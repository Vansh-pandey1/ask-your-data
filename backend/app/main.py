from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .profiler import profile_csv, preview_and_profile_csv
from .schemas import DatasetProfile, DatasetPreviewResponse

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
    Accept a CSV file upload, validate size and format, return real preview rows and profile.

    Returns:
        DatasetPreviewResponse containing file metadata, first preview rows,
        and the full deterministic dataset profile.
    """
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)}MB"
        )

    try:
        return preview_and_profile_csv(content, file.filename or "uploaded.csv")
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


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "Ask Your Data backend is running"}
