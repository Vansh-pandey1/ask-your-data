import time
import io
import tracemalloc
import pandas as pd
from backend.app.profiler import load_dataframe_from_bytes, profile_dataframe
from backend.app.db import db_manager
from backend.app.workflow import run_text_to_sql_workflow
from backend.tests.test_modifying_sql import ModifyingMockLLM


def generate_benchmark_csv(rows: int, cols: int) -> bytes:
    """Generate a realistic benchmark CSV byte payload."""
    data = {}
    for i in range(cols):
        if i % 4 == 0:
            data[f"id_{i}"] = list(range(1, rows + 1))
        elif i % 4 == 1:
            data[f"category_{i}"] = [f"Category_{j % 10}" for j in range(rows)]
        elif i % 4 == 2:
            data[f"amount_{i}"] = [float(j * 1.25) for j in range(rows)]
        else:
            data[f"date_{i}"] = [f"2024-{(j % 12) + 1:02d}-{(j % 28) + 1:02d}" for j in range(rows)]

    df = pd.DataFrame(data)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def benchmark_upload_pipeline(csv_bytes: bytes, label: str):
    """Measure each phase of the upload pipeline with memory tracking."""
    tracemalloc.start()
    t_start = time.perf_counter()

    # 1. Parse DataFrame
    t0 = time.perf_counter()
    df = load_dataframe_from_bytes(csv_bytes)
    t_parse = (time.perf_counter() - t0) * 1000

    # 2. Database Ingestion
    t0 = time.perf_counter()
    db_manager.load_dataset(df, "benchmark.csv")
    t_db = (time.perf_counter() - t0) * 1000

    # 3. Profiling
    t0 = time.perf_counter()
    profile = profile_dataframe(df, "benchmark.csv")
    t_profile = (time.perf_counter() - t0) * 1000

    # 4. Preview Extraction
    t0 = time.perf_counter()
    preview_df = df.head(5).where(pd.notnull(df.head(5)), None)
    preview_rows = preview_df.to_dict(orient="records")
    t_preview = (time.perf_counter() - t0) * 1000

    t_total = (time.perf_counter() - t_start) * 1000
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\n--- Upload Benchmark: {label} ({len(df)} rows, {len(df.columns)} cols) ---")
    print(f"  Parse CSV:          {t_parse:8.2f} ms")
    print(f"  Database Ingestion: {t_db:8.2f} ms")
    print(f"  Profile DataFrame:  {t_profile:8.2f} ms")
    print(f"  Preview Extraction: {t_preview:8.2f} ms")
    print(f"  TOTAL UPLOAD TIME:  {t_total:8.2f} ms")
    print(f"  Peak Memory:        {peak_mem / (1024 * 1024):8.2f} MiB")

    return {
        "parse_ms": t_parse,
        "db_ms": t_db,
        "profile_ms": t_profile,
        "preview_ms": t_preview,
        "total_ms": t_total,
        "peak_mem_mib": peak_mem / (1024 * 1024)
    }


def benchmark_query_pipeline():
    """Measure query execution latency through workflow with mock LLM."""
    csv_bytes = generate_benchmark_csv(500, 8)
    df = load_dataframe_from_bytes(csv_bytes)
    db_manager.load_dataset(df, "query_bench.csv")

    mock_llm = ModifyingMockLLM(
        intent="DATA_ANALYSIS",
        statement_type="SELECT",
        sql="SELECT category_1, SUM(amount_2) FROM dataset GROUP BY category_1",
        insight="Category_0 has highest sales."
    )

    t0 = time.perf_counter()
    res = run_text_to_sql_workflow("What are total sales by category?", custom_llm=mock_llm)
    t_query = (time.perf_counter() - t0) * 1000

    print(f"\n--- Query Benchmark (Mock LLM) ---")
    print(f"  Total Workflow Latency: {t_query:.2f} ms")
    print(f"  Rows returned: {res.row_count}")
    print(f"  LLM Calls Count: {len(mock_llm.calls)}")

    return {
        "query_ms": t_query,
        "llm_calls": len(mock_llm.calls)
    }


if __name__ == "__main__":
    print("=== BASELINE PERFORMANCE BENCHMARK ===")
    small_csv = generate_benchmark_csv(100, 6)
    benchmark_upload_pipeline(small_csv, "Small Dataset")

    medium_csv = generate_benchmark_csv(5000, 10)
    benchmark_upload_pipeline(medium_csv, "Medium Dataset")

    benchmark_query_pipeline()
