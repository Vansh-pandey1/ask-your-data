import pytest
from pathlib import Path
from backend.app.profiler import profile_csv
from backend.app.schemas import ColumnType

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_profile_sales_dataset():
    """Verify sales.csv produces exact known deterministic statistics."""
    csv_path = FIXTURES_DIR / "sales.csv"
    with open(csv_path, "rb") as f:
        profile = profile_csv(f.read(), "sales.csv")

    assert profile.file_name == "sales.csv"
    assert profile.total_rows == 5
    assert profile.total_columns == 5
    assert profile.duplicate_row_count == 0  # Dates differ across all rows

    col_map = {c.column_name: c for c in profile.columns}
    assert set(col_map.keys()) == {"date", "product", "region", "amount", "salesperson"}

    # Amount column numeric stats
    amount_col = col_map["amount"]
    assert amount_col.column_type == ColumnType.float
    assert amount_col.null_count == 0
    assert amount_col.null_percentage == 0.0
    assert amount_col.unique_count == 3
    assert amount_col.numeric_stats is not None
    assert amount_col.numeric_stats["min"] == 89.99
    assert amount_col.numeric_stats["max"] == 235.00
    assert round(amount_col.numeric_stats["mean"], 2) == 160.20
    assert amount_col.numeric_stats["median"] == 120.50

    # Categorical distributions
    region_col = col_map["region"]
    assert region_col.column_type == ColumnType.string
    assert region_col.unique_count == 2
    assert region_col.categorical_stats == {"East": 3, "West": 2}

    product_col = col_map["product"]
    assert product_col.unique_count == 3
    assert product_col.categorical_stats == {"Widget A": 2, "Widget B": 2, "Widget C": 1}

    # Date column
    date_col = col_map["date"]
    assert date_col.column_type == ColumnType.date
    assert date_col.date_range is not None
    assert date_col.date_range["min_date"] == "2024-01-15"
    assert date_col.date_range["max_date"] == "2024-01-19"


def test_profile_employees_dataset():
    """Verify employees.csv produces completely distinct, accurate statistics."""
    csv_path = FIXTURES_DIR / "employees.csv"
    with open(csv_path, "rb") as f:
        profile = profile_csv(f.read(), "employees.csv")

    assert profile.file_name == "employees.csv"
    assert profile.total_rows == 3
    assert profile.total_columns == 5
    assert profile.duplicate_row_count == 0

    col_map = {c.column_name: c for c in profile.columns}
    assert set(col_map.keys()) == {"name", "email", "age", "department", "salary"}

    # Age stats
    age_col = col_map["age"]
    assert age_col.column_type == ColumnType.integer
    assert age_col.numeric_stats["min"] == 25
    assert age_col.numeric_stats["max"] == 35
    assert age_col.numeric_stats["mean"] == 30.0
    assert age_col.numeric_stats["median"] == 30.0

    # Salary stats
    salary_col = col_map["salary"]
    assert salary_col.column_type == ColumnType.integer
    assert salary_col.numeric_stats["min"] == 72000
    assert salary_col.numeric_stats["max"] == 110000
    assert round(salary_col.numeric_stats["mean"], 2) == 92333.33
    assert salary_col.numeric_stats["median"] == 95000.0

    # Department category counts
    dept_col = col_map["department"]
    assert dept_col.categorical_stats == {"Engineering": 2, "Marketing": 1}


def test_profile_empty_csv_raises_error():
    """Empty CSV must raise ValueError with clear message."""
    with pytest.raises(ValueError, match="CSV file is empty"):
        profile_csv(b"", "empty.csv")


def test_profile_malformed_csv_raises_error():
    """Malformed/unparseable CSV must raise ValueError."""
    # NUL bytes or unparseable text
    with pytest.raises(ValueError, match="CSV parsing error"):
        profile_csv(b"\x00\x01\x02\x03\xff", "corrupt.csv")


def test_profile_header_only_csv_raises_error():
    """CSV with header but 0 data rows must raise ValueError."""
    with pytest.raises(ValueError, match="CSV file has no data rows"):
        profile_csv(b"col1,col2,col3\n", "header_only.csv")
