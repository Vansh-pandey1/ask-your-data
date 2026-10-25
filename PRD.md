# Product Requirements — Ask Your Data (Minimal Version)

## Product goal
Let a user upload one CSV and explore the actual data in plain English without writing SQL.

## Core user-facing capabilities
1. **Upload and preview:** upload one CSV; show its column names, row count, and a few real rows.
2. **Dataset summary:** generate a useful overview of the uploaded dataset, including calculated statistics and data-quality findings, explained in plain English.
3. **Ask a question:** translate a natural-language question into read-only SQL, execute it against the selected dataset, and show the real result table and SQL.
4. **Optional simple chart:** after the core workflow works, display a basic chart when the result is suitable.

## Dataset summary requirements
The summary must be based on the uploaded dataset, not a hardcoded template or a few rows sent to an LLM.

Calculate deterministic facts in code, where applicable:
- Total rows and columns.
- Column names and inferred data types.
- Missing-value count and percentage per column.
- Duplicate-row count.
- Numerical column statistics such as minimum, maximum, mean, and median when meaningful.
- Basic category counts for suitable categorical columns.
- Date range for columns confidently identified as dates.

Then use the LLM, if configured, to explain these calculated facts in clear language and suggest a few possible questions. The LLM must not invent statistics, correlations, causes, or conclusions unsupported by the computed data. If the LLM is unavailable, the application should still show the calculated profile and a clear note that the narrative explanation could not be generated.

## Initial constraints
- CSV only.
- One dataset at a time.
- One simple workspace screen.
- One backend and one database/query engine.
- No multi-file joins, Excel, accounts, teams, advanced agent workflows, or vector database.
- Do not optimize for many features. Optimize for a reliable end-to-end flow.

## Trust requirements
- No hardcoded answers or mocked analytics in the real application path.
- No silent demo-data fallback.
- The selected dataset determines the schema, summary, and query context.
- Show errors honestly.
- Keep generated SQL visible to the user.
- Restrict execution to safe, read-only queries.

## Definition of a successful first version
A user uploads a CSV, sees a correct profile and summary for that file, asks a question about its actual columns, and gets a verifiable result table and the SQL that produced it. The same workflow works on a second CSV with different columns without changing application code.
