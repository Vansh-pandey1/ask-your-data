import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.db import db_manager, validate_sql, validate_modifying_sql
from backend.app.workflow import run_text_to_sql_workflow, extract_json_from_response

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure clean database before and after each test."""
    db_manager.reset()
    yield
    db_manager.reset()


class ModifyingMockLLM:
    """Mock LLM simulating intent classification and SQL generation for all 5 statement types."""
    def __init__(self, intent: str, statement_type: str, sql: str, insight: str = ""):
        self.intent = intent
        self.statement_type = statement_type
        self.sql = sql
        self.insight = insight
        self.calls = []

    def invoke(self, messages):
        msg = str(messages[-1].content) if messages else ""
        self.calls.append(msg)

        if "intent classifier" in msg or "schema analyst" in msg:
            mock = MagicMock()
            mock.content = json.dumps({
                "intent": self.intent,
                "statement_type": self.statement_type,
                "is_answerable": True,
                "unanswerable_reason": None
            })
            return mock

        if "helpful SQL assistant" in msg or "DROP TABLE statement" in msg:
            mock = MagicMock()
            mock.content = self.sql
            return mock

        if "data analyst" in msg:
            mock = MagicMock()
            mock.content = self.insight or "Analysis completed."
            return mock

        mock = MagicMock()
        mock.content = self.sql
        return mock


def test_select_workflow_executes_safely():
    """1. Normal SELECT questions generate and execute correctly through read-only path."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    mock_llm = ModifyingMockLLM(
        intent="DATA_ANALYSIS",
        statement_type="SELECT",
        sql="SELECT product, SUM(amount) AS total FROM dataset GROUP BY product"
    )

    result = run_text_to_sql_workflow(
        question="What are total sales by product?",
        custom_llm=mock_llm
    )

    assert result.intent == "DATA_ANALYSIS"
    assert result.statement_type == "SELECT"
    assert result.error is None
    assert result.row_count > 0
    assert result.preview is None  # Normal SELECT has no modifying preview


def test_insert_request_generates_sql_without_executing():
    """2. INSERT requests generate SQL and preview without modifying the dataset."""
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    # Initial row count = 3
    initial_schema = db_manager.get_schema()
    assert initial_schema.total_rows == 3

    insert_sql = "INSERT INTO dataset (name, email, age, department, salary) VALUES ('Charlie', 'charlie@example.com', 29, 'Marketing', 75000)"
    mock_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="INSERT",
        sql=insert_sql
    )

    result = run_text_to_sql_workflow(
        question="Give me SQL to add a new employee named Charlie with salary 75000",
        custom_llm=mock_llm
    )

    assert result.intent == "SQL_GENERATION"
    assert result.statement_type == "INSERT"
    assert result.error is None
    assert result.generated_sql == insert_sql
    assert result.preview is not None
    assert result.preview["preview_type"] == "INSERT_PROPOSED"
    assert "not executed" in result.preview["warning"].lower()

    # STRICT GUARANTEE: Dataset row count remains exactly 3
    post_schema = db_manager.get_schema()
    assert post_schema.total_rows == 3

    # Direct DB verification: Charlie is NOT in the database
    check = client.post("/api/query", json={"sql": "SELECT COUNT(*) as cnt FROM dataset WHERE name = 'Charlie'"})
    assert check.status_code == 200
    assert check.json()["rows"][0]["cnt"] == 0


