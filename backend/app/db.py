import re
import time
import sqlite3
import threading
from typing import List, Dict, Any, Optional
import pandas as pd
import sqlglot
from sqlglot import exp
from .schemas import QueryResult, SchemaResponse, SchemaColumn


def sanitize_identifier(col: str) -> str:
    """Convert an arbitrary column name into a safe SQL identifier."""
    cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', col.strip())
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"col_{cleaned}"
    return cleaned.lower()


def validate_sql(sql: str) -> None:
    """
    Validate that the SQL statement is strictly a single, read-only SELECT query.
    This performs basic syntax and structure validation WITHOUT requiring an active dataset.
    Raises ValueError with a clear explanation if validation fails.
    """
    if not sql or not sql.strip():
        raise ValueError("Query string cannot be empty")

    try:
        parsed = sqlglot.parse(sql, read="sqlite")
    except Exception as e:
        raise ValueError(f"SQL syntax error: {str(e)}") from e

    if len(parsed) == 0:
        raise ValueError("Query string contains no valid SQL statements")

    if len(parsed) > 1:
        raise ValueError("Only a single SQL statement is allowed. Multi-statement queries are prohibited.")

    stmt = parsed[0]

    # Verify statement root is a SELECT or UNION
    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise ValueError(f"Prohibited query type: only SELECT queries are allowed (found: {type(stmt).__name__})")

    # Search for forbidden modifications anywhere in the AST
    forbidden_types = (
        exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
        exp.Command, exp.Create
    )
    for forbidden in forbidden_types:
        if stmt.find(forbidden):
            raise ValueError(f"Prohibited operation in query: {forbidden.__name__} is not allowed")

    # Check for forbidden SQLite pragmas or commands
    sql_upper = sql.upper()
    forbidden_keywords = ["PRAGMA", "ATTACH", "DETACH", "VACUUM"]
    for kw in forbidden_keywords:
        if re.search(r'\b' + kw + r'\b', sql_upper):
            raise ValueError(f"Prohibited keyword '{kw}' found in query")


def validate_sql_against_schema(sql: str) -> None:
    """
    Validate that the SQL statement references only tables and columns
    that exist in the active dataset schema or are defined as aliases/CTEs within the query.
    Must be called after validate_sql() and requires an active dataset.
    """
    # First run basic validation
    validate_sql(sql)

    # Now validate against active schema
    parsed = sqlglot.parse(sql, read="sqlite")
    stmt = parsed[0]

    schema = db_manager.get_schema()
    base_table = schema.table_name.lower()
    valid_columns = {col.name.lower() for col in schema.columns}

    # Collect CTE names and table aliases defined in the query
    cte_names = {cte.alias.lower() for cte in stmt.find_all(exp.CTE) if cte.alias}
    table_aliases = {t.alias.lower() for t in stmt.find_all(exp.Table) if t.alias}
    valid_tables = {base_table} | cte_names | table_aliases

    # Collect column aliases defined in the query (e.g. SUM(amount) AS total_sales)
    column_aliases = {a.alias.lower() for a in stmt.find_all(exp.Alias) if a.alias}
    allowed_columns = valid_columns | column_aliases

    # Check table references
    for table in stmt.find_all(exp.Table):
        tbl_name = table.name.lower()
        if tbl_name and tbl_name not in valid_tables:
            raise ValueError(f"Table '{table.name}' does not exist in active dataset schema")

    # Check column references (skip wildcard)
    for column in stmt.find_all(exp.Column):
        col_name = column.name
        if not col_name or col_name == "*":
            continue
        # Skip alias definitions themselves (e.g., in `AS col_alias`)
        if isinstance(column.parent, exp.Alias) and column.parent.alias == col_name:
            continue
        if col_name.lower() not in allowed_columns:
            raise ValueError(
                f"No such column: {col_name}. It does not exist in active dataset schema. "
                f"Available columns: {', '.join(sorted(valid_columns))}"
            )


