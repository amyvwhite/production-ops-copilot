"""The eval scorer itself is tested, so a bad grader can't hide a bad model."""

import json
from pathlib import Path

from evals.run_evals import score_answer

CASES = {c["id"]: c for c in json.loads((Path(__file__).parents[1] / "evals" / "qa_cases.json").read_text())["cases"]}


def test_good_answer_passes():
    case = CASES["warehouse-ready"]
    r = score_answer(
        case, "No: the location agreement is still open [checklist.csv#CL-01].", ["checklist.csv#CL-01"], []
    )
    assert r["passed"]


def test_missing_fact_or_citation_or_invented_source_fails():
    case = CASES["kane-house-scenes"]
    assert not score_answer(case, "Scenes 13, 14 and 15.", ["scenes.csv#sc-13"], [])["passed"]
    full = "Scenes 13, 14, 15, 16, 24, 25 and 26."
    assert not score_answer(case, full, [], [])["passed"]
    assert not score_answer(case, full, ["schedule.csv#day-5"], ["fake.csv#1"])["passed"]
    assert score_answer(case, full, ["schedule.csv#day-5"], [])["passed"]


def test_abstain_case_requires_admitting_the_gap():
    case = CASES["abstain-catering"]
    assert score_answer(case, "I don't have catering information in the production data.", [], [])["passed"]
    assert not score_answer(case, "Lunch is lasagna.", [], [])["passed"]
