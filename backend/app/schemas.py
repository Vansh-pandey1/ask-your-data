from pydantic import BaseModel, model_validator
from typing import List, Optional, Any, Dict
from enum import Enum


class ColumnType(str, Enum):
    string = "string"
    integer = "integer"
    float = "float"
    boolean = "boolean"
    date = "date"
    datetime = "datetime"
    text = "text"


class ColumnSummary(BaseModel):
    column_name: str
    column_type: ColumnType
    null_count: int
    null_percentage: float
    unique_count: int
    numeric_stats: Optional[dict] = None  # min, max, mean, median
    categorical_stats: Optional[dict] = None  # top values and counts
    date_range: Optional[dict] = None  # min_date, max_date


class DatasetProfile(BaseModel):
    file_name: str
    total_rows: int
    total_columns: int
    duplicate_row_count: int
    columns: List[ColumnSummary]
    summary_notes: str = "Deterministic profile calculated from actual CSV data"


class DatasetPreviewResponse(BaseModel):
    file_name: str
    total_rows: int
    total_columns: int
    column_names: List[str]
    preview_rows: List[Dict[str, Any]]
    profile: DatasetProfile


class QueryRequest(BaseModel):
    sql: str
    row_limit: Optional[int] = 100


class QueryResult(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int
    executed_sql: str
    execution_time_ms: float


class SchemaColumn(BaseModel):
    name: str
    data_type: str
    original_name: Optional[str] = None


class SchemaResponse(BaseModel):
    table_name: str
    file_name: str
    total_rows: int
    columns: List[SchemaColumn]


class AskRequest(BaseModel):
    question: Optional[str] = None
    query: Optional[str] = None
    row_limit: Optional[int] = 100

    @model_validator(mode="after")
    def resolve_question(self):
        val = self.question or self.query
        if not val or not str(val).strip():
            raise ValueError("Field 'question' (or 'query') is required")
        self.question = str(val).strip()
        return self


class AskResponse(BaseModel):
    question: str
    generated_sql: str = ""
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []
    row_count: int = 0
    correction_attempted: bool = False
    answerable: bool = True
    explanation: Optional[str] = None
    insight: Optional[str] = None
    error: Optional[str] = None
    intent: str = "DATA_ANALYSIS"
    statement_type: str = "SELECT"
    preview: Optional[Dict[str, Any]] = None
    execution_time_ms: float = 0.0
    llm_calls_count: int = 0