def test_update_request_generates_sql_and_previews_without_executing():
    """3. UPDATE requests generate SQL, preview matching rows, and do NOT modify dataset."""
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    update_sql = "UPDATE dataset SET salary = 120000 WHERE name = 'Alice'"
    mock_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="UPDATE",
        sql=update_sql
    )

    result = run_text_to_sql_workflow(
        question="Generate an UPDATE query to increase Alice's salary to 120000",
        custom_llm=mock_llm
    )

    assert result.intent == "SQL_GENERATION"
    assert result.statement_type == "UPDATE"
    assert result.error is None
    assert result.preview is not None
    assert result.preview["preview_type"] == "UPDATE_IMPACT"
    assert result.preview["where_clause_present"] is True
    assert result.preview["affected_rows_count"] == 1
    assert "not executed" in result.preview["warning"].lower()

    # STRICT GUARANTEE: Database salary for Alice is still 95000, NOT 120000
    check = client.post("/api/query", json={"sql": "SELECT salary FROM dataset WHERE name = 'Alice'"})
    assert check.status_code == 200
    assert check.json()["rows"][0]["salary"] == 95000


def test_update_without_where_clause_flags_prominent_warning():
    """4. UPDATE without WHERE clause flags critical warning about modifying all rows."""
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    update_all_sql = "UPDATE dataset SET salary = 100000"
    mock_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="UPDATE",
        sql=update_all_sql
    )

    result = run_text_to_sql_workflow(
        question="Update all salaries to 100000",
        custom_llm=mock_llm
    )

    assert result.preview is not None
    assert result.preview["where_clause_present"] is False
    assert "no where clause" in result.preview["warning"].lower()
    assert result.preview["is_destructive"] is True

    # Database remains unchanged
    check = client.post("/api/query", json={"sql": "SELECT salary FROM dataset WHERE name = 'Alice'"})
    assert check.json()["rows"][0]["salary"] == 95000


def test_delete_request_previews_targeted_rows_without_executing():
    """5. DELETE requests preview target rows without deleting anything."""
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    delete_sql = "DELETE FROM dataset WHERE age > 30"
    mock_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="DELETE",
        sql=delete_sql
    )

    result = run_text_to_sql_workflow(
        question="Write SQL to delete employees older than 30",
        custom_llm=mock_llm
    )

    assert result.intent == "SQL_GENERATION"
    assert result.statement_type == "DELETE"
    assert result.preview is not None
    assert result.preview["preview_type"] == "DELETE_TARGETS"
    assert result.preview["where_clause_present"] is True
    assert "not executed" in result.preview["warning"].lower()

    # Database still has 3 rows (none deleted)
    check = client.post("/api/query", json={"sql": "SELECT COUNT(*) as c FROM dataset"})
    assert check.json()["rows"][0]["c"] == 3


def test_delete_without_where_clause_flags_prominent_warning():
    """6. DELETE without WHERE clause flags critical warning about deleting all records."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    delete_all_sql = "DELETE FROM dataset"
    mock_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="DELETE",
        sql=delete_all_sql
    )

    result = run_text_to_sql_workflow(
        question="Delete all records",
        custom_llm=mock_llm
    )

    assert result.preview is not None
    assert result.preview["where_clause_present"] is False
    assert "no where clause" in result.preview["warning"].lower()
    assert result.preview["is_destructive"] is True

    # Sales still has 5 rows
    check = client.post("/api/query", json={"sql": "SELECT COUNT(*) as c FROM dataset"})
    assert check.json()["rows"][0]["c"] == 5


def test_drop_table_shows_destructive_warning_without_dropping():
    """7. DROP TABLE shows prominent destructive warning and does NOT drop table."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    drop_sql = "DROP TABLE dataset"
    mock_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="DROP",
        sql=drop_sql
    )

    result = run_text_to_sql_workflow(
        question="Give me SQL to drop the dataset table",
        custom_llm=mock_llm
    )

    assert result.intent == "SQL_GENERATION"
    assert result.statement_type == "DROP"
    assert result.preview is not None
    assert result.preview["preview_type"] == "DROP_WARNING"
    assert result.preview["is_destructive"] is True
    assert "destructive warning" in result.preview["warning"].lower()
    assert result.preview["affected_rows_count"] == 5

    # Table 'dataset' is still intact and queryable!
    check = client.post("/api/query", json={"sql": "SELECT COUNT(*) as c FROM dataset"})
    assert check.status_code == 200
    assert check.json()["rows"][0]["c"] == 5


