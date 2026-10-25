from pydantic import BaseModel
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