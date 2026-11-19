# 0002. Grounded answers with checked citations

**Status:** Accepted

## Context
An assistant that answers confidently from nowhere is worse than no assistant.

## Decision
- The model gets **tools**, not the whole production: `get_day`, `find_scenes`,
  `get_checklist`, `get_issues`, `get_person_or_place`. Every record a tool returns carries
  its source id (`schedule.csv#day-3`, `call_sheet_2026-11-25.pdf`, `checklist.csv#CL-06`).
- The system prompt requires a source id after every fact.
- The app **checks** each citation against the sources the tools actually returned in that
  conversation. Citations the model invented are flagged in the UI and fail the evals.
- The tool loop is our code behind a small `ChatModel` interface, capped at 6 rounds. Tests
  use a scripted fake model, so the loop, citation checks and caching are tested without API
  calls.
- `evals/` holds golden questions (including one where the right answer is "the data
  doesn't say") and a PDF extraction benchmark against ground truth. Scores go in
  `evals/RESULTS.md`.

## Consequences
- Answers can be audited in one click; hallucinated sources are visible, not hidden.
- Adding a capability means adding a tool with a source field, plus an eval case.
