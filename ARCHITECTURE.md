# Architecture — Ask Your Data (Minimal Version)

## Principle
Build the smallest real end-to-end flow. Do not add architecture for hypothetical future features.

## Proposed flow
```text
React frontend
  -> FastAPI backend
      -> Validate and ingest CSV
      -> Calculate dataset profile and summary statistics
      -> Store dataset metadata and data
      -> Read actual schema for selected dataset
      -> LLM proposes SQL from question + schema
      -> Validate read-only SQL
      -> Execute query with limits and timeout
      -> Return SQL + real rows + status/error
      -> Optionally ask LLM to explain calculated summary facts
  -> React displays preview, dataset summary, SQL, and result table
  -> Optional chart renders from actual result rows
```

## Suggested stack
- Frontend: React + Vite.
- Backend: Python + FastAPI.
- Data/query storage: choose one simple, reliable approach during the first milestone. PostgreSQL is appropriate if already available; DuckDB can be simpler for a CSV-first prototype. Do not use both unless there is a clear need.
- LLM: call from the backend using environment-based configuration.
- Charts: Recharts, only after real query results work.
- Tests: pytest for backend behavior.

## Core rules
- The uploaded CSV is the source of truth.
- Resolve schema from the selected dataset, never from a hardcoded example.
- Calculate summary metrics deterministically in code. The LLM may explain calculated metrics but must not invent them.
- Never execute raw user input as SQL.
- Parse and validate generated SQL; enforce read-only database permissions, timeouts, and row limits.
- Use safe table/column identifier handling.
- Database/model failures return truthful errors, never sample analytics.
- The SQL, table results, summary facts, and optional chart must all correspond to the selected dataset and actual computation.

## Dataset summary implementation
For a CSV, calculate row and column counts, inferred types, null counts and percentages, duplicate rows, numeric statistics, common categorical values, and date ranges where appropriate. Avoid misleading statistics for identifiers or columns with unsuitable values. For large files, use a bounded or streaming approach where practical and clearly state when any metrics are approximate.

The base calculated profile should remain available even if LLM narrative generation fails.

## Defer
Do not add LangGraph, vector search, agent memory, automatic joins, XLSX, user accounts, or deployment complexity in the initial version. Reconsider only when the core workflow works and a concrete need is demonstrated.
