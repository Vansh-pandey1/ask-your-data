import os
import re
from typing import TypedDict, List, Dict, Any, Optional
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from .db import db_manager, validate_sql, validate_sql_against_schema
from .schemas import AskResponse

# Load environment variables from .env if present
load_dotenv()


class SQLWorkflowState(TypedDict):
    question: str
    schema_context: str
    generated_sql: str
    validation_error: Optional[str]
    execution_error: Optional[str]
    final_error: Optional[str]
    query_result: Optional[Dict[str, Any]]
    correction_attempted: bool
    row_limit: int
    # Answerability fields
    is_answerable: Optional[bool]
    unanswerable_reason: Optional[str]


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
    Get configured Gemini LLM or custom test LLM.
    Requires GOOGLE_API_KEY or GEMINI_API_KEY in environment.
    """
    if custom_llm is not None:
        return custom_llm

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY or GEMINI_API_KEY environment variable is not configured on the backend. "
            "Please set your Google Gemini API key to enable natural-language questions."
        )

    model_name = os.environ.get("GOOGLE_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key
    )


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
    Construct the LangGraph StateGraph for Text-to-SQL:
    1. Check answerability - can the question be answered with available columns?
    2. Generate SQL from user question + active dataset schema.
    3. Validate SQL with sqlglot (read-only SELECT only).
    4. Execute query on SQLite.
    5. On execution error, allow at most one correction attempt.
    6. Return actual results or an honest error.
    """

    def check_answerability_node(state: SQLWorkflowState) -> Dict[str, Any]:
        """
        Determine if the question is answerable using the active dataset schema.
        Returns a clear explanation if unanswerable, without generating substitute SQL.
        """
        # Get schema from db_manager
        schema = db_manager.get_schema()
        available_columns = {col.name for col in schema.columns}

        # Use LLM to classify whether the question is answerable
        # We ask the LLM to evaluate based on the schema, not generate SQL
        prompt = (
            f"You are a dataset analyst. Determine if the user's question can be answered "
            f"using ONLY the columns available in the dataset schema below.\n\n"
            f"Schema:\n{state['schema_context']}\n\n"
            f"User question: {state['question']}\n\n"
            f"Respond with ONLY a JSON object in this format:\n"
            f'{{"answerable": true/false, "reason": "explanation if not answerable"}}\n\n'
            f"Rules:\n"
            f"1. If the question references concepts, columns, or entities not present in the schema, answerable=false.\n"
            f"2. Do NOT assume synonyms map to different columns (e.g., 'region' ≠ 'department', 'sales' ≠ 'salary').\n"
            f"3. If the question requires joining, aggregating, or filtering on columns that don't exist, answerable=false.\n"
            f"4. Only answerable=true if the question can be fully answered with the available columns."
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        raw_text = extract_text_from_response(response)

        # Parse JSON response
        import json
        try:
            result = json.loads(raw_text.strip())
            is_answerable = result.get("answerable", False)
            reason = result.get("reason", "")
        except Exception:
            # If LLM fails to return valid JSON, default to not answerable for safety
            is_answerable = False
            reason = "Could not determine answerability. Please check your question against the available columns."

        if not is_answerable:
            return {
                "is_answerable": False,
                "unanswerable_reason": reason,
                "generated_sql": "",
                "validation_error": None,
                "execution_error": None,
                "final_error": None,
                "query_result": None,
                "correction_attempted": False
            }

        return {"is_answerable": True, "unanswerable_reason": None}

    def generate_sql_node(state: SQLWorkflowState) -> Dict[str, Any]:
        prompt = (
            f"You are a helpful SQL assistant. Write a single SQLite read-only query to answer the user's question.\n"
            f"Rules:\n"
            f"1. Use ONLY the table '{db_manager.table_name}' and the columns listed in the schema.\n"
            f"2. Return ONLY the SQL query. Do not include markdown explanations or text outside the query.\n"
            f"3. Do not modify the database (only SELECT queries are allowed).\n\n"
            f"Schema:\n{state['schema_context']}\n\n"
            f"User question: {state['question']}"
        )
        response = llm.invoke([SystemMessage(content="You generate valid SQLite SQL queries."), HumanMessage(content=prompt)])
        raw_text = extract_text_from_response(response)
        sql = clean_sql(raw_text)
        return {"generated_sql": sql}

    def validate_sql_node(state: SQLWorkflowState) -> Dict[str, Any]:
        try:
            validate_sql(state["generated_sql"])
            return {"validation_error": None}
        except ValueError as e:
            return {"validation_error": str(e)}

    def execute_sql_node(state: SQLWorkflowState) -> Dict[str, Any]:
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

    def correct_sql_node(state: SQLWorkflowState) -> Dict[str, Any]:
        err_msg = state.get("validation_error") or state.get("execution_error") or "Unknown error"
        prompt = (
            f"The previous SQL query produced an error. Please fix the SQL query to answer the question.\n\n"
            f"Schema:\n{state['schema_context']}\n\n"
            f"User question: {state['question']}\n\n"
            f"Failed SQL: {state['generated_sql']}\n\n"
            f"Error message: {err_msg}\n\n"
            f"Return ONLY the corrected SQLite SQL query."
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
    def route_after_answerability(state: SQLWorkflowState) -> str:
        if state.get("is_answerable") is False:
            return "set_unanswerable_end"
        return "generate_sql_node"

    def route_after_validation(state: SQLWorkflowState) -> str:
        if state.get("validation_error"):
            if not state.get("correction_attempted", False):
                return "correct_sql_node"
            return "set_validation_error_end"
        return "execute_sql_node"

    def route_after_execution(state: SQLWorkflowState) -> str:
        if state.get("execution_error"):
            if not state.get("correction_attempted", False):
                return "correct_sql_node"
            return "set_execution_error_end"
        return END

    def set_validation_error_end(state: SQLWorkflowState) -> Dict[str, Any]:
        return {"final_error": state.get("validation_error")}

    def set_execution_error_end(state: SQLWorkflowState) -> Dict[str, Any]:
        return {"final_error": state.get("execution_error")}

    def set_unanswerable_end(state: SQLWorkflowState) -> Dict[str, Any]:
        return {"final_error": state.get("unanswerable_reason")}

    builder = StateGraph(SQLWorkflowState)

    builder.add_node("check_answerability_node", check_answerability_node)
    builder.add_node("generate_sql_node", generate_sql_node)
    builder.add_node("validate_sql_node", validate_sql_node)
    builder.add_node("execute_sql_node", execute_sql_node)
    builder.add_node("correct_sql_node", correct_sql_node)
    builder.add_node("set_validation_error_end", set_validation_error_end)
    builder.add_node("set_execution_error_end", set_execution_error_end)
    builder.add_node("set_unanswerable_end", set_unanswerable_end)

    builder.add_edge(START, "check_answerability_node")

    builder.add_conditional_edges(
        "check_answerability_node",
        route_after_answerability,
        {
            "generate_sql_node": "generate_sql_node",
            "set_unanswerable_end": "set_unanswerable_end"
        }
    )

    builder.add_edge("generate_sql_node", "validate_sql_node")

    builder.add_conditional_edges(
        "validate_sql_node",
        route_after_validation,
        {
            "correct_sql_node": "correct_sql_node",
            "execute_sql_node": "execute_sql_node",
            "set_validation_error_end": "set_validation_error_end"
        }
    )

    builder.add_conditional_edges(
        "execute_sql_node",
        route_after_execution,
        {
            "correct_sql_node": "correct_sql_node",
            "set_execution_error_end": "set_execution_error_end",
            END: END
        }
    )

    builder.add_edge("correct_sql_node", "validate_sql_node")
    builder.add_edge("set_validation_error_end", END)
    builder.add_edge("set_execution_error_end", END)
    builder.add_edge("set_unanswerable_end", END)

    return builder.compile()


def run_text_to_sql_workflow(
    question: str,
    row_limit: int = 100,
    custom_llm: Optional[Any] = None
) -> AskResponse:
    """Execute the text-to-SQL workflow and return AskResponse."""
    schema_context = build_schema_context()

    llm = get_gemini_llm(custom_llm)
    graph = create_sql_workflow(llm)

    initial_state: SQLWorkflowState = {
        "question": question,
        "schema_context": schema_context,
        "generated_sql": "",
        "validation_error": None,
        "execution_error": None,
        "final_error": None,
        "query_result": None,
        "correction_attempted": False,
        "row_limit": row_limit,
        "is_answerable": None,
        "unanswerable_reason": None
    }

    final_state = graph.invoke(initial_state)

    if final_state.get("final_error"):
        error = final_state.get("final_error") or "Query failed"
        # Check if this was an unanswerable response (not a true error)
        if final_state.get("unanswerable_reason") or (not final_state.get("generated_sql") and final_state.get("final_error")):
            # This is an answerability response, not a real error
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
                answerable=False
            )
        return AskResponse(
            question=question,
            generated_sql=final_state.get("generated_sql", "") if final_state.get("generated_sql") else "",
            columns=[],
            rows=[],
            row_count=0,
            correction_attempted=final_state.get("correction_attempted", False),
            error=error,
            answerable=True  # Any real error means it was answerable but failed
            # Note: if the question was unanswerable, error will contain the explanation
        )

    query_res = final_state.get("query_result") or {}
    is_answerable = final_state.get("is_answerable", True)

    return AskResponse(
        question=question,
        generated_sql=final_state.get("generated_sql", ""),
        columns=query_res.get("columns", []),
        rows=query_res.get("rows", []),
        row_count=query_res.get("row_count", 0),
        correction_attempted=final_state.get("correction_attempted", False),
        error=None,
        answerable=is_answerable
    )
