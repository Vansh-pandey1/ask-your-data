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


def test_api_upload_100mib_boundary():
    """Verify exactly 100 MiB (104,857,600 bytes) limit boundary."""
    import backend.app.main as main_mod
    limit = 104_857_600
    assert main_mod.MAX_FILE_SIZE == limit


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


def test_api_upload_windows_1252_csv_and_query():
    """
    Upload a Windows-1252 encoded CSV with non-ASCII characters ('é' and '’').
    Verify it ingests successfully and can be queried via /api/query.
    """
    csv_text = "id,name,role,description\n1,René,Manager,Customer’s account\n2,Aimée,Analyst,Company’s data\n"
    csv_bytes = csv_text.encode("cp1252")

    # Upload
    upload_resp = client.post("/api/upload", files={"file": ("users_cp1252.csv", csv_bytes, "text/csv")})
    assert upload_resp.status_code == 200
    upload_data = upload_resp.json()
    assert upload_data["total_rows"] == 2
    assert upload_data["preview_rows"][0]["name"] == "René"
    assert upload_data["preview_rows"][0]["description"] == "Customer’s account"

    # Query loaded dataset
    query_resp = client.post("/api/query", json={"sql": "SELECT name, description FROM dataset WHERE id = 1"})
    assert query_resp.status_code == 200
    query_data = query_resp.json()
    assert query_data["row_count"] == 1
    assert query_data["rows"][0]["name"] == "René"
    assert query_data["rows"][0]["description"] == "Customer’s account"


def test_api_upload_utf8_bom_csv_and_query():
    """
    Upload a UTF-8 with BOM CSV.
    Verify BOM is stripped from columns and data queries cleanly.
    """
    csv_text = "﻿id,title,value\n10,Café,150.00\n20,Théâtre,250.00\n"
    csv_bytes = csv_text.encode("utf-8-sig")

    upload_resp = client.post("/api/upload", files={"file": ("bom_data.csv", csv_bytes, "text/csv")})
    assert upload_resp.status_code == 200
    upload_data = upload_resp.json()
    assert upload_data["column_names"] == ["id", "title", "value"]

    query_resp = client.post("/api/query", json={"sql": "SELECT title, value FROM dataset WHERE id = 10"})
    assert query_resp.status_code == 200
    assert query_resp.json()["rows"][0]["title"] == "Café"
    assert query_resp.json()["rows"][0]["value"] == 150.00


def test_api_upload_malformed_corrupt_csv_400():
    """Upload binary or corrupt CSV data returns HTTP 400 with a clear error message."""
    corrupt_bytes = b"\x00\x01\x02\x03\x04\xff\xfe"
    upload_resp = client.post("/api/upload", files={"file": ("corrupt.bin", corrupt_bytes, "text/csv")})
    assert upload_resp.status_code == 400
    assert "csv parsing error" in upload_resp.json()["detail"].lower()

