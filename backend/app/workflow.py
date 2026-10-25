import os
import re
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from .db import db_manager, validate_sql
from .schemas import AskResponse


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
    Requires GEMINI_API_KEY or GOOGLE_API_KEY in environment.
    """
    if custom_llm is not None:
        return custom_llm

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not configured on the backend. "
            "Please set your Google Gemini API key to enable natural-language questions."
        )

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=0.0
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
    1. Generate SQL from user question + active dataset schema.
    2. Validate SQL with sqlglot (read-only SELECT only).
    3. Execute query on SQLite.
    4. On execution error, allow at most one correction attempt.
    5. Return actual results or an honest error.
    """

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
        raw_text = response.content if hasattr(response, "content") else str(response)
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
        raw_text = response.content if hasattr(response, "content") else str(response)
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

    builder = StateGraph(SQLWorkflowState)

    builder.add_node("generate_sql_node", generate_sql_node)
    builder.add_node("validate_sql_node", validate_sql_node)
    builder.add_node("execute_sql_node", execute_sql_node)
    builder.add_node("correct_sql_node", correct_sql_node)
    builder.add_node("set_validation_error_end", set_validation_error_end)
    builder.add_node("set_execution_error_end", set_execution_error_end)

    builder.add_edge(START, "generate_sql_node")
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

    return builder.compile()


def run_text_to_sql_workflow(
    question: str,
    row_limit: int = 100,
    custom_llm: Optional[Any] = None
) -> AskResponse:
    """Execute the text-to-SQL workflow and return AskResponse."""
    # Ensure active dataset exists
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
        "row_limit": row_limit
    }

    final_state = graph.invoke(initial_state)

    if final_state.get("final_error"):
        return AskResponse(
            question=question,
            generated_sql=final_state.get("generated_sql", ""),
            columns=[],
            rows=[],
            row_count=0,
            correction_attempted=final_state.get("correction_attempted", False),
            error=final_state.get("final_error")
        )

    query_res = final_state.get("query_result") or {}
    return AskResponse(
        question=question,
        generated_sql=final_state.get("generated_sql", ""),
        columns=query_res.get("columns", []),
        rows=query_res.get("rows", []),
        row_count=query_res.get("row_count", 0),
        correction_attempted=final_state.get("correction_attempted", False),
        error=None
    )
