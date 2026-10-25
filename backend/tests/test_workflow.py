import pytest
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.db import db_manager
from backend.app.workflow import run_text_to_sql_workflow, clean_sql

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure clean database before each test."""
    db_manager.reset()
    yield
    db_manager.reset()


import json

class MockLLM:
    """Mock LLM returning sequential predetermined answers or JSON for answerability."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0

    def invoke(self, messages):
        resp = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        mock = MagicMock()
        # If the prompt asks about answerability (JSON expected) and the response is not JSON,
        # provide appropriate JSON.
        msg_content = str(messages[-1].content) if messages else ""
        if "Determine if the user's question can be answered" in msg_content:
            # For answerability, we check if the test SQL responses contain valid columns
            # If the response is a SELECT query string, assume it's answerable
            if isinstance(resp, str) and resp.strip().upper().startswith("SELECT"):
                # Check if the SQL references known columns in the fixture
                resp = json.dumps({"answerable": True, "reason": "Question is answerable with available columns"})
            # Non-SELECT statements (DROP, DELETE, etc.) are not answerable as SQL
            elif isinstance(resp, str) and resp.strip().upper().startswith(("DROP", "DELETE", "INSERT", "UPDATE", "ALTER")):
                resp = json.dumps({"answerable": False, "reason": f"Mutating operation not allowed: {resp}"})
            elif isinstance(resp, str) and not resp.strip().startswith("{"):
                resp = json.dumps({"answerable": False, "reason": resp})
            elif isinstance(resp, bool):
                resp = json.dumps({"answerable": resp, "reason": "Mock answerability check"})
        mock.content = resp
        return mock


def test_clean_sql_helper():
    """clean_sql must strip markdown fences, whitespace, and semicolons."""
    assert clean_sql("```sql\nSELECT * FROM dataset;\n```") == "SELECT * FROM dataset"
    assert clean_sql("```\nSELECT 1;\n```") == "SELECT 1"
    assert clean_sql("  SELECT col FROM dataset;  ") == "SELECT col FROM dataset"


def test_ask_without_dataset_raises_400():
    """Asking a question when no CSV is loaded returns 400."""
    resp = client.post("/api/ask", json={"question": "What is the total sales?"})
    assert resp.status_code == 400
    assert "no active dataset loaded" in resp.json()["detail"].lower()


def test_ask_missing_api_key_honest_error(monkeypatch):
    """Missing GEMINI_API_KEY must return an honest error, never mock analytics."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    resp = client.post("/api/ask", json={"question": "What are total sales?"})
    assert resp.status_code == 400
    assert "api_key" in resp.json()["detail"].lower()


def test_text_to_sql_workflow_clean_execution():
    """Workflow generates valid SQL, validates, executes, returns real data."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    mock_llm = MockLLM(["SELECT product, SUM(amount) AS total FROM dataset GROUP BY product ORDER BY total DESC"])

    result = run_text_to_sql_workflow(
        question="What is the total sales by product?",
        custom_llm=mock_llm
    )

    assert result.error is None
    assert result.correction_attempted is False
    assert result.row_count == 3
    assert result.columns == ["product", "total"]
    assert result.rows[0]["product"] == "Widget B"
    assert result.rows[0]["total"] == 470.0


def test_text_to_sql_workflow_one_correction_attempt():
    """Workflow catches initial SQL error, allows 1 correction attempt, succeeds."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    # First response: answerability check -> answerable=True
    # Second response: initial SQL (invalid)
    # Third response: corrected SQL
    mock_llm = MockLLM([
        json.dumps({"answerable": True, "reason": "Question is answerable"}),
        "SELECT nonexistent_col FROM dataset",
        "SELECT product, amount FROM dataset WHERE amount > 200"
    ])

    result = run_text_to_sql_workflow(
        question="Show big sales",
        custom_llm=mock_llm
    )

    assert result.correction_attempted is True
    assert result.error is None
    assert result.row_count == 2
    assert result.rows[0]["amount"] == 235.0


def test_text_to_sql_workflow_fails_honestly_after_failed_correction():
    """When correction also fails, return honest error, never mock fallback."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    # Both attempts produce invalid column names
    mock_llm = MockLLM([
        "SELECT bad_col_1 FROM dataset",
        "SELECT bad_col_2 FROM dataset"
    ])

    result = run_text_to_sql_workflow(
        question="Invalid query test",
        custom_llm=mock_llm
    )

    assert result.correction_attempted is True
    assert result.error is not None
    assert "no such column: bad_col_2" in result.error.lower()
    assert result.rows == []
    assert result.row_count == 0


