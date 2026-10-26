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


def validate_modifying_sql(sql: str, expected_type: str) -> None:
    """
    Validate that a modifying SQL statement (INSERT, UPDATE, DELETE, DROP)
    is syntactically valid, targets the correct table, and references valid columns.
    Raises ValueError if invalid or prohibited.
    """
    if not sql or not sql.strip():
        raise ValueError("SQL string cannot be empty")

    try:
        parsed = sqlglot.parse(sql, read="sqlite")
    except Exception as e:
        raise ValueError(f"SQL syntax error: {str(e)}") from e

    if len(parsed) == 0:
        raise ValueError("SQL string contains no valid statements")

    if len(parsed) > 1:
        raise ValueError("Only a single SQL statement is allowed. Multi-statement queries are prohibited.")

    stmt = parsed[0]
    stmt_type = type(stmt).__name__.upper()

    expected_map = {
        "INSERT": exp.Insert,
        "UPDATE": exp.Update,
        "DELETE": exp.Delete,
        "DROP": exp.Drop,
        "ALTER": exp.Alter,
        "ALTER_TABLE": exp.Alter
    }

    expected_exp = expected_map.get(expected_type.upper())
    if not expected_exp or not isinstance(stmt, expected_exp):
        raise ValueError(f"Expected statement type {expected_type}, but found {stmt_type}")

    schema = db_manager.get_schema()
    base_table = schema.table_name.lower()
    valid_columns = {col.name.lower() for col in schema.columns}

    # Verify target table for INSERT, UPDATE, DELETE, DROP, ALTER
    table_node = stmt.find(exp.Table)
    if table_node and table_node.name:
        tbl_name = table_node.name.lower()
        if tbl_name and tbl_name != base_table:
            raise ValueError(f"Target table '{table_node.name}' does not match active dataset table '{schema.table_name}'")

    # For ALTER TABLE: verify it is dropping a column and that the column is droppable
    if isinstance(stmt, exp.Alter):
        drop_node = stmt.find(exp.Drop)
        if not drop_node:
            raise ValueError("Only ALTER TABLE ... DROP COLUMN statements are supported for schema modification.")
        cols = [c.name for c in stmt.find_all(exp.Column)]
        if not cols:
            raise ValueError("Could not identify the target column in the ALTER TABLE statement.")
        target_col = cols[0]
        db_manager.check_column_droppable(target_col)
        return

    # Verify column references against schema
    for column in stmt.find_all(exp.Column):
        col_name = column.name
        if not col_name or col_name == "*":
            continue
        if col_name.lower() not in valid_columns:
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
        self._cached_schema: Optional[SchemaResponse] = None
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
            self._cached_schema = None

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

            # In-place rename columns temporarily to avoid full DataFrame copy
            orig_columns = list(df.columns)
            try:
                df.columns = [mapping[str(c)] for c in orig_columns]
                # Enforce safe bound parameter limit (max 999 parameters per insert statement for SQLite compatibility)
                max_params = 999
                num_cols = max(1, len(df.columns))
                safe_chunksize = max(1, min(1000, max_params // num_cols))
                df.to_sql(self.table_name, conn, index=False, if_exists="replace", chunksize=safe_chunksize, method="multi")
            finally:
                df.columns = orig_columns

            self._conn = conn
            self._file_name = filename
            self._total_rows = len(df)
            self._col_mapping = mapping
            self._cached_schema = None

            schema = self._get_schema_internal()
            self._cached_schema = schema
            return schema

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
            if self._cached_schema is not None:
                return self._cached_schema
            schema = self._get_schema_internal()
            self._cached_schema = schema
            return schema

    def check_column_droppable(self, column_name: str) -> None:
        """
        Verify SQLite version support and schema dependencies for dropping a column.
        Raises ValueError with an honest explanation if unsupported or invalid.
        """
        # 1. SQLite version support check (ALTER TABLE DROP COLUMN requires 3.35.0+)
        if sqlite3.sqlite_version_info < (3, 35, 0):
            raise ValueError(
                f"SQLite version {sqlite3.sqlite_version} does not support dropping columns. "
                f"'ALTER TABLE ... DROP COLUMN' requires SQLite 3.35.0 or higher."
            )

        schema = self.get_schema()
        valid_cols = {c.name.lower(): c for c in schema.columns}
        col_lower = column_name.lower()

        # 2. Column existence check
        if col_lower not in valid_cols:
            raise ValueError(
                f"No such column: '{column_name}'. It does not exist in active dataset schema. "
                f"Available columns: {', '.join(sorted([c.name for c in schema.columns]))}"
            )

        # 3. Table column count check (SQLite cannot drop the only column)
        if len(schema.columns) <= 1:
            raise ValueError(
                f"Cannot drop column '{column_name}'. SQLite does not allow dropping the only column in a table."
            )

        # 4. Check PRAGMA table_info for primary key constraints
        with self._lock:
            if self._conn is not None:
                cur = self._conn.cursor()
                cur.execute(f"PRAGMA table_info({self.table_name});")
                for col_info in cur.fetchall():
                    # col_info: (cid, name, type, notnull, dflt_value, pk)
                    if col_info[1].lower() == col_lower and col_info[5] > 0:
                        raise ValueError(
                            f"Cannot drop column '{column_name}' because it is part of the table's PRIMARY KEY."
                        )

                # 5. Check if column is part of any index
                cur.execute(f"PRAGMA index_list({self.table_name});")
                for idx in cur.fetchall():
                    idx_name = idx[1]
                    cur.execute(f"PRAGMA index_info('{idx_name}');")
                    for idx_col in cur.fetchall():
                        if idx_col[2] and idx_col[2].lower() == col_lower:
                            raise ValueError(
                                f"Cannot drop column '{column_name}' because it is indexed by '{idx_name}'."
                            )

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

    def execute_safe_preview(self, sql: str, statement_type: str) -> Dict[str, Any]:
        """
        Safely generate a non-destructive preview for a modifying statement (INSERT, UPDATE, DELETE, DROP)
        by inspecting the SQL AST and executing safe read-only queries against the dataset.
        NEVER modifies the underlying dataset.
        """
        validate_modifying_sql(sql, statement_type)
        schema = self.get_schema()
        table_name = schema.table_name

        parsed = sqlglot.parse(sql, read="sqlite")
        stmt = parsed[0]

        preview: Dict[str, Any] = {
            "statement_type": statement_type.upper(),
            "preview_type": "UNKNOWN",
            "where_clause_present": None,
            "affected_rows_count": None,
            "proposed_data": None,
            "before_after": None,
            "warning": None,
            "is_destructive": statement_type.upper() in ("DELETE", "DROP", "UPDATE", "ALTER", "ALTER_TABLE")
        }

        if statement_type.upper() in ("ALTER", "ALTER_TABLE"):
            preview["preview_type"] = "COLUMN_DROP_PREVIEW"
            cols = [c.name for c in stmt.find_all(exp.Column)]
            target_col = cols[0] if cols else ""

            self.check_column_droppable(target_col)

            schema_col = next((c for c in schema.columns if c.name.lower() == target_col.lower()), None)
            target_col_actual = schema_col.name if schema_col else target_col

            remaining_cols = [c.name for c in schema.columns if c.name.lower() != target_col.lower()]
            preview["target_column"] = target_col_actual
            preview["remaining_columns"] = remaining_cols
            preview["dropped_columns"] = [target_col_actual]
            preview["affected_rows_count"] = schema.total_rows

            if remaining_cols:
                preview_cols_sql = ", ".join([f'"{c}"' for c in remaining_cols])
                preview_select_sql = f'SELECT {preview_cols_sql} FROM "{table_name}" LIMIT 50'
                select_res = self.execute_query(preview_select_sql, row_limit=50)
                preview["proposed_data"] = select_res.rows
            else:
                preview["proposed_data"] = []

            preview["warning"] = (
                f"Preview only — not executed. Column '{target_col_actual}' would be removed from dataset schema "
                f"({len(schema.columns)} -> {len(remaining_cols)} columns). {schema.total_rows} rows affected."
            )
            return preview

        if statement_type.upper() == "DROP":
            preview["preview_type"] = "DROP_WARNING"
            preview["warning"] = f"DESTRUCTIVE WARNING: Executing DROP TABLE would permanently remove table '{table_name}' and all {schema.total_rows} rows. This preview is read-only and has not been executed."
            preview["affected_rows_count"] = schema.total_rows
            return preview

        if statement_type.upper() == "INSERT":
            preview["preview_type"] = "INSERT_PROPOSED"
            preview["is_destructive"] = False
            # Extract inserted values / columns if possible
            proposed_row = {}
            try:
                # Attempt to extract expressions from INSERT
                if isinstance(stmt, exp.Insert):
                    cols = [c.name for c in stmt.find_all(exp.Column)]
                    # If columns and expressions can be mapped
                    expressions = list(stmt.find_all(exp.Literal))
                    if cols and expressions and len(cols) >= len(expressions):
                        for c, lit in zip(cols, expressions):
                            proposed_row[c] = lit.this
            except Exception:
                pass
            preview["proposed_data"] = [proposed_row] if proposed_row else [{"note": "New row values as parsed from insert statement"}]
            preview["warning"] = "Preview only — not executed. No rows were added to the dataset."
            return preview

        # For UPDATE and DELETE, check for WHERE clause
        where_clause = stmt.find(exp.Where)
        has_where = where_clause is not None
        preview["where_clause_present"] = has_where

        if not has_where:
            if statement_type.upper() == "DELETE":
                preview["warning"] = "CRITICAL WARNING: No WHERE clause detected. This DELETE statement would remove EVERY row in the dataset!"
            elif statement_type.upper() == "UPDATE":
                preview["warning"] = "CRITICAL WARNING: No WHERE clause detected. This UPDATE statement would modify EVERY row in the dataset!"

        # Use sqlglot AST directly to derive read-only preview SELECT statement
        # Preserves predicate semantics, identifiers, table aliases, and qualifications without brittle string splitting
        table_node = stmt.find(exp.Table)
        target_table = table_node.copy() if table_node else exp.to_table(table_name)
        select_stmt = exp.Select().select("*").from_(target_table)
        if where_clause and where_clause.this:
            select_stmt = select_stmt.where(where_clause.this.copy())
        select_stmt = select_stmt.limit(50)
        preview_select_sql = select_stmt.sql(dialect="sqlite")

        try:
            select_res = self.execute_query(preview_select_sql, row_limit=50)
            target_rows = select_res.rows
            preview["affected_rows_count"] = select_res.row_count

            if statement_type.upper() == "DELETE":
                preview["preview_type"] = "DELETE_TARGETS"
                preview["proposed_data"] = target_rows
                if not preview["warning"]:
                    preview["warning"] = f"Preview only — not executed. {select_res.row_count} matching rows targeted for deletion."

            elif statement_type.upper() == "UPDATE":
                preview["preview_type"] = "UPDATE_IMPACT"
                # Simulate before/after diff for up to 50 rows in memory
                before_after_list = []

                # Try to extract full SET expressions for accurate preview (handles CASE, functions, etc.)
                set_expressions = []
                try:
                    if isinstance(stmt, exp.Update):
                        for eq in stmt.expressions:
                            if isinstance(eq, exp.EQ):
                                col_name = eq.this.name if hasattr(eq.this, 'name') else str(eq.this)
                                expr_sql = eq.expression.sql(dialect='sqlite')
                                set_expressions.append((col_name, expr_sql))
                except Exception:
                    pass

                if set_expressions:
                    # Build a read-only SELECT that computes the after-values using the same expressions
                    computed_cols = [f"({expr_sql}) AS __preview_{col}" for col, expr_sql in set_expressions]
                    calc_select = exp.Select().select("*", *[exp.var(c) for c in computed_cols]).from_(target_table)
                    if where_clause and where_clause.this:
                        calc_select = calc_select.where(where_clause.this.copy())
                    calc_sql = calc_select.limit(50).sql(dialect="sqlite")
                    try:
                        calc_res = self.execute_query(calc_sql, row_limit=50)
                        for row in calc_res.rows:
                            before_row = {k: v for k, v in row.items() if not k.startswith('__preview_')}
                            after_row = dict(before_row)
                            for col, _ in set_expressions:
                                after_row[col] = row[f'__preview_{col}']
                            before_after_list.append({"before": before_row, "after": after_row})
                    except Exception:
                        # Fall back to simple literal extraction if complex expression fails
                        set_assignments = []
                        try:
                            for eq in stmt.find_all(exp.EQ):
                                if isinstance(eq.parent, exp.Set):
                                    col_name = eq.left.name
                                    val = eq.right.name or eq.right.this
                                    set_assignments.append((col_name, val))
                        except Exception:
                            pass
                        for row in target_rows:
                            before_row = dict(row)
                            after_row = dict(row)
                            for col_name, val in set_assignments:
                                if col_name in after_row:
                                    after_row[col_name] = f"{val} (applied)"
                            before_after_list.append({"before": before_row, "after": after_row})
                else:
                    # Fallback: simple literal extraction
                    set_assignments = []
                    try:
                        for eq in stmt.find_all(exp.EQ):
                            if isinstance(eq.parent, exp.Set):
                                col_name = eq.left.name
                                val = eq.right.name or eq.right.this
                                set_assignments.append((col_name, val))
                    except Exception:
                        pass
                    for row in target_rows:
                        before_row = dict(row)
                        after_row = dict(row)
                        for col_name, val in set_assignments:
                            if col_name in after_row:
                                after_row[col_name] = f"{val} (applied)"
                        before_after_list.append({"before": before_row, "after": after_row})

                preview["before_after"] = before_after_list
                preview["proposed_data"] = target_rows
                if not preview["warning"]:
                    preview["warning"] = f"Preview only — not executed. {select_res.row_count} rows match update criteria."

        except Exception as e:
            raise ValueError(f"Could not compute preview for {statement_type.upper()} statement: {str(e)}") from e

        return preview


# Singleton database manager instance
db_manager = DatabaseManager()