def test_modifying_sql_cannot_reach_analytical_execution_function():
    """8. Modifying statements cannot reach db_manager.execute_query."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    # Direct call to db_manager.execute_query with modifying SQL must raise ValueError
    with pytest.raises(ValueError, match="only SELECT queries are allowed"):
        db_manager.execute_query("DROP TABLE dataset")

    with pytest.raises(ValueError, match="only SELECT queries are allowed"):
        db_manager.execute_query("DELETE FROM dataset WHERE amount > 100")

    with pytest.raises(ValueError, match="only SELECT queries are allowed"):
        db_manager.execute_query("UPDATE dataset SET amount = 0")

    with pytest.raises(ValueError, match="only SELECT queries are allowed"):
        db_manager.execute_query("INSERT INTO dataset (amount) VALUES (10)")


def test_multi_statement_queries_rejected():
    """9. Multi-statement queries are strictly rejected by both validators."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    stacked_sql = "SELECT * FROM dataset; DROP TABLE dataset;"
    with pytest.raises(ValueError, match="Only a single SQL statement is allowed"):
        validate_sql(stacked_sql)

    with pytest.raises(ValueError, match="Only a single SQL statement is allowed"):
        validate_modifying_sql(stacked_sql, "DROP")


def test_invalid_column_in_modifying_sql_rejected():
    """10. Modifying SQL referencing nonexistent columns is rejected."""
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    # 'bonus' does not exist in employees.csv
    bad_update = "UPDATE dataset SET bonus = 5000 WHERE name = 'Alice'"
    with pytest.raises(ValueError, match="No such column: bonus"):
        validate_modifying_sql(bad_update, "UPDATE")


def test_update_swap_regions_case_expression():
    """
    11. Regression test: 'change the region name east to west and west to east'
    should generate an UPDATE with CASE expression, classify as SQL_GENERATION/UPDATE,
    show accurate before/after preview, and never modify the dataset.
    """
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    # Initial state: 3 East, 2 West
    initial_check = client.post("/api/query", json={"sql": "SELECT region, COUNT(*) as cnt FROM dataset GROUP BY region"})
    initial_counts = {r["region"]: r["cnt"] for r in initial_check.json()["rows"]}
    assert initial_counts.get("East") == 3
    assert initial_counts.get("West") == 2

    # Mock LLM that correctly classifies as SQL_GENERATION/UPDATE
    swap_sql = "UPDATE dataset SET region = CASE WHEN region = 'East' THEN 'West' WHEN region = 'West' THEN 'East' ELSE region END WHERE region IN ('East', 'West')"
    mock_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="UPDATE",
        sql=swap_sql
    )

    result = run_text_to_sql_workflow(
        question="change the region name east to west and west to east",
        custom_llm=mock_llm
    )

    # Should be classified as SQL_GENERATION with UPDATE, NOT rejected by answerability
    assert result.intent == "SQL_GENERATION"
    assert result.statement_type == "UPDATE"
    assert result.error is None
    assert result.answerable is True
    assert result.generated_sql == swap_sql

    # Preview must show accurate before/after swap
    assert result.preview is not None
    assert result.preview["preview_type"] == "UPDATE_IMPACT"
    assert result.preview["where_clause_present"] is True
    assert result.preview["affected_rows_count"] == 5
    assert result.preview["before_after"] is not None
    assert len(result.preview["before_after"]) == 5

    # Verify before/after shows correct swap
    for item in result.preview["before_after"]:
        before_region = item["before"]["region"]
        after_region = item["after"]["region"]
        if before_region == "East":
            assert after_region == "West"
        elif before_region == "West":
            assert after_region == "East"

    # CRITICAL: Dataset must remain unchanged
    final_check = client.post("/api/query", json={"sql": "SELECT region, COUNT(*) as cnt FROM dataset GROUP BY region"})
    final_counts = {r["region"]: r["cnt"] for r in final_check.json()["rows"]}
    assert final_counts.get("East") == 3
    assert final_counts.get("West") == 2
    assert final_check.json()["rows"][0]["cnt"] == 3  # Still 3 East


