import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from google.genai.errors import ServerError, ClientError
from backend.app.main import app
from backend.app.db import db_manager

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    db_manager.reset()
    yield
    db_manager.reset()


def _setup_test_dataset():
    import pandas as pd
    df = pd.DataFrame({"col1": [1, 2]})
    db_manager.load_dataset(df, "test.csv")


def test_provider_server_error_504_returns_503():
    """Verify real google.genai ServerError (504 DEADLINE_EXCEEDED) returns HTTP 503."""
    _setup_test_dataset()
    error = ServerError(code=504, response_json={"error": {"status": "DEADLINE_EXCEEDED", "message": "Deadline exceeded"}})
    with patch("backend.app.main.run_text_to_sql_workflow", side_effect=error):
        resp = client.post("/api/ask", json={"question": "What is the sum?"})
        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"].lower()


def test_provider_client_error_429_returns_429():
    """Verify real google.genai ClientError (429 RESOURCE_EXHAUSTED) returns HTTP 429."""
    _setup_test_dataset()
    error = ClientError(code=429, response_json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}})
    with patch("backend.app.main.run_text_to_sql_workflow", side_effect=error):
        resp = client.post("/api/ask", json={"question": "What is the sum?"})
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["detail"].lower()


def test_provider_client_error_400_invalid_argument_returns_400():
    """Verify ClientError with code 400 (INVALID_ARGUMENT) returns HTTP 400."""
    _setup_test_dataset()
    error = ClientError(code=400, response_json={"error": {"status": "INVALID_ARGUMENT", "message": "Bad request"}})
    with patch("backend.app.main.run_text_to_sql_workflow", side_effect=error):
        resp = client.post("/api/ask", json={"question": "What is the sum?"})
        assert resp.status_code == 400
        assert "invalid parameters" in resp.json()["detail"].lower()


def test_provider_client_error_403_auth_failure_returns_503_without_leaking_key():
    """Verify auth errors (403/401) return sanitized 503 and do not leak keys/secrets."""
    _setup_test_dataset()
    secret_key = "AIzaSySecretApiKey12345"
    error = ClientError(code=403, response_json={"error": {"status": "PERMISSION_DENIED", "message": f"Invalid API key {secret_key}"}})
    with patch("backend.app.main.run_text_to_sql_workflow", side_effect=error):
        resp = client.post("/api/ask", json={"question": "What is the sum?"})
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert "authentication failed" in detail.lower()
        assert secret_key not in detail


def test_chained_provider_exception_unrolled():
    """Verify chained exceptions (RuntimeError caused by ServerError) are unrolled to correct status."""
    _setup_test_dataset()
    inner = ServerError(code=504, response_json={"error": {"status": "DEADLINE_EXCEEDED", "message": "Timeout"}})
    outer = RuntimeError("Workflow node failed")
    outer.__cause__ = inner

    with patch("backend.app.main.run_text_to_sql_workflow", side_effect=outer):
        resp = client.post("/api/ask", json={"question": "What is the sum?"})
        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"].lower()


def test_unexpected_runtime_error_returns_structured_500():
    """Verify unexpected non-provider runtime errors return structured HTTP 500 JSON, not plain text."""
    _setup_test_dataset()
    with patch("backend.app.main.run_text_to_sql_workflow", side_effect=RuntimeError("Internal state bug")):
        resp = client.post("/api/ask", json={"question": "What is the sum?"})
        assert resp.status_code == 500
        assert "unexpected internal error" in resp.json()["detail"].lower()
        # Verify response is valid JSON
        assert "detail" in resp.json()

