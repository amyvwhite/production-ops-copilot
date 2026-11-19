# Production Ops Copilot

[![CI](https://github.com/amyvwhite/production-ops-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/amyvwhite/production-ops-copilot/actions/workflows/ci.yml)

An AI assistant for a film/TV production office. It reads the shooting schedule, call
sheets and the production checklist, **catches problems before they cost a shoot day**,
answers questions with **cited sources**, writes the morning briefing, and drafts call sheets.

Built by someone who spent five years as a production coordinator on shows for Disney/Hulu,
Amazon and CBS: the checks are the ones a coordinator or 1st AD runs in their head at 11pm.

> All data in this repo is a **fictional** production ("Harbour Lights"). No real show, crew,
> addresses or documents.

## What it does

| | |
|---|---|
| **Flags problems** (rules, not AI) | Performer turnaround under 12h · location agreement/permit not done days before the shoot · minor without a work permit, or working nights · call sheet that doesn't match the schedule · call sheet missing the nearest hospital, weather or sunset · days over 7 pages · company moves · overdue, blocked and unowned checklist tasks |
| **Answers questions** (Gemini + tools) | "Is the warehouse ready for Thursday?" The model looks things up through tools and cites every fact (`[checklist.csv#CL-01]`); the app verifies each citation against what the tools actually returned and flags any it invented |
| **Daily briefing** | Facts for the day are computed in code; Gemini turns them into a short brief for department heads. Without a key you get the same facts as plain bullets |
| **Generates documents** | Printable call sheet for any day: the issued one, or a draft built from the schedule. Missing values print as **TBC** in red, never guessed; that day's issues are boxed at the top |
| **Reads PDF call sheets** | Upload a PDF; Gemini extracts it to structured data (validated with Pydantic), then the rules check it against the schedule |
| **Production checklist** | Prep / shoot / wrap tasks with owners, due dates and dependencies; update status in the app and the issues update live |

On the sample data the rules engine finds **7 critical issues, 7 warnings and 4 notes**,
including one that wasn't planted: Day 6 wraps at 20:00 and Day 7's crew call is 07:00, so
three actors get 11 hours' rest.

## How it's built

```
sample_data/ (CSV + call-sheet JSON/PDF)
        │  validated by Pydantic models (app/models.py, app/loader.py)
        ▼
   Production ──► rules engine (app/rules.py) ──► Issues, each with sources + a suggested fix
        │                                │
        │        ┌───────────────────────┘
        ▼        ▼
   AI layer (app/ai.py)                       documents (app/documents.py)
   tools: get_day, find_scenes,               call sheet HTML from data only
   get_checklist, get_issues, ...
   citation check · disk cache · daily cap
        │
        ▼
   FastAPI (app/main.py)  ──►  single-page UI (app/static)
```

Design decisions, with the trade-offs: [rules find problems, AI explains them](docs/adr/0001-rules-before-ai.md) ·
[grounded answers with checked citations](docs/adr/0002-grounded-answers.md) ·
[free tier, guardrails and a data rule](docs/adr/0003-free-tier-and-data-governance.md).

## Evaluation

AI features are measured, not assumed. `evals/` has:

- **10 golden questions** about the sample show, each with the facts the answer must contain
  and the record it must cite. One is a trap ("What's for lunch from catering?"): the only
  passing answer admits the data doesn't say. A pass also requires **zero invented citations**.
- **PDF extraction benchmark:** the 5 sample call-sheet PDFs, compared field by field with
  their ground-truth JSON.

```bash
python evals/run_evals.py        # ~30 Gemini calls, fits the free tier; writes evals/RESULTS.md
```

The grader itself is unit-tested (`tests/test_evals.py`), so a bad grader can't hide a bad model.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env              # add GEMINI_API_KEY to turn AI on (free key: aistudio.google.com)
uvicorn app.main:app --reload     # http://localhost:8000
```

Windows: double-click `RUN_APP.bat`. Docker: `docker build -t prodops . && docker run -p 8000:8000 --env-file .env prodops`.

Without a key everything except Ask, the AI briefing and PDF reading still works.

**Data note:** Gemini's free tier may use inputs to improve Google's products. Use the sample
or anonymised documents on the free tier; real production paperwork belongs on a paid tier or
provider with a data agreement ([ADR 0003](docs/adr/0003-free-tier-and-data-governance.md)).

## Quality

- 31 tests at 92% coverage: the rules engine against the planted problems, the AI tool loop,
  citation checks, caching and call cap (with a scripted fake model, so CI never calls the
  API), the HTTP API, the loader's validation, and the eval grader
- ruff (lint + format) and mypy in CI; Docker image built in CI
- Sample data is generated by a script and CI checks it's reproducible

## Roadmap

- Import from real scheduling tools (Movie Magic / StudioBinder exports) behind the same loader contract
- Weather and sunset lookup for draft call sheets
- Slack bot on the same API for the morning briefing
- Per-production thresholds (union agreements) in a config file

## Licence

All rights reserved. The code is public to view as part of my portfolio; see [LICENSE](LICENSE).