def test_extract_json_helper_resilience():
    """12. extract_json_from_response handles markdown fences, surrounding text, and invalid JSON."""

    # Fenced JSON with json tag
    res1 = extract_json_from_response("```json\n{\"intent\": \"SQL_GENERATION\", \"statement_type\": \"UPDATE\"}\n```")
    assert res1 == {"intent": "SQL_GENERATION", "statement_type": "UPDATE"}

    # Fenced JSON without json tag
    res2 = extract_json_from_response("```\n{\"answerable\": true}\n```")
    assert res2 == {"answerable": True}

    # Surrounding conversational text
    res3 = extract_json_from_response("Here is the classification:\n{\"intent\": \"DATA_ANALYSIS\", \"statement_type\": \"SELECT\"}\nHope this helps!")
    assert res3 == {"intent": "DATA_ANALYSIS", "statement_type": "SELECT"}

    # Plain raw JSON
    res4 = extract_json_from_response('{"intent": "UNSUPPORTED", "statement_type": "UNKNOWN"}')
    assert res4 == {"intent": "UNSUPPORTED", "statement_type": "UNKNOWN"}

    # Malformed JSON raises ValueError
    with pytest.raises(ValueError, match="Failed to parse JSON"):
        extract_json_from_response("```json\n{intent: invalid_json}\n```")

    # Missing JSON object raises ValueError
    with pytest.raises(ValueError, match="No JSON object found"):
        extract_json_from_response("Just plain text with no braces.")


def test_update_increase_everybody_salary_preview():
    """
    13. Regression test: 'increase everybody salary by 50 percent'
    generates UPDATE dataset SET salary = salary * 1.5, flags WHERE warning,
    simulates preview before/after diffs, and leaves dataset unaltered.
    """
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    # Initial salaries
    initial_check = client.post("/api/query", json={"sql": "SELECT name, salary FROM dataset ORDER BY name"})
    initial_salaries = {r["name"]: r["salary"] for r in initial_check.json()["rows"]}

    update_sql = "UPDATE dataset SET salary = salary * 1.5"
    mock_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="UPDATE",
        sql=update_sql
    )

    result = run_text_to_sql_workflow(
        question="increase everybody salary by 50 percent",
        custom_llm=mock_llm
    )

    assert result.intent == "SQL_GENERATION"
    assert result.statement_type == "UPDATE"
    assert result.error is None
    assert result.answerable is True
    assert result.generated_sql == update_sql

    # Preview checks
    assert result.preview is not None
    assert result.preview["preview_type"] == "UPDATE_IMPACT"
    assert result.preview["where_clause_present"] is False
    assert "No WHERE clause detected" in result.preview["warning"]
    assert result.preview["affected_rows_count"] == len(initial_salaries)
    assert len(result.preview["before_after"]) == len(initial_salaries)

    # Check 50% increase in simulated preview diffs
    for item in result.preview["before_after"]:
        emp_name = item["before"]["name"]
        orig_sal = initial_salaries[emp_name]
        assert item["before"]["salary"] == orig_sal
        assert item["after"]["salary"] == round(orig_sal * 1.5, 2)

    # Dataset remains completely unaltered
    final_check = client.post("/api/query", json={"sql": "SELECT name, salary FROM dataset ORDER BY name"})
    final_salaries = {r["name"]: r["salary"] for r in final_check.json()["rows"]}
    assert final_salaries == initial_salaries


