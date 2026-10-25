# Milestones — Minimal Ask Your Data

Work on one milestone at a time. Do not mark it complete until acceptance criteria have been verified. Stop and ask for approval before starting the next milestone.

## Milestone 0 — Check the environment
**Status:** Complete
- [x] Inspect the new project folder and available tools.
- [x] Identify the simplest suitable database/query approach.
- [x] Propose the smallest first implementation.

**Acceptance:** No code changes; explain the plan and dependencies.

## Milestone 1 — CSV profiling and dataset summary
**Status:** Complete
- [x] Create a small backend function that reads a CSV and calculates its profile.
- [x] Calculate row/column counts, inferred types, missing values, duplicate rows, numeric statistics, and suitable category/date summaries.
- [x] Return structured summary data from an API endpoint or testable function.
- [x] Add tests using at least two CSVs with different schemas and known expected statistics.
- [x] Ensure an empty or malformed CSV returns a clear error.

**Acceptance criteria**
- All reported numbers match independently calculated expected values.
- Different input files produce summaries based on their own contents.
- No LLM is needed to calculate facts.
- If LLM narrative is included later, it only explains computed facts and cannot replace them with guesses.

## Milestone 2 — Minimal frontend for upload, preview, and summary
**Status:** Not started
- [ ] Add a simple CSV upload UI.
- [ ] Display the real preview and calculated profile returned by the backend.
- [ ] Add loading, empty, and error states.
- [ ] Do not silently use mock data.

**Acceptance:** Uploading two different CSVs displays their distinct, correct summaries.

## Milestone 3 — One real query
**Status:** Not started
- [ ] Configure one database/query engine.
- [ ] Load a controlled test dataset and execute a fixed read-only query.
- [ ] Return actual rows through an API endpoint.
- [ ] Add an integration test with independently verified expected results.

**Acceptance:** Query results are correct; database failure returns an error, not fake data.

## Milestone 4 — Natural-language questions
**Status:** Not started
- [ ] Call the LLM from the backend.
- [ ] Supply the selected dataset's real schema.
- [ ] Generate, validate, and execute read-only SQL.
- [ ] Return the generated SQL and actual result table.
- [ ] Handle unknown columns, model failures, and SQL errors honestly.

**Acceptance:** Questions return verifiable results on two different datasets. No mocked success fallback.

## Milestone 5 — Simple chart (optional)
**Status:** Not started
- [ ] Add one or two chart types, such as bar and line.
- [ ] Render only from real query result rows.
- [ ] Keep the result table available.

**Acceptance:** Chart values match the returned result rows; unsuitable results show no misleading chart.

## Deferred
Excel, multiple-file joins, authentication, LangGraph, vector search, agent memory, advanced charts, and deployment are out of scope until explicitly approved.
