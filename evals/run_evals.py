"""Score the assistant against golden questions and the PDF extractor against ground truth.

Uses the real Gemini API (GEMINI_API_KEY), about 30 calls in total, which fits the free
tier. A pause between questions keeps it under the free-tier per-minute limit.

    python evals/run_evals.py                 # both suites
    python evals/run_evals.py --only qa       # or: --only extract

Writes evals/results/<timestamp>.json and rewrites evals/RESULTS.md with the latest scores.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai import (  # noqa: E402
    AIUnavailable,
    Cache,
    GeminiChat,
    extract_call_sheet,
    make_assistant,
)
from app.config import get_settings  # noqa: E402
from app.loader import demo_today, load_production  # noqa: E402

DATA = ROOT / "sample_data"
HERE = Path(__file__).resolve().parent


def score_answer(case: dict, text: str, verified: list[str], unverified: list[str]) -> dict:
    low = text.lower()
    groups = [any(p.lower() in low for p in group) for group in case["expect"]]
    cited = not case.get("cite_any") or any(c in verified for c in case["cite_any"])
    return {
        "facts_ok": all(groups),
        "groups_hit": f"{sum(groups)}/{len(groups)}",
        "cited_ok": cited,
        "unverified": unverified,
        "passed": all(groups) and cited and not unverified,
    }


def run_qa(pause: float) -> dict:
    settings = get_settings()
    prod = load_production(DATA)
    # Fresh cache dir so every run really asks the model.
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    settings = settings.__class__(**{**settings.__dict__, "cache_dir": ROOT / ".cache" / f"eval-{stamp}"})
    assistant = make_assistant(prod, demo_today(DATA), settings)
    if assistant.model is None:
        raise SystemExit("Set GEMINI_API_KEY to run the evals.")
    cases = json.loads((HERE / "qa_cases.json").read_text())["cases"]
    results = []
    for case in cases:
        try:
            a = assistant.ask(case["question"])
            row = {
                "id": case["id"],
                "question": case["question"],
                "answer": a.text,
                "tools": a.tools_used,
                **score_answer(case, a.text, a.citations, a.unverified_citations),
            }
        except AIUnavailable as exc:
            row = {"id": case["id"], "question": case["question"], "error": str(exc), "passed": False}
        results.append(row)
        print(("PASS " if row["passed"] else "FAIL ") + case["id"])
        time.sleep(pause)
    passed = sum(r["passed"] for r in results)
    return {"suite": "qa", "passed": passed, "total": len(results), "results": results}


FIELDS = ["date", "day_number", "crew_call", "shooting_call", "est_wrap", "nearest_hospital", "location_ids"]


def run_extract(pause: float) -> dict:
    settings = get_settings()
    model = GeminiChat(settings)
    prod = load_production(DATA)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    cache = Cache(ROOT / ".cache" / f"eval-extract-{stamp}")
    rows, right, total = [], 0, 0
    for truth in prod.call_sheets:
        pdf = (DATA / "pdfs" / f"call_sheet_{truth.date}.pdf").read_bytes()
        try:
            got = extract_call_sheet(pdf, model, cache, f"call_sheet_{truth.date}.pdf")
        except (AIUnavailable, ValueError) as exc:
            rows.append({"date": str(truth.date), "error": str(exc)})
            total += len(FIELDS) + 2
            continue
        checks = {f: getattr(got, f) == getattr(truth, f) for f in FIELDS}
        checks["scene_numbers"] = got.scene_numbers == truth.scene_numbers
        checks["cast_on_set"] = {c.cast_id: c.on_set for c in got.cast_calls} == {
            c.cast_id: c.on_set for c in truth.cast_calls
        }
        right += sum(checks.values())
        total += len(checks)
        rows.append({"date": str(truth.date), "fields": checks})
        print(f"{truth.date}: {sum(checks.values())}/{len(checks)} fields")
        time.sleep(pause)
    return {"suite": "extract", "fields_right": right, "fields_total": total, "results": rows}


def write_report(runs: list[dict]) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    (HERE / "results").mkdir(exist_ok=True)
    out = HERE / "results" / f"{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    out.write_text(
        json.dumps({"run_at": stamp, "model": get_settings().gemini_model, "runs": runs}, indent=2, default=str)
    )
    lines = [
        "# Eval results (latest run)",
        "",
        f"Run {stamp} with `{get_settings().gemini_model}`. Raw: `{out.relative_to(ROOT)}`.",
        "",
    ]
    for run in runs:
        if run["suite"] == "qa":
            lines += [
                f"## Question answering: {run['passed']}/{run['total']} passed",
                "",
                "A pass needs every expected fact, at least one verified citation to the right record, and "
                "no citations the model invented.",
                "",
                "| Case | Result | Facts | Cited | Lookups |",
                "|---|---|---|---|---|",
            ]
            for r in run["results"]:
                lines.append(
                    f"| {r['id']} | {'pass' if r['passed'] else 'FAIL'} | {r.get('groups_hit', '-')} | "
                    f"{'yes' if r.get('cited_ok') else 'no'} | {', '.join(r.get('tools', [])) or '-'} |"
                )
        else:
            pct = 100 * run["fields_right"] / max(run["fields_total"], 1)
            lines += [
                "",
                f"## PDF call-sheet extraction: {run['fields_right']}/{run['fields_total']} fields ({pct:.0f}%)",
                "",
                "Fields compared with the ground-truth JSON for each sample PDF.",
            ]
        lines.append("")
    (HERE / "RESULTS.md").write_text("\n".join(lines))
    print(f"\nWrote {out.relative_to(ROOT)} and evals/RESULTS.md")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only", choices=["qa", "extract"])
    p.add_argument("--pause", type=float, default=6.0, help="seconds between calls (free-tier friendly)")
    args = p.parse_args()
    runs = []
    if args.only in (None, "qa"):
        runs.append(run_qa(args.pause))
    if args.only in (None, "extract"):
        runs.append(run_extract(args.pause))
    write_report(runs)


if __name__ == "__main__":
    main()