def test_classify_intent_fenced_json_never_silently_defaults():
    """
    14. Intent classifier with markdown code fences successfully extracts intent
    and does not trigger false DATA_ANALYSIS fallback.
    """
    class FencedMockLLM:
        def __init__(self, response_text: str):
            self.response_text = response_text
        def invoke(self, messages):
            mock = MagicMock()
            mock.content = self.response_text
            return mock

    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    # LLM returns markdown fenced JSON for intent
    fenced_content = "```json\n{\"intent\": \"SQL_GENERATION\", \"statement_type\": \"UPDATE\"}\n```"
    mock_llm = FencedMockLLM(fenced_content)

    # Workflow state test directly on classify_intent_node or via run_text_to_sql_workflow
    # With FencedMockLLM, intent classification will parse cleanly as SQL_GENERATION / UPDATE
    result = run_text_to_sql_workflow(
        question="change region east to west",
        custom_llm=mock_llm
    )
    # Generated SQL will use the mock content, but intent is correctly SQL_GENERATION
    assert result.intent == "SQL_GENERATION"
    assert result.statement_type == "UPDATE"


def test_deleting_france_and_spain_rows():
    """
    15. Regression test: Dedicated SQLite fixture with Geography values France and Spain.
    Verifies:
    - SELECT for France returns expected France rows.
    - DELETE preview for equivalent condition reports same matching rows and count.
    - DELETE preview does not change database contents.
    - A genuine zero-match condition reports zero.
    - A preview execution failure reports an error, not zero.
    """
    import pandas as pd

    df = pd.DataFrame({
        "id": [1, 2, 3, 4],
        "Geography": ["France", "Spain", "France", "Spain"],
        "Balance": [1000, 2000, 3000, 4000]
    })
    db_manager.load_dataset(df, "geography_test.csv")

    # 1. SELECT for France returns the expected France rows
    sel_res = db_manager.execute_query("SELECT * FROM dataset WHERE geography = 'France'")
    assert sel_res.row_count == 2
    assert len(sel_res.rows) == 2
    france_ids = {r["id"] for r in sel_res.rows}
    assert france_ids == {1, 3}

    # 2. DELETE preview for the equivalent condition reports the same matching rows and count
    preview = db_manager.execute_safe_preview("DELETE FROM dataset WHERE geography = 'France'", "DELETE")
    assert preview["affected_rows_count"] == 2
    assert preview["affected_rows_count"] == sel_res.row_count
    assert len(preview["proposed_data"]) == 2
    preview_ids = {r["id"] for r in preview["proposed_data"]}
    assert preview_ids == france_ids
    assert "2 matching rows targeted for deletion" in preview["warning"]

    # 3. DELETE preview does not change the database contents
    post_check = db_manager.execute_query("SELECT COUNT(*) as c FROM dataset")
    assert post_check.rows[0]["c"] == 4
    all_rows = db_manager.execute_query("SELECT id FROM dataset ORDER BY id")
    assert [r["id"] for r in all_rows.rows] == [1, 2, 3, 4]

    # 4. A genuine zero-match condition reports zero
    zero_preview = db_manager.execute_safe_preview("DELETE FROM dataset WHERE geography = 'Germany'", "DELETE")
    assert zero_preview["affected_rows_count"] == 0
    assert len(zero_preview["proposed_data"]) == 0
    assert "0 matching rows targeted for deletion" in zero_preview["warning"]

    # 5. A preview execution failure reports an error, not zero
    # Test that db_manager.execute_safe_preview raises ValueError (not swallowed into 0 rows)
    with patch.object(db_manager, "execute_query", side_effect=ValueError("Simulated preview execution failure")):
        with pytest.raises(ValueError, match="Could not compute preview for DELETE statement"):
            db_manager.execute_safe_preview("DELETE FROM dataset WHERE geography = 'France'", "DELETE")

    # Verify that in end-to-end workflow, preview execution failure reports error in AskResponse and not 0 rows
    with patch.object(db_manager, "execute_query", side_effect=ValueError("Simulated preview execution failure")):
        mock_llm = ModifyingMockLLM(
            intent="SQL_GENERATION",
            statement_type="DELETE",
            sql="DELETE FROM dataset WHERE geography = 'France'"
        )
        res = run_text_to_sql_workflow("delete rows where geography is France", custom_llm=mock_llm)
        assert res.error is not None
        assert "Could not compute preview for DELETE statement" in res.error
        assert res.preview is None


