import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.db import validate_sql, db_manager

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure a clean database state before each test."""
    db_manager.reset()
    yield
    db_manager.reset()


def test_sql_validator_accepts_valid_queries():
    """Valid read-only analytical SQL statements must pass validation."""
    valid_queries = [
        "SELECT * FROM dataset",
        "SELECT product, SUM(amount) FROM dataset GROUP BY product",
        "SELECT * FROM dataset WHERE amount > 100 ORDER BY amount DESC",
        "WITH summary AS (SELECT region, COUNT(*) as cnt FROM dataset GROUP BY region) SELECT * FROM summary",
        "SELECT a.product, b.amount FROM dataset a JOIN dataset b ON a.product = b.product",
        "SELECT COUNT(DISTINCT salesperson) FROM dataset"
    ]
    for q in valid_queries:
        validate_sql(q)  # Should not raise


def test_sql_validator_rejects_mutating_or_stacked_queries():
    """Mutating or stacked SQL queries must be rejected with ValueError."""
    prohibited_queries = [
        ("DROP TABLE dataset", "only SELECT queries are allowed"),
        ("DELETE FROM dataset WHERE 1=1", "only SELECT queries are allowed"),
        ("INSERT INTO dataset VALUES (1, 2)", "only SELECT queries are allowed"),
        ("UPDATE dataset SET amount = 0", "only SELECT queries are allowed"),
        ("ALTER TABLE dataset ADD COLUMN hacked TEXT", "only SELECT queries are allowed"),
        ("SELECT * FROM dataset; DROP TABLE dataset;", "Multi-statement queries are prohibited"),
        ("SELECT * FROM dataset; SELECT 1;", "Multi-statement queries are prohibited"),
        ("ATTACH DATABASE 'test.db' AS test", "only SELECT queries are allowed"),
        ("SELECT * FROM dataset WHERE 1=1; PRAGMA query_only = OFF", "Multi-statement queries are prohibited"),
        ("", "Query string cannot be empty"),
    ]
    for q, err_snippet in prohibited_queries:
        with pytest.raises(ValueError, match=err_snippet):
            validate_sql(q)


def test_query_without_dataset_raises_400():
    """Querying when no dataset has been uploaded must return HTTP 400."""
    response = client.post("/api/query", json={"sql": "SELECT * FROM dataset"})
    assert response.status_code == 400
    assert "no active dataset loaded" in response.json()["detail"].lower()


def test_real_query_sales_dataset():
    """Upload sales.csv and execute analytical query with exact mathematical assertions."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        upload_resp = client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})
    assert upload_resp.status_code == 200

    # Query 1: Total amount per product ordered by total descending
    query = "SELECT product, ROUND(SUM(amount), 2) AS total_sales FROM dataset GROUP BY product ORDER BY total_sales DESC"
    resp = client.post("/api/query", json={"sql": query})
    assert resp.status_code == 200
    data = resp.json()
    assert data["columns"] == ["product", "total_sales"]
    assert data["row_count"] == 3
    # Widget B: 235 + 235 = 470.0
    # Widget A: 120.5 + 120.5 = 241.0
    # Widget C: 89.99
    assert data["rows"] == [
        {"product": "Widget B", "total_sales": 470.0},
        {"product": "Widget A", "total_sales": 241.0},
        {"product": "Widget C", "total_sales": 89.99}
    ]

    # Query 2: Salesperson transaction count
    query2 = "SELECT salesperson, COUNT(*) as tx_count FROM dataset GROUP BY salesperson ORDER BY tx_count DESC, salesperson ASC"
    resp2 = client.post("/api/query", json={"sql": query2})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["rows"] == [
        {"salesperson": "Alice", "tx_count": 2},
        {"salesperson": "Bob", "tx_count": 2},
        {"salesperson": "Charlie", "tx_count": 1}
    ]


def test_real_query_employees_dataset():
    """Upload employees.csv and execute query against distinct schema."""
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        upload_resp = client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})
    assert upload_resp.status_code == 200

    query = "SELECT department, AVG(salary) AS avg_salary, COUNT(*) as head_count FROM dataset GROUP BY department ORDER BY avg_salary DESC"
    resp = client.post("/api/query", json={"sql": query})
    assert resp.status_code == 200
    data = resp.json()
    assert data["rows"] == [
        {"department": "Engineering", "avg_salary": 102500.0, "head_count": 2},
        {"department": "Marketing", "avg_salary": 72000.0, "head_count": 1}
    ]


def test_dataset_isolation_wipes_previous_dataset():
    """Uploading a new dataset completely isolates data and drops the old schema."""
    # 1. Upload sales.csv
    csv_sales = FIXTURES_DIR / "sales.csv"
    with open(csv_sales, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    # Verify sales column works
    resp1 = client.post("/api/query", json={"sql": "SELECT amount FROM dataset LIMIT 1"})
    assert resp1.status_code == 200

    # 2. Upload employees.csv
    csv_emp = FIXTURES_DIR / "employees.csv"
    with open(csv_emp, "rb") as f:
        client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    # 3. Querying 'amount' must fail honestly because employees table has no such column
    resp2 = client.post("/api/query", json={"sql": "SELECT amount FROM dataset"})
    assert resp2.status_code == 400
    assert "no such column: amount" in resp2.json()["detail"].lower()

    # 4. Querying 'salary' must succeed
    resp3 = client.post("/api/query", json={"sql": "SELECT salary FROM dataset LIMIT 1"})
    assert resp3.status_code == 200


def test_query_syntax_error_returns_honest_error():
    """Invalid SQL syntax must return 400 with real error, never fake data."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    resp = client.post("/api/query", json={"sql": "SELECT FROM WHERE"})
    assert resp.status_code == 400
    assert "syntax error" in resp.json()["detail"].lower()


def test_query_schema_endpoint():
    """GET /api/schema returns table structure and column types."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    resp = client.get("/api/schema")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["table_name"] == "dataset"
    assert schema["file_name"] == "sales.csv"
    assert schema["total_rows"] == 5
    col_names = [c["name"] for c in schema["columns"]]
    assert set(col_names) == {"date", "product", "region", "amount", "salesperson"}