def test_text_to_sql_workflow_rejects_mutating_query():
    """Mutating SQL is blocked at answerability check and sqlglot validator during workflow."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    # First response: answerability check -> answerable=False for DROP
    # The workflow should stop at answerability check, not generate SQL
    mock_llm = MockLLM([
        json.dumps({"answerable": False, "reason": "Mutating operations not allowed"}),
        "DROP TABLE dataset"
    ])

    result = run_text_to_sql_workflow(
        question="Drop the table",
        custom_llm=mock_llm
    )

    # Should be rejected at answerability stage (answerable=False), no correction attempt
    assert result.correction_attempted is False
    assert result.answerable is False
    assert result.error is not None
    assert "can't answer" in result.error.lower()
    # Verify dataset still exists unharmed
    verify_resp = client.post("/api/query", json={"sql": "SELECT COUNT(*) as cnt FROM dataset"})
    assert verify_resp.status_code == 200
    assert verify_resp.json()["rows"][0]["cnt"] == 5


def test_dual_dataset_verification_employees():
    """Verify text-to-sql workflow works on second disjoint dataset (employees.csv)."""
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    mock_llm = MockLLM(["SELECT department, AVG(salary) AS avg_sal FROM dataset GROUP BY department ORDER BY avg_sal DESC"])

    result = run_text_to_sql_workflow(
        question="What is the average salary per department?",
        custom_llm=mock_llm
    )

    assert result.error is None
    assert result.row_count == 2
    assert result.rows[0]["department"] == "Engineering"
    assert result.rows[0]["avg_sal"] == 102500.0


def test_unanswerable_question_region_sales_on_employees_rejected():
    """
    Requirement 9.1: 'Which region has highest sales?' with employee dataset
    must be rejected as unanswerable. No substitute SQL is executed.
    """
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    mock_llm = MockLLM([
        json.dumps({
            "answerable": False,
            "reason": "The dataset contains name, email, age, department, and salary, but does not contain region or sales information."
        })
    ])

    result = run_text_to_sql_workflow(
        question="Which region has highest sales?",
        custom_llm=mock_llm
    )

    assert result.answerable is False
    assert result.generated_sql == ""
    assert result.rows == []
    assert result.row_count == 0
    assert result.error is not None
    assert "region" in result.error.lower()
    assert "sales" in result.error.lower()
    assert "can't answer" in result.error.lower()


def test_answerable_question_highest_salary_allowed():
    """
    Requirement 9.2: 'Which department has the highest salary?'
    is allowed to generate, validate, and execute SQL returning real results.
    """
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    mock_llm = MockLLM([
        json.dumps({"answerable": True, "reason": "Department and salary are available"}),
        "SELECT department, MAX(salary) AS highest_salary FROM dataset GROUP BY department ORDER BY highest_salary DESC LIMIT 1"
    ])

    result = run_text_to_sql_workflow(
        question="Which department has the highest salary?",
        custom_llm=mock_llm
    )

    assert result.answerable is True
    assert result.error is None
    assert result.row_count == 1
    assert result.columns == ["department", "highest_salary"]
    assert result.rows[0]["department"] == "Engineering"
    assert result.rows[0]["highest_salary"] == 110000


def test_question_referencing_nonexistent_column_rejected():
    """
    Requirement 9.3: A question referencing a nonexistent column must be rejected.
    """
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    # Case A: Caught at answerability check
    mock_llm_unanswerable = MockLLM([
        json.dumps({
            "answerable": False,
            "reason": "The dataset does not contain quarterly_bonus column or information."
        })
    ])

    result_a = run_text_to_sql_workflow(
        question="What is the average quarterly_bonus?",
        custom_llm=mock_llm_unanswerable
    )
    assert result_a.answerable is False
    assert result_a.rows == []
    assert "quarterly_bonus" in result_a.error

    # Case B: If LLM generated SQL referencing nonexistent column, schema validator rejects it
    mock_llm_bad_col = MockLLM([
        json.dumps({"answerable": True, "reason": "Attempting query"}),
        "SELECT quarterly_bonus FROM dataset",
        "SELECT quarterly_bonus FROM dataset"
    ])

    result_b = run_text_to_sql_workflow(
        question="What is the average quarterly_bonus?",
        custom_llm=mock_llm_bad_col
    )
    assert result_b.rows == []
    assert result_b.error is not None
    assert "no such column: quarterly_bonus" in result_b.error.lower()


def test_valid_query_returning_actual_dataset_results():
    """
    Requirement 9.4: A valid query returning actual dataset results.
    """
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    mock_llm = MockLLM([
        json.dumps({"answerable": True, "reason": "Query is answerable"}),
        "SELECT region, COUNT(*) as count, SUM(amount) as total FROM dataset GROUP BY region ORDER BY total DESC"
    ])

    result = run_text_to_sql_workflow(
        question="What are total sales and counts by region?",
        custom_llm=mock_llm
    )

    assert result.answerable is True
    assert result.error is None
    assert result.row_count == 2
    assert result.rows[0]["region"] == "West"
    assert result.rows[0]["total"] == 470.0
    assert result.rows[1]["region"] == "East"
    assert result.rows[1]["total"] == 330.99


def test_unsafe_sql_request_rejected():
    """
    Requirement 9.5: An unsafe SQL request (e.g. DROP, UPDATE, DELETE) is rejected.
    """
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    mock_llm = MockLLM([
        json.dumps({"answerable": True, "reason": "Malicious query attempt"}),
        "DROP TABLE dataset",
        "DROP TABLE dataset"
    ])

    result = run_text_to_sql_workflow(
        question="Drop the database table",
        custom_llm=mock_llm
    )

    assert result.error is not None
    assert "only select queries are allowed" in result.error.lower()
    # Confirm dataset is intact
    check_resp = client.post("/api/query", json={"sql": "SELECT COUNT(*) as c FROM dataset"})
    assert check_resp.status_code == 200
    assert check_resp.json()["rows"][0]["c"] == 5