def test_distinguish_row_column_and_table_deletion():
    """
    16. Regression test: Distinguish row deletion, column deletion, and whole-table deletion:
    - Row deletion: statement_type = DELETE, preview_type = DELETE_TARGETS
    - Column deletion: statement_type = ALTER_TABLE, preview_type = COLUMN_DROP_PREVIEW
    - Table deletion: statement_type = DROP, preview_type = DROP_WARNING
    All modifying statements remain strictly preview-only and never alter the uploaded dataset.
    """
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    # Initial employee count = 3, columns = ['name', 'email', 'age', 'department', 'salary']
    initial_schema = db_manager.get_schema()
    assert initial_schema.total_rows == 3
    assert len(initial_schema.columns) == 5

    # Case A: Row deletion ("delete rows where age > 30")
    delete_rows_sql = "DELETE FROM dataset WHERE age > 30"
    mock_llm_row = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="DELETE",
        sql=delete_rows_sql
    )
    result_row = run_text_to_sql_workflow("delete rows where age > 30", custom_llm=mock_llm_row)
    assert result_row.statement_type == "DELETE"
    assert result_row.error is None
    assert result_row.preview is not None
    assert result_row.preview["preview_type"] == "DELETE_TARGETS"
    assert result_row.preview["where_clause_present"] is True

    # Case B: Column deletion ("delete column email")
    drop_col_sql = "ALTER TABLE dataset DROP COLUMN email"
    mock_llm_col = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="ALTER_TABLE",
        sql=drop_col_sql
    )
    result_col = run_text_to_sql_workflow("delete column email", custom_llm=mock_llm_col)
    assert result_col.statement_type == "ALTER_TABLE"
    assert result_col.error is None
    assert result_col.preview is not None
    assert result_col.preview["preview_type"] == "COLUMN_DROP_PREVIEW"
    assert result_col.preview["target_column"] == "email"
    assert "email" not in result_col.preview["remaining_columns"]
    assert "name" in result_col.preview["remaining_columns"]
    assert len(result_col.preview["remaining_columns"]) == 4
    # Returned preview columns should be the remaining columns
    assert "email" not in result_col.columns
    assert "name" in result_col.columns

    # Case C: Whole-table deletion ("drop the entire table")
    drop_tbl_sql = "DROP TABLE dataset"
    mock_llm_tbl = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="DROP",
        sql=drop_tbl_sql
    )
    result_tbl = run_text_to_sql_workflow("drop the entire table", custom_llm=mock_llm_tbl)
    assert result_tbl.statement_type == "DROP"
    assert result_tbl.error is None
    assert result_tbl.preview is not None
    assert result_tbl.preview["preview_type"] == "DROP_WARNING"
    assert result_tbl.preview["is_destructive"] is True

    # STRICT GUARANTEE: Dataset remains 100% unaltered
    post_schema = db_manager.get_schema()
    assert post_schema.total_rows == 3
    assert len(post_schema.columns) == 5
    assert {c.name for c in post_schema.columns} == {"name", "email", "age", "department", "salary"}


