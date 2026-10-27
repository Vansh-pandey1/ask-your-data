from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from .profiler import profile_csv, load_dataframe_from_bytes, profile_dataframe
from .schemas import (
    DatasetProfile,
    DatasetPreviewResponse,
    QueryRequest,
    QueryResult,
    SchemaResponse,
    AskRequest,
    AskResponse
)
from .db import db_manager
from .workflow import run_text_to_sql_workflow

MAX_FILE_SIZE = 104_857_600  # 100 MiB (104,857,600 bytes) limit

app = FastAPI(
    title="Ask Your Data v2 API",
    description="Backend for Ask Your Data - CSV profiling and natural-language SQL queries",
    version="0.1.0"
)

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/upload", response_model=DatasetPreviewResponse)
async def upload_csv(file: UploadFile = File(...)):
    """
    Accept a CSV file upload, ingest into SQLite database, and return preview + profile.
    """
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)} MiB"
        )

    try:
        df = load_dataframe_from_bytes(content)
        filename = file.filename or "uploaded.csv"
        # Ingest into active SQLite table
        db_manager.load_dataset(df, filename)
        # Calculate profile
        profile = profile_dataframe(df, filename)
        # Extract preview rows - evaluate once
        preview_df = df.head(5).where(pd.notnull(df.head(5)), None)
        preview_rows = preview_df.to_dict(orient="records")

        return DatasetPreviewResponse(
            file_name=filename,
            total_rows=profile.total_rows,
            total_columns=profile.total_columns,
            column_names=[str(c) for c in df.columns],
            preview_rows=preview_rows,
            profile=profile
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/profile", response_model=DatasetProfile)
async def profile_upload(file: UploadFile = File(...)):
    """Accept a CSV file upload and return a deterministic dataset profile."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)} MiB"
        )
    try:
        return profile_csv(content, file.filename or "uploaded.csv")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/schema", response_model=SchemaResponse)
async def get_schema():
    """Get the active dataset schema."""
    try:
        return db_manager.get_schema()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/query", response_model=QueryResult)
async def execute_query(req: QueryRequest):
    """
    Execute a validated, read-only SQL query against the active dataset.
    Rejects any non-SELECT, multi-statement, or mutating queries.
    """
    try:
        return db_manager.execute_query(req.sql, req.row_limit or 100)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



import logging

logger = logging.getLogger(__name__)


def _map_provider_exception(exc: Exception) -> HTTPException:
    """
    Inspect exception and chained causes (__cause__, __context__) to extract provider error details.
    Maps status codes cleanly to HTTPException without exposing secrets or raw stack traces.
    """
    # Unroll chained exceptions to find the root provider error if wrapped
    target: BaseException = exc
    visited = set()
    while target is not None and id(target) not in visited:
        visited.add(id(target))
        if hasattr(target, "code") or hasattr(target, "status"):
            break
        target = target.__cause__ or target.__context__ or target
        if target is exc or id(target) in visited:
            break

    code = getattr(target, "code", None)
    status = str(getattr(target, "status", "")).upper()
    message = str(getattr(target, "message", str(target))).lower()

    # Log sanitized provider failure diagnostic on backend only (never log sensitive user inputs or secrets)
    logger.warning(
        f"[PROVIDER ERROR] type={type(target).__name__} code={code} status={status}"
    )

    # 1. Rate limiting / Quota exhausted
    if code == 429 or status == "RESOURCE_EXHAUSTED" or "resource_exhausted" in message or "quota" in message:
        return HTTPException(
            status_code=429,
            detail="The AI service rate limit has been reached. Please wait a moment and try again."
        )

    # 2. Transient upstream server unavailability or deadline exceeded
    if code in (503, 504) or status in ("UNAVAILABLE", "DEADLINE_EXCEEDED") or "deadline" in message:
        return HTTPException(
            status_code=503,
            detail="The AI service is temporarily unavailable. Please try again shortly."
        )

    # 3. Authentication or permission failures (never leak keys or details to frontend)
    if code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED") or "api_key" in message:
        return HTTPException(
            status_code=503,
            detail="The AI service authentication failed. Please check backend configuration."
        )

    # 4. Resource not found (e.g. unknown model identifier)
    if code == 404 or status == "NOT_FOUND":
        return HTTPException(
            status_code=404,
            detail="The requested AI model or resource was not found. Please verify configuration."
        )

    # 5. Invalid arguments / token limits
    if code == 400 or status == "INVALID_ARGUMENT" or "token limit" in message:
        return HTTPException(
            status_code=400,
            detail="The AI request could not be processed due to invalid parameters or length limits."
        )

    # 6. Upstream 5xx errors from provider
    if isinstance(code, int) and 500 <= code < 600:
        return HTTPException(
            status_code=502,
            detail="The upstream AI provider encountered an internal error. Please try again."
        )

    # 7. Known Google API errors without code
    from google.api_core.exceptions import GoogleAPIError
    if isinstance(target, GoogleAPIError):
        return HTTPException(
            status_code=503,
            detail="The AI service is temporarily unavailable. Please try again shortly."
        )

    # 8. Unhandled internal error fallback (guarantees JSON response, never exposes stack traces)
    return HTTPException(
        status_code=500,
        detail="An unexpected internal error occurred while processing your query. Please try again."
    )


@app.post("/api/ask", response_model=AskResponse)
async def ask_question(req: AskRequest):
    """
    Translate a natural-language question into SQL, validate it,
    execute it against the active dataset, and return results.
    """
    import anyio

    try:
        result = await anyio.to_thread.run_sync(
            run_text_to_sql_workflow,
            req.question,
            req.row_limit or 100
        )
        return result

    except ValueError as e:
        # Standard input/dataset validation errors
        raise HTTPException(status_code=400, detail=str(e)) from e

    except HTTPException:
        # Re-raise already constructed HTTP exceptions
        raise

    except Exception as e:
        # Differentiated mapping for provider and runtime exceptions
        raise _map_provider_exception(e) from e



@app.post("/api/reset")
async def reset_dataset():
    """Reset the active database and wipe loaded dataset."""
    db_manager.reset()
    return {"status": "cleared"}


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "Ask Your Data backend is running"}
