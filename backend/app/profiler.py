import io
from typing import Union, List
import pandas as pd
from .schemas import ColumnSummary, DatasetProfile, ColumnType


def profile_csv(file_bytes_or_stream: Union[bytes, io.BytesIO, io.TextIOBase], filename: str) -> DatasetProfile:
    """
    Calculate deterministic dataset profile from CSV data.

    Args:
        file_bytes_or_stream: CSV data as bytes, BytesIO, or text stream
        filename: Original filename for metadata

    Returns:
        DatasetProfile with calculated metrics
    """
    if isinstance(file_bytes_or_stream, bytes):
        raw_bytes = file_bytes_or_stream
    elif hasattr(file_bytes_or_stream, 'read'):
        content = file_bytes_or_stream.read()
        raw_bytes = content.encode('utf-8') if isinstance(content, str) else content
    else:
        raise ValueError("Invalid file input type")

    if not raw_bytes or len(raw_bytes.strip()) == 0:
        raise ValueError("CSV file is empty")

    try:
        df = pd.read_csv(io.BytesIO(raw_bytes))
    except pd.errors.EmptyDataError:
        raise ValueError("CSV file is empty")
    except Exception as e:
        raise ValueError(f"CSV parsing error: {str(e)}") from e

    if len(df) == 0:
        raise ValueError("CSV file has no data rows")

    total_rows = len(df)
    total_columns = len(df.columns)
    duplicate_rows = int(df.duplicated().sum())

    columns: List[ColumnSummary] = []
    for col in df.columns:
        series = df[col]
        col_type = ColumnType.text
        numeric_stats = None
        categorical_stats = None
        date_range = None

        if pd.api.types.is_numeric_dtype(series):
            if pd.api.types.is_integer_dtype(series):
                col_type = ColumnType.integer
            else:
                col_type = ColumnType.float
            stats = series.dropna().describe()
            if not stats.empty:
                numeric_stats = {
                    "min": float(stats["min"]),
                    "max": float(stats["max"]),
                    "mean": float(stats["mean"]),
                    "median": float(series.dropna().median())
                }
        elif pd.api.types.is_bool_dtype(series):
            col_type = ColumnType.boolean
        else:
            # Check for date / datetime strings
            parsed_dates = None
            non_null = series.dropna()
            if len(non_null) > 0:
                try:
                    # Attempt parsing dates with pandas
                    parsed = pd.to_datetime(non_null, errors='coerce', format='mixed')
                    # If all non-null values parsed successfully as dates
                    if parsed.notna().all():
                        parsed_dates = parsed
                        col_type = ColumnType.date
                        date_range = {
                            "min_date": parsed_dates.min().strftime("%Y-%m-%d"),
                            "max_date": parsed_dates.max().strftime("%Y-%m-%d")
                        }
                except Exception:
                    pass

            if col_type != ColumnType.date:
                col_type = ColumnType.string
                counts = series.value_counts().head(5)
                categorical_stats = {str(k): int(v) for k, v in counts.items()}

        null_count = int(series.isna().sum())
        null_percentage = (null_count / total_rows) * 100 if total_rows > 0 else 0.0
        unique_count = int(series.nunique())

        column_summary = ColumnSummary(
            column_name=str(col),
            column_type=col_type,
            null_count=null_count,
            null_percentage=round(null_percentage, 2),
            unique_count=unique_count,
            numeric_stats=numeric_stats,
            categorical_stats=categorical_stats,
            date_range=date_range
        )
        columns.append(column_summary)

    summary_notes = f"Profile calculated from {total_rows} rows and {total_columns} columns with {duplicate_rows} duplicate rows"

    return DatasetProfile(
        file_name=filename,
        total_rows=total_rows,
        total_columns=total_columns,
        duplicate_row_count=duplicate_rows,
        columns=columns,
        summary_notes=summary_notes
    )
