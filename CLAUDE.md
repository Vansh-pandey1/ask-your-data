# Ask Your Data — Claude Code Rules

## Goal
Build a small app where a user uploads one CSV, asks a question about its data, and receives a real answer with a result table. A simple chart is optional after the core workflow works.

## Work in small steps
- Implement one milestone at a time.
- Before coding, inspect relevant files and state the smallest planned change.
- Do not implement future milestones early.
- Run relevant tests and report the actual commands and results.
- Mark a task complete only after its acceptance criteria pass.
- Stop after each milestone and wait for approval.

## Data integrity
- Never show hardcoded or mocked analytics as real results.
- Never silently fall back to sample data if the API, model, or database fails.
- Use the currently selected dataset's actual schema and records.
- Do not assume fixed column names or a particular sample dataset.
- If a query fails or cannot be answered, explain the failure instead of inventing an answer.
- Test with at least two structurally different CSV files.

## Safety
- Validate uploaded CSV files and impose a file-size limit.
- Allow only read-only analytical SQL.
- Validate generated SQL before execution.
- Use query timeouts and result limits.
- Keep secrets on the backend and out of logs and frontend code.
- Keep each uploaded dataset isolated from other datasets.

## Scope limits
Do not add authentication, Excel support, multiple-file joins, agent memory, autonomous multi-step planning, vector search, advanced charting, or deployment infrastructure unless explicitly requested later.

## Completion report
At the end of each milestone, report changed files, implemented behavior, tests and actual results, known limitations, and the proposed next milestone. Do not start the next milestone without approval.
