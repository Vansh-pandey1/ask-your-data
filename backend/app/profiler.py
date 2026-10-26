import io
from typing import Union, List
import pandas as pd
from .schemas import ColumnSummary, DatasetProfile, ColumnType, DatasetPreviewResponse


def load_dataframe_from_bytes(file_bytes_or_stream: Union[bytes, io.BytesIO, io.TextIOBase]) -> pd.DataFrame:
    """
    Helper to parse CSV data into a validated pandas DataFrame.
    Supports common encodings in a controlled order:
    1. UTF-8 (or UTF-8-sig if BOM is present)
    2. UTF-8-sig
    3. Windows-1252 (cp1252)
    4. ISO-8859-1 (latin-1) as fallback
    Reads directly from byte streams to avoid intermediate full-string allocations.
    """
    if isinstance(file_bytes_or_stream, str):
        return pd.read_csv(io.StringIO(file_bytes_or_stream))

    if isinstance(file_bytes_or_stream, bytes):
        raw_bytes = file_bytes_or_stream
    elif hasattr(file_bytes_or_stream, 'read'):
        raw_bytes = file_bytes_or_stream.read()
        if not isinstance(raw_bytes, bytes):
            raise ValueError("Stream did not return bytes")
    else:
        raise ValueError("Invalid file input type")

    if not raw_bytes or len(raw_bytes.strip()) == 0:
        raise ValueError("CSV file is empty")
    if b"\x00" in raw_bytes:
        raise ValueError("CSV parsing error: file contains null bytes (binary or corrupt file)")

    # Controlled encoding order: prefer UTF-8, then Windows-1252, then ISO-8859-1 fallback
    encodings = (
        ("utf-8-sig", "utf-8", "cp1252", "latin-1")
        if raw_bytes.startswith(b"\xef\xbb\xbf")
        else ("utf-8", "utf-8-sig", "cp1252", "latin-1")
    )

    decode_error = None
    for enc in encodings:
        try:
            # Stream bytes directly to pandas; avoids decoding entire file into a string first
            df = pd.read_csv(io.BytesIO(raw_bytes), encoding=enc)
            if len(df) == 0:
                raise ValueError("CSV file has no data rows")
            return df
        except UnicodeDecodeError as e:
            decode_error = e
            continue
        except pd.errors.EmptyDataError:
            raise ValueError("CSV file is empty")

    raise ValueError(
        f"CSV parsing error: Could not decode file with supported encodings (UTF-8, UTF-8-sig, Windows-1252, ISO-8859-1). {decode_error}"
    )


def profile_dataframe(df: pd.DataFrame, filename: str) -> DatasetProfile:
    """Calculate deterministic dataset profile from a pandas DataFrame."""
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
                    "median": float(stats["50%"])  # reuse describe() 50th percentile
                }
        elif pd.api.types.is_bool_dtype(series):
            col_type = ColumnType.boolean
        else:
            # Check for date / datetime strings
            parsed_dates = None
            non_null = series.dropna()
            if len(non_null) > 0:
                # Fast sample check first: if sample values aren't dates, don't parse the whole column
                sample = non_null.iloc[:min(len(non_null), 50)]
                try:
                    sample_parsed = pd.to_datetime(sample, errors='coerce', format='mixed')
                    if sample_parsed.notna().all():
                        parsed = pd.to_datetime(non_null, errors='coerce', format='mixed')
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


def profile_csv(file_bytes_or_stream: Union[bytes, io.BytesIO, io.TextIOBase], filename: str) -> DatasetProfile:
    """Calculate deterministic dataset profile from CSV data."""
    df = load_dataframe_from_bytes(file_bytes_or_stream)
    return profile_dataframe(df, filename)


def preview_and_profile_csv(
    file_bytes_or_stream: Union[bytes, io.BytesIO, io.TextIOBase],
    filename: str,
    preview_limit: int = 5
) -> DatasetPreviewResponse:
    """Calculate deterministic profile and extract preview rows from CSV data."""
    df = load_dataframe_from_bytes(file_bytes_or_stream)
    profile = profile_dataframe(df, filename)

    # Evaluate head once to avoid duplication
    preview_head = df.head(preview_limit)
    preview_df = preview_head.where(pd.notnull(preview_head), None)
    preview_rows = preview_df.to_dict(orient="records")

    return DatasetPreviewResponse(
        file_name=filename,
        total_rows=profile.total_rows,
        total_columns=profile.total_columns,
        column_names=[str(c) for c in df.columns],
        preview_rows=preview_rows,
        profile=profile
    )