class DatabaseManager:
    """
    Manages an isolated SQLite in-memory database holding the active uploaded dataset.
    Enforces read-only querying, row limits, and execution timeouts.
    """

    def __init__(self, table_name: str = "dataset"):
        self.table_name = table_name
        self._conn: Optional[sqlite3.Connection] = None
        self._file_name: Optional[str] = None
        self._total_rows: int = 0
        self._col_mapping: Dict[str, str] = {}  # original -> sanitized
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Reset the active database connection and wipe all state."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None
            self._file_name = None
            self._total_rows = 0
            self._col_mapping = {}

    def load_dataset(self, df: pd.DataFrame, filename: str) -> SchemaResponse:
        """
        Load a DataFrame into an isolated SQLite in-memory database table named `dataset`.
        Overwrites any previous dataset to ensure strict isolation.
        """
        with self._lock:
            # Close existing connection to ensure complete isolation
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass

            # Create fresh in-memory database
            conn = sqlite3.connect(":memory:", check_same_thread=False, timeout=5.0)

            # Build mapping of original column names to sanitized SQL column names
            mapping: Dict[str, str] = {}
            used_names = set()
            for col in df.columns:
                sanitized = sanitize_identifier(str(col))
                # Avoid collisions
                original_sanitized = sanitized
                counter = 1
                while sanitized in used_names:
                    sanitized = f"{original_sanitized}_{counter}"
                    counter += 1
                used_names.add(sanitized)
                mapping[str(col)] = sanitized

            # Rename columns in copy and load into SQLite
            df_sql = df.rename(columns=mapping)
            df_sql.to_sql(self.table_name, conn, index=False, if_exists="replace")

            self._conn = conn
            self._file_name = filename
            self._total_rows = len(df)
            self._col_mapping = mapping

            return self._get_schema_internal()

    def _get_schema_internal(self) -> SchemaResponse:
        """Inspect the active table and return SchemaResponse."""
        if self._conn is None:
            raise ValueError("No active dataset loaded. Please upload a CSV first.")

        cur = self._conn.cursor()
        cur.execute(f"PRAGMA table_info({self.table_name});")
        # Returns (cid, name, type, notnull, dflt_value, pk)
        cols_info = cur.fetchall()

        reverse_mapping = {v: k for k, v in self._col_mapping.items()}
        schema_cols = [
            SchemaColumn(
                name=col[1],
                data_type=col[2] or "TEXT",
                original_name=reverse_mapping.get(col[1], col[1])
            )
            for col in cols_info
        ]

        return SchemaResponse(
            table_name=self.table_name,
            file_name=self._file_name or "unknown",
            total_rows=self._total_rows,
            columns=schema_cols
        )

    def get_schema(self) -> SchemaResponse:
        """Get the active dataset schema."""
        with self._lock:
            return self._get_schema_internal()

    def execute_query(self, sql: str, row_limit: int = 100, timeout_seconds: float = 5.0) -> QueryResult:
        """
        Validate and execute a read-only analytical SQL query against the active dataset.
        Enforces timeout and row limits.
        """
        # Validate query before touching the database
        validate_sql_against_schema(sql)

        with self._lock:
            if self._conn is None:
                raise ValueError("No active dataset loaded. Please upload a CSV first.")

            # Append or enforce LIMIT if not present or exceeds maximum
            # Check row limit bounds (1 to 1000)
            effective_limit = max(1, min(row_limit, 1000))

            start_time = time.perf_counter()
            try:
                # Enable SQLite query_only mode to enforce engine-level read-only
                self._conn.execute("PRAGMA query_only = ON;")

                cur = self._conn.cursor()
                cur.execute(sql)

                cols = [desc[0] for desc in cur.description] if cur.description else []
                # Fetch up to effective_limit rows
                raw_rows = cur.fetchmany(effective_limit)

                rows = [dict(zip(cols, row)) for row in raw_rows]
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

                return QueryResult(
                    columns=cols,
                    rows=rows,
                    row_count=len(rows),
                    executed_sql=sql,
                    execution_time_ms=elapsed_ms
                )
            except sqlite3.Error as e:
                raise ValueError(f"SQLite execution error: {str(e)}") from e


# Singleton database manager instance
db_manager = DatabaseManager()