def test_column_deletion_validations_and_unsupported_reasons():
    """
    17. Column deletion validations:
    - Missing column reports clear schema error.
    - SQLite version < 3.35.0 reports unsupported SQLite version.
    - Dropping only column in table is rejected.
    """
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    # 1. Non-existent column raises ValueError
    bad_col_sql = "ALTER TABLE dataset DROP COLUMN nonexistent_col"
    with pytest.raises(ValueError, match="No such column: 'nonexistent_col'"):
        validate_modifying_sql(bad_col_sql, "ALTER_TABLE")

    # 2. Mock SQLite version < 3.35.0
    with patch("sqlite3.sqlite_version_info", (3, 34, 0)), patch("sqlite3.sqlite_version", "3.34.0"):
        with pytest.raises(ValueError, match="requires SQLite 3.35.0 or higher"):
            db_manager.check_column_droppable("email")

    # 3. Only column in table cannot be dropped
    import pandas as pd
    single_col_df = pd.DataFrame({"single_col": [1, 2, 3]})
    db_manager.load_dataset(single_col_df, "single.csv")
    with pytest.raises(ValueError, match="does not allow dropping the only column"):
        db_manager.check_column_droppable("single_col")


def test_column_deletion_preview_never_shows_no_matching_records():
    """
    18. Verifies that column-removal preview displays target column and relevant schema impact,
    and returns remaining columns in AskResponse.
    """
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    schema_before = db_manager.get_schema()
    col_names = [c.name for c in schema_before.columns]
    assert "salesperson" in col_names

    drop_sql = "ALTER TABLE dataset DROP COLUMN salesperson"
    preview = db_manager.execute_safe_preview(drop_sql, "ALTER_TABLE")

    assert preview["preview_type"] == "COLUMN_DROP_PREVIEW"
    assert preview["target_column"] == "salesperson"
    assert "salesperson" not in preview["remaining_columns"]
    assert preview["affected_rows_count"] == schema_before.total_rows
    assert len(preview["proposed_data"]) > 0
    # Every row in proposed_data must not contain 'salesperson'
    for r in preview["proposed_data"]:
        assert "salesperson" not in r
        assert "product" in r

    # Dataset table schema is completely intact
    schema_after = db_manager.get_schema()
    assert "salesperson" in [c.name for c in schema_after.columns]


def test_ai_insights_generated_for_all_statement_types():
    """
    19. Verify AI insights are generated for SELECT, INSERT, UPDATE, DELETE, DROP, and ALTER_TABLE.
    Guarantees:
    - Each statement type populates result.insight.
    - Modifying statements retain preview_only flag and preview metadata.
    - Dataset remains 100% unaltered.
    """
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    # A. SELECT insight
    select_llm = ModifyingMockLLM(
        intent="DATA_ANALYSIS",
        statement_type="SELECT",
        sql="SELECT department, AVG(salary) as avg_sal FROM dataset GROUP BY department",
        insight="Engineering department has an average salary of 102,500 across 2 employees."
    )
    sel_res = run_text_to_sql_workflow("What is the average salary by department?", custom_llm=select_llm)
    assert sel_res.statement_type == "SELECT"
    assert sel_res.insight == "Engineering department has an average salary of 102,500 across 2 employees."
    assert sel_res.preview is None

    # B. INSERT insight
    insert_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="INSERT",
        sql="INSERT INTO dataset (name, salary) VALUES ('Dave', 80000)",
        insight="This INSERT statement would add 1 new employee (Dave) with salary 80,000. This is a preview and no records were added."
    )
    ins_res = run_text_to_sql_workflow("Add a new employee Dave", custom_llm=insert_llm)
    assert ins_res.statement_type == "INSERT"
    assert ins_res.insight is not None
    assert "preview" in ins_res.insight.lower()
    assert ins_res.preview is not None

    # C. UPDATE insight
    update_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="UPDATE",
        sql="UPDATE dataset SET salary = salary * 1.1 WHERE department = 'Engineering'",
        insight="This UPDATE statement would modify 2 Engineering employees by giving a 10% raise. No changes were executed against the dataset."
    )
    upd_res = run_text_to_sql_workflow("Give Engineering a 10% raise", custom_llm=update_llm)
    assert upd_res.statement_type == "UPDATE"
    assert upd_res.insight is not None
    assert "update" in upd_res.insight.lower() or "raise" in upd_res.insight.lower()
    assert upd_res.preview is not None
    assert upd_res.preview["affected_rows_count"] == 2

    # D. DELETE insight
    delete_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="DELETE",
        sql="DELETE FROM dataset WHERE age < 30",
        insight="This DELETE statement targets 1 employee under age 30 for deletion. This preview is non-destructive and no rows were deleted."
    )
    del_res = run_text_to_sql_workflow("Delete employees younger than 30", custom_llm=delete_llm)
    assert del_res.statement_type == "DELETE"
    assert del_res.insight is not None
    assert "delete" in del_res.insight.lower()
    assert del_res.preview is not None
    assert del_res.preview["affected_rows_count"] == 1

    # E. DROP insight
    drop_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="DROP",
        sql="DROP TABLE dataset",
        insight="DESTRUCTIVE IMPACT: This statement would remove the dataset table and all 3 rows. No database changes were applied."
    )
    drop_res = run_text_to_sql_workflow("Drop the table", custom_llm=drop_llm)
    assert drop_res.statement_type == "DROP"
    assert drop_res.insight is not None
    assert "destructive" in drop_res.insight.lower() or "remove" in drop_res.insight.lower()
    assert drop_res.preview is not None

    # F. ALTER_TABLE (column drop) insight
    alter_llm = ModifyingMockLLM(
        intent="SQL_GENERATION",
        statement_type="ALTER_TABLE",
        sql="ALTER TABLE dataset DROP COLUMN age",
        insight="Dropping column 'age' would reduce the dataset from 5 to 4 columns. This is a non-destructive preview."
    )
    alt_res = run_text_to_sql_workflow("Remove column age", custom_llm=alter_llm)
    assert alt_res.statement_type == "ALTER_TABLE"
    assert alt_res.insight is not None
    assert alt_res.preview is not None
    assert alt_res.preview["target_column"] == "age"

    # STRICT ZERO-MODIFICATION GUARANTEE
    final_schema = db_manager.get_schema()
    assert final_schema.total_rows == 3
    assert len(final_schema.columns) == 5


