import os
import re
import json
from typing import TypedDict, List, Dict, Any, Optional
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from .db import db_manager, validate_sql, validate_sql_against_schema, validate_modifying_sql
from .schemas import AskResponse

# Load environment variables from .env if present
load_dotenv()


class SQLWorkflowState(TypedDict):
    question: str
    schema_context: str
    intent: str
    statement_type: str
    generated_sql: str
    validation_error: Optional[str]
    execution_error: Optional[str]
    final_error: Optional[str]
    classification_error: Optional[str]
    query_result: Optional[Dict[str, Any]]
    preview_data: Optional[Dict[str, Any]]
    correction_attempted: bool
    row_limit: int
    # Answerability fields
    is_answerable: Optional[bool]
    unanswerable_reason: Optional[str]
    # AI Insight
    insight: Optional[str]


def extract_text_from_response(response: Any) -> str:
    """Safely extract plain text from LangChain response, handling strings, lists, and dicts."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            elif hasattr(item, "text"):
                parts.append(str(item.text))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def extract_json_from_response(raw_text: str) -> Dict[str, Any]:
    """
    Robustly extract a JSON object from LLM output.
    Handles raw JSON, markdown code fences (```json ... ```), and surrounding text.
    Raises ValueError if no valid JSON object is found or parsing fails.
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("Empty response from LLM")

    cleaned = raw_text.strip()

    # Remove markdown code fences if present
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()

    # Find the first JSON object (between first { and matching })
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        json_str = cleaned[start:end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON from LLM response: {e}")

    raise ValueError("No JSON object found in LLM response")


def clean_sql(raw: str) -> str:
    """Strip markdown code formatting and clean up generated SQL."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    cleaned = cleaned.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    return cleaned


def get_gemini_llm(custom_llm: Optional[Any] = None) -> Any:
    """
    Get configured LLM (Gemini or OpenAI compatible/Groq) or custom test LLM.
    Supports GOOGLE_API_KEY/GEMINI_API_KEY / GROQ_API_KEY.
    """
    if custom_llm is not None:
        return custom_llm

    provider = (os.environ.get("LLM_PROVIDER") or "gemini").lower()


    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY environment variable is not configured on the backend. "
            "Please set your API key to enable natural-language questions."
        )

    model_name = os.environ.get("GOOGLE_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
    cache_key = (api_key, model_name)
    if cache_key not in _default_llm_cache:
        _default_llm_cache[cache_key] = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            max_retries=2,       # Bounded retries to prevent runaway exponential backoff loops (~63s)
            timeout=25.0         # Explicit timeout to fail fast on stalled network connections
        )
    return _default_llm_cache[cache_key]


_default_llm_cache: Dict[tuple, Any] = {}
_workflow_cache: Dict[int, Any] = {}


def get_compiled_workflow(llm: Any) -> Any:
    """
    Get or compile a reusable LangGraph workflow for the given LLM instance.
    Contains no request-specific state, datasets, or schema context.
    """
    llm_id = id(llm)
    if llm_id not in _workflow_cache:
        if len(_workflow_cache) > 32:
            _workflow_cache.clear()
        _workflow_cache[llm_id] = create_sql_workflow(llm)
    return _workflow_cache[llm_id]


def build_schema_context() -> str:
    """Format active SQLite table schema and real column names for the LLM prompt."""
    schema = db_manager.get_schema()
    cols_desc = [f"  - {col.name} ({col.data_type})" for col in schema.columns]
    cols_str = "\n".join(cols_desc)
    return (
        f"Table name: {schema.table_name}\n"
        f"Available columns:\n{cols_str}\n"
        f"Total rows in dataset: {schema.total_rows}"
    )


def create_sql_workflow(llm: Any):
    """
    Construct the LangGraph StateGraph for Text-to-SQL with Intent Classification and Safe Modifying Previews:
    1. Classify intent (DATA_ANALYSIS, SQL_GENERATION, or UNSUPPORTED) and statement type (SELECT, INSERT, UPDATE, DELETE, DROP).
    2. For DATA_ANALYSIS (SELECT), check answerability.
    3. Generate SQL tailored to the statement type.
    4. Validate SQL (read-only SELECT vs modifying statement validation against schema).
    5. For SELECT: execute safely via read-only execution path and generate grounded AI insight.
    6. For INSERT, UPDATE, DELETE, DROP: generate non-destructive preview impact safely without modifying database.
    """

    def classify_and_verify_node(state: SQLWorkflowState) -> Dict[str, Any]:
        """
        Classify user request intent into DATA_ANALYSIS, SQL_GENERATION, or UNSUPPORTED,
        statement_type into SELECT, INSERT, UPDATE, DELETE, DROP, or ALTER_TABLE,
        and verify schema answerability in a single structured LLM call.
        Eliminates sequential LLM round-trips while preserving rigorous answerability verification.
        """
        prompt = (
            f"You are an intent classifier and schema analyst for a CSV data assistant.\n"
            f"Dataset schema:\n{state['schema_context']}\n\n"
            f"User request: {state['question']}\n\n"
            f"Classify the request and verify answerability into ONLY a JSON object with this exact structure:\n"
            f'{{"intent": "DATA_ANALYSIS" | "SQL_GENERATION" | "UNSUPPORTED", '
            f'"statement_type": "SELECT" | "INSERT" | "UPDATE" | "DELETE" | "DROP" | "ALTER_TABLE", '
            f'"is_answerable": true | false, '
            f'"unanswerable_reason": "explanation if not answerable or null"}}\n\n'
            f"Guidelines:\n"
            f"1. DATA_ANALYSIS: The user wants to query, filter, aggregate, inspect, or analyze existing data without modifying it (always statement_type SELECT).\n"
            f"   - If the question references concepts, columns, or entities not present in the schema, set is_answerable=false and explain in unanswerable_reason.\n"
            f"   - Do NOT assume synonyms map to different columns.\n"
            f"   - Only set is_answerable=true if the question can be fully answered with the available columns.\n"
            f"2. SQL_GENERATION: The user wants to modify data or schema, or explicitly asks for SQL statements:\n"
            f"   - Row deletion ('delete/remove rows where ...', 'remove records where ...') -> statement_type DELETE.\n"
            f"   - Column deletion ('delete/remove/drop column ...', 'delete the column ...') -> statement_type ALTER_TABLE.\n"
            f"   - Whole-table deletion ('drop table ...', 'delete the entire table ...') -> statement_type DROP.\n"
            f"   - Adding, renaming, or modifying column schema -> statement_type ALTER_TABLE.\n"
            f"   - Data insertion or row addition -> statement_type INSERT.\n"
            f"   - Data updating, value modification, or swapping -> statement_type UPDATE.\n"
            f"   - For SQL_GENERATION, set is_answerable=true.\n"
            f"3. UNSUPPORTED: The request is unrelated to the dataset or database operations.\n"
            f"4. Return ONLY the JSON object. Do not include extra commentary or markdown explanations."
        )

        ALLOWED_INTENTS = {"DATA_ANALYSIS", "SQL_GENERATION", "UNSUPPORTED"}
        ALLOWED_STATEMENT_TYPES = {"SELECT", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "ALTER_TABLE"}

        last_error = None
        for attempt in range(2):
            try:
                msg = prompt if attempt == 0 else f"{prompt}\n\nPrevious attempt failed ({last_error}). Output strictly valid JSON."
                response = llm.invoke([HumanMessage(content=msg)])
                raw_text = extract_text_from_response(response)
                result = extract_json_from_response(raw_text)

                intent = result.get("intent")
                statement_type = str(result.get("statement_type", "")).upper()
                if statement_type == "ALTER":
                    statement_type = "ALTER_TABLE"

                if intent not in ALLOWED_INTENTS:
                    raise ValueError(f"Invalid intent '{intent}'. Allowed: {ALLOWED_INTENTS}")
                if statement_type not in ALLOWED_STATEMENT_TYPES:
                    raise ValueError(f"Invalid statement_type '{statement_type}'. Allowed: {ALLOWED_STATEMENT_TYPES}")

                # Answerability extraction (support both is_answerable and answerable keys for flexibility)
                if "is_answerable" in result:
                    is_answerable = bool(result["is_answerable"])
                elif "answerable" in result:
                    is_answerable = bool(result["answerable"])
                else:
                    is_answerable = True

                unanswerable_reason = result.get("unanswerable_reason") or result.get("reason")

                if not is_answerable and intent == "DATA_ANALYSIS":
                    return {
                        "intent": intent,
                        "statement_type": statement_type,
                        "is_answerable": False,
                        "unanswerable_reason": unanswerable_reason or "This question cannot be answered using the available columns.",
                        "classification_error": None,
                        "generated_sql": "",
                        "validation_error": None,
                        "execution_error": None,
                        "final_error": None,
                        "query_result": None,
                        "correction_attempted": False
                    }

                return {
                    "intent": intent,
                    "statement_type": statement_type,
                    "is_answerable": is_answerable,
                    "unanswerable_reason": unanswerable_reason if not is_answerable else None,
                    "classification_error": None
                }
            except Exception as e:
                last_error = str(e)

        # Never silently default to DATA_ANALYSIS on failure!
        return {
            "intent": "UNSUPPORTED",
            "statement_type": "UNKNOWN",
            "is_answerable": False,
            "classification_error": (
                f"Unable to determine request intent: {last_error}. "
                "Please clarify whether you want to query data or generate SQL (e.g., SELECT, UPDATE, INSERT, DELETE, ALTER TABLE)."
            )
        }

    def generate_sql_node(state: SQLWorkflowState) -> Dict[str, Any]:
        stmt_type = state.get("statement_type", "SELECT").upper()
        table_name = db_manager.table_name

        if stmt_type == "SELECT":
            prompt = (
                f"You are a helpful SQL assistant. Write a single SQLite read-only query to answer the user's question.\n"
                f"Rules:\n"
                f"1. Use ONLY the table '{table_name}' and the columns listed in the schema.\n"
                f"2. Ensure queries retrieve complete information, including relevant numerical metrics alongside group labels when appropriate.\n"
                f"3. Return ONLY the SQL query. Do not include markdown explanations or text outside the query.\n"
                f"4. Do not modify the database (only SELECT queries are allowed).\n\n"
                f"Schema:\n{state['schema_context']}\n\n"
                f"User question: {state['question']}"
            )
        elif stmt_type == "INSERT":
            prompt = (
                f"You are a helpful SQL assistant. Write a single SQLite INSERT statement based on the user's request.\n"
                f"Rules:\n"
                f"1. Target table must be '{table_name}'. Use ONLY columns from the schema.\n"
                f"2. Return ONLY the SQL statement. No markdown explanations.\n\n"
                f"Schema:\n{state['schema_context']}\n\n"
                f"User request: {state['question']}"
            )
        elif stmt_type == "UPDATE":
            prompt = (
                f"You are a helpful SQL assistant. Write a single SQLite UPDATE statement based on the user's request.\n"
                f"Rules:\n"
                f"1. Target table must be '{table_name}'. Use ONLY columns from the schema.\n"
                f"2. Include a precise WHERE clause unless the user explicitly requested updating all rows.\n"
                f"3. For swapping two values (e.g. east and west), use a single CASE expression to swap them simultaneously while preserving all other values (e.g. CASE WHEN LOWER(region) = 'east' THEN 'West' WHEN LOWER(region) = 'west' THEN 'East' ELSE region END).\n"
                f"4. For string matching in WHERE and CASE conditions, use case-insensitive matching like LOWER(col) = 'val' or col COLLATE NOCASE = 'val' where appropriate so user input matches dataset casing.\n"
                f"5. Return ONLY the SQL statement. No markdown explanations.\n\n"
                f"Schema:\n{state['schema_context']}\n\n"
                f"User request: {state['question']}"
            )
        elif stmt_type == "DELETE":
            prompt = (
                f"You are a helpful SQL assistant. Write a single SQLite DELETE statement based on the user's request.\n"
                f"Rules:\n"
                f"1. Target table must be '{table_name}'.\n"
                f"2. Include a clear WHERE clause unless the user explicitly asked to delete all rows.\n"
                f"3. For string matching in WHERE conditions, use case-insensitive matching like LOWER(col) = 'val' or col COLLATE NOCASE = 'val' where appropriate so user input matches dataset casing.\n"
                f"4. Return ONLY the SQL statement. No markdown explanations.\n\n"
                f"Schema:\n{state['schema_context']}\n\n"
                f"User request: {state['question']}"
            )
        elif stmt_type == "DROP":
            prompt = (
                f"Write a single SQLite DROP TABLE statement for the table '{table_name}'.\n"
                f"Return ONLY the SQL statement. No markdown explanations."
            )
        elif stmt_type in ("ALTER_TABLE", "ALTER"):
            prompt = (
                f"You are a helpful SQL assistant. Write a single SQLite ALTER TABLE statement based on the user's request.\n"
                f"Rules:\n"
                f"1. Target table must be '{table_name}'.\n"
                f"2. For column deletion, write: ALTER TABLE {table_name} DROP COLUMN <column_name>;\n"
                f"3. Use the exact column name from the schema.\n"
                f"4. Do NOT drop the entire table. Only drop the specified column.\n"
                f"5. Return ONLY the SQL statement. No markdown explanations.\n\n"
                f"Schema:\n{state['schema_context']}\n\n"
                f"User request: {state['question']}"
            )
        else:
            prompt = f"SELECT * FROM {table_name} LIMIT 10"

        response = llm.invoke([SystemMessage(content=f"You generate valid SQLite SQL statements."), HumanMessage(content=prompt)])
        raw_text = extract_text_from_response(response)
        sql = clean_sql(raw_text)
        return {"generated_sql": sql}

    def validate_sql_node(state: SQLWorkflowState) -> Dict[str, Any]:
        stmt_type = state.get("statement_type", "SELECT").upper()
        try:
            if stmt_type == "SELECT":
                validate_sql(state["generated_sql"])
            else:
                validate_modifying_sql(state["generated_sql"], stmt_type)
            return {"validation_error": None}
        except ValueError as e:
            return {"validation_error": str(e)}

    def execute_sql_node(state: SQLWorkflowState) -> Dict[str, Any]:
        """
        Execute ONLY read-only SELECT queries. Modifying queries must NEVER reach this node.
        """
        if state.get("statement_type", "SELECT").upper() != "SELECT":
            raise RuntimeError("Modifying SQL statements cannot be sent to execute_sql_node.")

        try:
            res = db_manager.execute_query(state["generated_sql"], row_limit=state["row_limit"])
            return {
                "query_result": {
                    "columns": res.columns,
                    "rows": res.rows,
                    "row_count": res.row_count,
                    "execution_time_ms": res.execution_time_ms
                },
                "execution_error": None,
                "final_error": None
            }
        except ValueError as e:
            return {"execution_error": str(e), "query_result": None}

    def generate_preview_node(state: SQLWorkflowState) -> Dict[str, Any]:
        """
        Generate a safe non-destructive preview for modifying SQL statements (INSERT, UPDATE, DELETE, DROP).
        Never modifies the dataset.
        """
        stmt_type = state.get("statement_type", "SELECT").upper()
        try:
            preview = db_manager.execute_safe_preview(state["generated_sql"], stmt_type)
            return {
                "preview_data": preview,
                "execution_error": None,
                "final_error": None
            }
        except Exception as e:
            return {"execution_error": str(e), "final_error": str(e), "preview_data": None}

    def generate_insight_node(state: SQLWorkflowState) -> Dict[str, Any]:
        query_result = state.get("query_result")
        preview_data = state.get("preview_data")

        # 1. SELECT query insights
        if query_result:
            rows = query_result.get("rows", [])
            if not rows:
                return {"insight": "No matching records were found in the dataset for this query."}

            columns = query_result.get("columns", [])
            cols_str = ", ".join(columns)
            sample_rows = rows[:10]
            rows_preview = "\n".join([str(row) for row in sample_rows])
            total_rows = query_result.get("row_count", len(rows))

            prompt = (
                f"You are a data analyst. Generate a concise natural-language explanation (1 to 3 sentences) "
                f"answering the user's question based strictly on the SQL query results below.\n\n"
                f"User question: {state['question']}\n\n"
                f"Executed SQL: {state['generated_sql']}\n\n"
                f"Result columns: {cols_str}\n\n"
                f"Result rows (showing {len(sample_rows)} of {total_rows}):\n{rows_preview}\n\n"
                f"Guidelines:\n"
                f"1. Directly answer the question in 1 to 3 clear, natural sentences.\n"
                f"2. Mention relevant numerical values and specific categories/names from the result rows.\n"
                f"3. Strictly use ONLY facts directly present in the result rows. Never invent numbers, guess, or extrapolate."
            )

            try:
                insight_llm = llm
                if hasattr(llm, "bind"):
                    try:
                        insight_llm = llm.bind(max_output_tokens=150)
                    except Exception:
                        insight_llm = llm
                response = insight_llm.invoke([
                    SystemMessage(content="You are a data analyst who provides concise, accurate insights based strictly on query results."),
                    HumanMessage(content=prompt)
                ])
                raw_text = extract_text_from_response(response)
                return {"insight": raw_text.strip()}
            except Exception:
                return {"insight": "Explanation is temporarily unavailable."}

        # 2. Modifying statement preview insights (INSERT, UPDATE, DELETE, DROP, ALTER_TABLE)
        if preview_data:
            stmt_type = state.get("statement_type", "UNKNOWN").upper()
            preview_type = preview_data.get("preview_type", "UNKNOWN")
            affected_rows = preview_data.get("affected_rows_count")
            warning = preview_data.get("warning") or ""
            target_col = preview_data.get("target_column")
            remaining_cols = preview_data.get("remaining_columns")
            proposed_data = preview_data.get("proposed_data") or preview_data.get("before_after") or []

            sample_preview = proposed_data[:5] if isinstance(proposed_data, list) else []
            preview_str = json.dumps(sample_preview, default=str) if sample_preview else "None"

            prompt = (
                f"You are a data analyst. Generate a concise natural-language explanation (1 to 3 sentences) "
                f"describing the proposed impact of this {stmt_type} statement based strictly on the verified preview data below.\n\n"
                f"User request: {state['question']}\n\n"
                f"Proposed SQL: {state['generated_sql']}\n\n"
                f"Statement type: {stmt_type}\n\n"
                f"Preview type: {preview_type}\n\n"
                f"Target column (if applicable): {target_col}\n\n"
                f"Remaining columns (if applicable): {remaining_cols}\n\n"
                f"Verified affected rows count: {affected_rows}\n\n"
                f"Safety warning / impact note: {warning}\n\n"
                f"Preview rows sample: {preview_str}\n\n"
                f"Guidelines:\n"
                f"1. Clearly explain what changes WOULD occur if this statement were executed, mentioning verified affected row counts or column changes.\n"
                f"2. Explicitly note that this is a non-destructive preview and no changes have been executed against the dataset.\n"
                f"3. Strictly use ONLY verified preview numbers and facts directly present above. Never invent or guess values.\n"
                f"4. Keep it concise (1 to 3 clear, natural sentences)."
            )

            try:
                insight_llm = llm
                if hasattr(llm, "bind"):
                    try:
                        insight_llm = llm.bind(max_output_tokens=150)
                    except Exception:
                        insight_llm = llm
                response = insight_llm.invoke([
                    SystemMessage(content="You are a data analyst who provides clear, accurate explanations of SQL preview impact without claiming execution."),
                    HumanMessage(content=prompt)
                ])
                raw_text = extract_text_from_response(response)
                return {"insight": raw_text.strip()}
            except Exception:
                return {"insight": "Preview explanation is temporarily unavailable."}

        return {"insight": None}

    def correct_sql_node(state: SQLWorkflowState) -> Dict[str, Any]:
        err_msg = state.get("validation_error") or state.get("execution_error") or "Unknown error"
        prompt = (
            f"The previous SQL query produced an error. Please fix the SQL query to answer the request.\n\n"
            f"Schema:\n{state['schema_context']}\n\n"
            f"User request: {state['question']}\n\n"
            f"Failed SQL: {state['generated_sql']}\n\n"
            f"Error message: {err_msg}\n\n"
            f"Return ONLY the corrected SQLite SQL statement."
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        raw_text = extract_text_from_response(response)
        sql = clean_sql(raw_text)
        return {
            "generated_sql": sql,
            "correction_attempted": True,
            "validation_error": None,
            "execution_error": None
        }

    # Conditional routing
    def route_after_validation(state: SQLWorkflowState) -> str:
        if state.get("validation_error"):
            if not state.get("correction_attempted", False):
                return "correct_sql_node"
            return "set_validation_error_end"

        stmt_type = state.get("statement_type", "SELECT").upper()
        if stmt_type == "SELECT":
            return "execute_sql_node"
        else:
            return "generate_preview_node"

    def route_after_execution(state: SQLWorkflowState) -> str:
        if state.get("execution_error"):
            if not state.get("correction_attempted", False):
                return "correct_sql_node"
            return "set_execution_error_end"
        return "generate_insight_node"

    def set_validation_error_end(state: SQLWorkflowState) -> Dict[str, Any]:
        return {"final_error": state.get("validation_error")}

    def set_execution_error_end(state: SQLWorkflowState) -> Dict[str, Any]:
        return {"final_error": state.get("execution_error")}

    def set_unanswerable_end(state: SQLWorkflowState) -> Dict[str, Any]:
        return {"final_error": state.get("unanswerable_reason")}

    def set_unsupported_end(_state: SQLWorkflowState) -> Dict[str, Any]:
        return {"final_error": "This request is outside the scope of CSV dataset analysis and SQL generation."}

    builder = StateGraph(SQLWorkflowState)

    builder.add_node("classify_and_verify_node", classify_and_verify_node)
    builder.add_node("generate_sql_node", generate_sql_node)
    builder.add_node("validate_sql_node", validate_sql_node)
    builder.add_node("execute_sql_node", execute_sql_node)
    builder.add_node("generate_preview_node", generate_preview_node)
    builder.add_node("correct_sql_node", correct_sql_node)
    builder.add_node("generate_insight_node", generate_insight_node)
    builder.add_node("set_validation_error_end", set_validation_error_end)
    builder.add_node("set_execution_error_end", set_execution_error_end)
    builder.add_node("set_unanswerable_end", set_unanswerable_end)
    builder.add_node("set_unsupported_end", set_unsupported_end)

    builder.add_edge(START, "classify_and_verify_node")

    def route_after_classify(state: SQLWorkflowState) -> str:
        intent = state.get("intent", "DATA_ANALYSIS")
        if intent == "UNSUPPORTED":
            return "set_unsupported_end"
        elif intent == "SQL_GENERATION":
            return "generate_sql_node"
        else:  # DATA_ANALYSIS
            if state.get("is_answerable") is False:
                return "set_unanswerable_end"
            return "generate_sql_node"

    builder.add_conditional_edges(
        "classify_and_verify_node",
        route_after_classify,
        {
            "generate_sql_node": "generate_sql_node",
            "set_unanswerable_end": "set_unanswerable_end",
            "set_unsupported_end": "set_unsupported_end"
        }
    )

    builder.add_edge("generate_sql_node", "validate_sql_node")

    builder.add_conditional_edges(
        "validate_sql_node",
        route_after_validation,
        {
            "correct_sql_node": "correct_sql_node",
            "execute_sql_node": "execute_sql_node",
            "generate_preview_node": "generate_preview_node",
            "set_validation_error_end": "set_validation_error_end"
        }
    )

    builder.add_conditional_edges(
        "execute_sql_node",
        route_after_execution,
        {
            "correct_sql_node": "correct_sql_node",
            "set_execution_error_end": "set_execution_error_end",
            "generate_insight_node": "generate_insight_node"
        }
    )

    builder.add_edge("generate_insight_node", END)
    builder.add_edge("generate_preview_node", "generate_insight_node")

    builder.add_edge("correct_sql_node", "validate_sql_node")
    builder.add_edge("set_validation_error_end", END)
    builder.add_edge("set_execution_error_end", END)
    builder.add_edge("set_unanswerable_end", END)
    builder.add_edge("set_unsupported_end", END)

    return builder.compile()


def run_text_to_sql_workflow(
    question: str,
    row_limit: int = 100,
    custom_llm: Optional[Any] = None
) -> AskResponse:
    """Execute the text-to-SQL workflow and return AskResponse."""
    import time
    from langchain_core.callbacks import BaseCallbackHandler

    t_start = time.perf_counter()
    call_count = 0

    class CallCounterHandler(BaseCallbackHandler):
        def __init__(self, counter):
            self.counter = counter
        def on_llm_start(self, serialized, prompts, **kwargs):
            self.counter[0] += 1

    schema_context = build_schema_context()

    llm = get_gemini_llm(custom_llm)
    # Add callback to count LLM calls
    call_counter = [0]
    handler = CallCounterHandler(call_counter)
    try:
        if hasattr(llm, "callbacks") and llm.callbacks is not None:
            llm.callbacks.append(handler)
        else:
            setattr(llm, "callbacks", [handler])
    except Exception:
        pass

    graph = get_compiled_workflow(llm)

    initial_state: SQLWorkflowState = {
        "question": question,
        "schema_context": schema_context,
        "intent": "DATA_ANALYSIS",
        "statement_type": "SELECT",
        "generated_sql": "",
        "validation_error": None,
        "execution_error": None,
        "final_error": None,
        "query_result": None,
        "preview_data": None,
        "correction_attempted": False,
        "row_limit": row_limit,
        "is_answerable": None,
        "unanswerable_reason": None,
        "insight": None
    }

    final_state = graph.invoke(initial_state, config={"callbacks": [handler]})
    call_count = call_counter[0]

    intent = final_state.get("intent", "DATA_ANALYSIS")
    statement_type = final_state.get("statement_type", "SELECT")

    if final_state.get("final_error") or final_state.get("execution_error"):
        error = final_state.get("final_error") or final_state.get("execution_error") or "Query failed"
        if final_state.get("unanswerable_reason") or (not final_state.get("generated_sql") and final_state.get("final_error")):
            msg = f"I can't answer this question using the current dataset. {error}. Please upload a relevant dataset or ask a question about the available columns."
            return AskResponse(
                question=question,
                generated_sql="",
                columns=[],
                rows=[],
                row_count=0,
                correction_attempted=False,
                error=msg,
                explanation=msg,
                answerable=False,
                intent=intent,
                statement_type=statement_type
            )
        return AskResponse(
            question=question,
            generated_sql=final_state.get("generated_sql", ""),
            columns=[],
            rows=[],
            row_count=0,
            correction_attempted=final_state.get("correction_attempted", False),
            error=error,
            answerable=True,
            intent=intent,
            statement_type=statement_type,
            execution_time_ms=(time.perf_counter() - t_start) * 1000,
            llm_calls_count=call_count
        )

    # Handle modifying statement preview results
    preview_data = final_state.get("preview_data")
    if preview_data and statement_type.upper() != "SELECT":
        preview_rows = preview_data.get("proposed_data") or preview_data.get("before_after") or []
        if preview_data.get("preview_type") == "COLUMN_DROP_PREVIEW":
            cols = preview_data.get("remaining_columns") or (
                list(preview_rows[0].keys()) if preview_rows and isinstance(preview_rows[0], dict) else []
            )
        else:
            cols = list(preview_rows[0].keys()) if preview_rows and isinstance(preview_rows[0], dict) else ["preview"]
        return AskResponse(
            question=question,
            generated_sql=final_state.get("generated_sql", ""),
            columns=cols,
            rows=preview_rows if isinstance(preview_rows, list) else [{"preview": str(preview_rows)}],
            row_count=preview_data.get("affected_rows_count") if preview_data.get("affected_rows_count") is not None else len(preview_rows),
            correction_attempted=final_state.get("correction_attempted", False),
            error=None,
            answerable=True,
            insight=final_state.get("insight"),
            intent=intent,
            statement_type=statement_type,
            preview=preview_data,
            execution_time_ms=(time.perf_counter() - t_start) * 1000,
            llm_calls_count=call_count
        )

    query_res = final_state.get("query_result") or {}
    is_answerable = True if final_state.get("is_answerable") is None else bool(final_state.get("is_answerable"))
    insight = final_state.get("insight")

    return AskResponse(
        question=question,
        generated_sql=final_state.get("generated_sql", ""),
        columns=query_res.get("columns", []),
        rows=query_res.get("rows", []),
        row_count=query_res.get("row_count", 0),
        correction_attempted=final_state.get("correction_attempted", False),
        error=None,
        answerable=is_answerable,
        insight=insight,
        intent=intent,
        statement_type=statement_type,
        execution_time_ms=(time.perf_counter() - t_start) * 1000,
        llm_calls_count=call_count
    )
