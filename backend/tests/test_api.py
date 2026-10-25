import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app.main import app, MAX_FILE_SIZE

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_api_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_api_upload_sales_csv():
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        response = client.post("/api/upload", files={"file": ("sales.csv", f, "text/csv")})

    assert response.status_code == 200
    data = response.json()
    assert data["file_name"] == "sales.csv"
    assert data["total_rows"] == 5
    assert data["total_columns"] == 5
    assert data["column_names"] == ["date", "product", "region", "amount", "salesperson"]
    assert len(data["preview_rows"]) == 5
    # Verify first row matches actual data
    first_row = data["preview_rows"][0]
    assert first_row["date"] == "2024-01-15"
    assert first_row["product"] == "Widget A"
    assert first_row["amount"] == 120.50
    # Verify profile is attached
    assert data["profile"]["total_rows"] == 5
    assert len(data["profile"]["columns"]) == 5


def test_api_upload_employees_csv():
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        response = client.post("/api/upload", files={"file": ("employees.csv", f, "text/csv")})

    assert response.status_code == 200
    data = response.json()
    assert data["file_name"] == "employees.csv"
    assert data["total_rows"] == 3
    assert data["total_columns"] == 5
    assert data["column_names"] == ["name", "email", "age", "department", "salary"]
    assert len(data["preview_rows"]) == 3
    first_row = data["preview_rows"][0]
    assert first_row["name"] == "Alice"
    assert first_row["department"] == "Engineering"
    assert first_row["salary"] == 95000


def test_api_upload_oversized_file_400(monkeypatch):
    import backend.app.main as main_mod
    monkeypatch.setattr(main_mod, "MAX_FILE_SIZE", 100)  # Temporarily set limit to 100 bytes
    large_content = b"a" * 200
    response = client.post("/api/upload", files={"file": ("big.csv", large_content, "text/csv")})
    assert response.status_code == 400
    assert "exceeds maximum allowed size" in response.json()["detail"].lower()


def test_api_profile_sales_csv():
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        response = client.post("/api/profile", files={"file": ("sales.csv", f, "text/csv")})

    assert response.status_code == 200
    data = response.json()
    assert data["file_name"] == "sales.csv"
    assert data["total_rows"] == 5
    assert data["total_columns"] == 5
    assert data["duplicate_row_count"] == 0
    assert len(data["columns"]) == 5


def test_api_profile_employees_csv():
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        response = client.post("/api/profile", files={"file": ("employees.csv", f, "text/csv")})

    assert response.status_code == 200
    data = response.json()
    assert data["file_name"] == "employees.csv"
    assert data["total_rows"] == 3
    assert data["total_columns"] == 5


def test_api_profile_empty_csv_400():
    response = client.post("/api/profile", files={"file": ("empty.csv", b"", "text/csv")})
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_api_profile_header_only_csv_400():
    response = client.post("/api/profile", files={"file": ("header.csv", b"a,b,c\n", "text/csv")})
    assert response.status_code == 400
    assert "no data rows" in response.json()["detail"].lower()
