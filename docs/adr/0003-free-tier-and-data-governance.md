# 0003. Gemini free tier, with guardrails and a data rule

**Status:** Accepted

## Context
The project should cost nothing to run. Gemini's free tier fits, but it is rate limited, and
Google's terms for the free tier allow inputs to be used to improve its products.

## Decision
- **Sample data only on the free tier.** The repo ships a fictional production; the README and
  upload screen say not to send real production documents unless the project is on a paid
  tier (or another provider) with a data agreement.
- **Cost and quota guardrails:** responses are cached on disk by question + data version, PDF
  extractions by file hash; a per-day call cap (`MAX_AI_CALLS_PER_DAY`); clear 429 handling.
- **Graceful degradation:** without a key or over the cap, AI features return a clear message
  and everything else keeps working.
- **No key in code:** `GEMINI_API_KEY` comes from the environment / a git-ignored `.env`.
- Model name is configuration (`GEMINI_MODEL`), so moving to a newer model is a setting.

## Consequences
- Running the demo and the evals costs $0.
- Real deployment would swap the data rule for the studio's AI policy, not change the code.
