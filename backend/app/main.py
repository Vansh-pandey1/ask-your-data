from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from .profiler import profile_csv, load_dataframe_from_bytes, profile_dataframe
from .schemas import (
    DatasetProfile,
    DatasetPreviewResponse,
    QueryRequest,
    QueryResult,
    SchemaResponse
)
from .db import db_manager

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB limit

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
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)}MB"
        )

    try:
        df = load_dataframe_from_bytes(content)
        filename = file.filename or "uploaded.csv"
        # Ingest into active SQLite table
        db_manager.load_dataset(df, filename)
        # Calculate profile
        profile = profile_dataframe(df, filename)
        # Extract preview rows
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
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)}MB"
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


@app.post("/api/reset")
async def reset_dataset():
    """Reset the active database and wipe loaded dataset."""
    db_manager.reset()
    return {"status": "cleared"}


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "Ask Your Data backend is running"}