def test_schema_caching_and_in_place_renaming_performance():
    """
    20. Performance and correctness validation:
    - load_dataset renames in place and restores original columns on df.
    - db_manager caches schema to avoid redundant SQLite PRAGMA table_info queries.
    - Cache invalidates properly on load_dataset and reset.
    """
    import pandas as pd
    df = pd.DataFrame({
        "User Email Address": ["a@test.com", "b@test.com"],
        "Annual Salary ($)": [100000, 120000]
    })
    original_cols = list(df.columns)

    schema1 = db_manager.load_dataset(df, "perf_test.csv")
    # Original DataFrame columns were preserved without copying
    assert list(df.columns) == original_cols

    # Repeated get_schema calls return the exact cached object
    schema2 = db_manager.get_schema()
    assert schema1 is schema2

    # Reset clears the cache
    db_manager.reset()
    assert db_manager._cached_schema is None


def test_csv_encoding_compatibility_preserved():
    """
    21. Preserve CSV encoding support across UTF-8, UTF-8-sig, Windows-1252, and Latin-1.
    """
    from backend.app.profiler import load_dataframe_from_bytes

    # UTF-8 with BOM
    bom_csv = "﻿name,score\nRené,95\n".encode("utf-8-sig")
    df_bom = load_dataframe_from_bytes(bom_csv)
    assert df_bom["name"].iloc[0] == "René"

    # Windows-1252 with special characters like € or curly quotes
    cp1252_csv = "product,price\nWidget,10 €\n".encode("cp1252")
    df_cp = load_dataframe_from_bytes(cp1252_csv)
    assert "10" in str(df_cp["price"].iloc[0])

    # Latin-1
    latin_csv = "city,temp\nMünchen,22\n".encode("latin-1")
    df_latin = load_dataframe_from_bytes(latin_csv)
    assert df_latin["city"].iloc[0] == "München"

