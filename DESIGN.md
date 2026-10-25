# Design — Ask Your Data (Minimal Version)

## Goal
A lightweight interface for uploading one CSV, getting a dataset summary, and asking questions about the real data. Prioritize clarity and trust over decoration.

## One-screen layout
1. **Header:** app name and active dataset name/status.
2. **Upload area:** choose a CSV when no dataset is loaded.
3. **Dataset preview:** row count, column count, and a small table of actual rows.
4. **Dataset summary:** readable overview with calculated row/column counts, missing-value findings, duplicate count, and relevant numerical/category/date statistics. Keep factual metrics distinct from AI-generated narrative.
5. **Question box:** plain-language question and submit action.
6. **Answer area:** generated SQL in a collapsible section, result table, and concise explanation based on the actual result.
7. **Optional chart:** add only after the question-and-answer flow works; use Recharts and actual result rows.

## Visual direction
- Light theme.
- Neutral background, restrained accent color, readable typography.
- Simple borders, consistent spacing, minimal shadows.
- Avoid complex glassmorphism, 3D effects, elaborate navigation, animated backgrounds, and unnecessary cards.
- Responsive on laptop and smaller screens.

## States
- Empty: invite the user to upload a CSV.
- Loading: show what is processing.
- Success: show actual dataset, summary, and query results.
- Error: explain what failed and how to recover.
- Never display fake rows, fake summaries, fake charts, or fake success states as real analysis.

## Implementation order
Build only the interface needed for the current milestone. Do not create every screen before the backend workflow is ready.
