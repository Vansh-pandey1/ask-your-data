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


class MockLLM:
    """Mock LLM returning sequential predetermined answers."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0

    def invoke(self, messages):
        resp = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        mock = MagicMock()
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

    # First response uses invalid column 'nonexistent_col', second response fixes it
    mock_llm = MockLLM([
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
    """Mutating SQL is blocked by sqlglot validator during workflow."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    # Attempt to inject DROP TABLE twice
    mock_llm = MockLLM([
        "DROP TABLE dataset",
        "DROP TABLE dataset"
    ])

    result = run_text_to_sql_workflow(
        question="Drop the table",
        custom_llm=mock_llm
    )

    assert result.correction_attempted is True
    assert result.error is not None
    assert "only select queries are allowed" in result.error.lower()
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
