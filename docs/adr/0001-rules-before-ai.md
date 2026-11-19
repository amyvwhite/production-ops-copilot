# 0001. Rules find problems; AI explains them

**Status:** Accepted

## Context
A production office lives on correctness: a wrong call time or a missed permit costs a shoot
day. Language models are good at reading and summarising, and bad at guaranteeing they
checked everything.

## Decision
Problems are found by deterministic rules in `app/rules.py` (turnaround, location paperwork,
minors, call sheet vs schedule, safety info, page counts, checklist). The model never decides
whether something is a problem. It answers questions *about* the data and the issues, and
writes briefings from facts computed in code. Call sheets are generated from data only, with
missing values printed as "TBC" in red rather than guessed.

## Consequences
- Every issue is reproducible, testable and cited (`tests/test_rules.py` checks the engine
  finds exactly the problems planted in the sample data, plus one it found that wasn't planted).
- The app is fully useful with no AI key: issues, checklist, documents and a plain briefing.
- Thresholds (12h turnaround, 7 pages a day, 3-day lookahead) are named constants a
  production can change to match its agreements.
