from fastapi import FastAPI, UploadFile, File, HTTPException
from .profiler import profile_csv
from .schemas import DatasetProfile

app = FastAPI(
    title="Ask Your Data v2 API",
    description="Backend for Ask Your Data - CSV profiling and natural-language SQL queries",
    version="0.1.0"
)


@app.post("/api/profile", response_model=DatasetProfile)
async def profile_upload(file: UploadFile = File(...)):
    """
    Accept a CSV file upload and return a deterministic dataset profile.

    The profile includes: total rows, columns, inferred column types,
    missing values per column, duplicate row count, and numeric/categorical/date statistics.

    Returns 400 if the file is empty, malformed, or has no data rows.
    """
    content = await file.read()
    try:
        return profile_csv(content, file.filename or "uploaded.csv")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "Ask Your Data backend is running"}
