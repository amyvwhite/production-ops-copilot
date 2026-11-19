"""The rules engine must find exactly the problems planted in the sample production."""

from __future__ import annotations

import json
from datetime import date

from app.models import Severity, Status
from app.rules import find_issues
from tests.conftest import SAMPLE, TODAY


def keyed(issues):
    """Map each issue to the same key format as sample_data/expected_issues.json."""
    out: dict[str, set[str]] = {}
    for i in issues:
        src = " ".join(i.sources)
        if i.code in ("TURNAROUND", "MINOR_PERMIT", "MINOR_HOURS"):
            cast = i.title.split("(cast ")[1].split(")")[0]
            key = f"{cast}@{i.date}"
        elif i.code == "PERMIT_NOT_READY":
            key = f"{src.split('locations.csv#')[1].split()[0]}@{i.date}"
        elif i.code in ("OVERDUE_TASK", "BLOCKED_TASK", "NO_OWNER"):
            key = i.sources[0].split("#")[1]
        else:
            key = str(i.date)
        out.setdefault(i.code, set()).add(key)
    return out


def test_finds_every_planted_problem_and_nothing_else(prod):
    expected = {k: set(v) for k, v in json.loads((SAMPLE / "expected_issues.json").read_text()).items()}
    assert keyed(find_issues(prod, TODAY)) == expected


def test_critical_issues_sort_first(prod):
    severities = [i.severity for i in find_issues(prod, TODAY)]
    assert severities == sorted(severities, key=[Severity.critical, Severity.warning, Severity.info].index)


def test_every_issue_cites_a_source_and_suggests_a_fix(prod):
    for issue in find_issues(prod, TODAY):
        assert issue.sources and issue.fix


def test_turnaround_math(prod):
    t = next(i for i in find_issues(prod, TODAY) if i.code == "TURNAROUND" and "cast 1" in i.title)
    # Day 2 est. wrap 23:30 -> cast 1 makeup call 06:15 on Day 3 = 6.75h
    assert "6.8h" in t.title and "11:30" in t.fix


def test_signing_the_agreement_clears_the_location_issue(prod):
    prod.checklist_item("CL-01").status = Status.done
    codes = {i.code for i in find_issues(prod, TODAY)}
    assert "PERMIT_NOT_READY" not in codes


def test_unblocking_a_dependency_clears_the_blocked_task(prod):
    prod.checklist_item("CL-07").status = Status.done
    assert not [i for i in find_issues(prod, TODAY) if i.code == "BLOCKED_TASK"]


def test_far_future_paperwork_is_not_critical_yet(prod):
    # The pier (Day 7, Dec 1) has open paperwork, but it's 7 days out on Nov 24.
    pier = [i for i in find_issues(prod, TODAY) if i.code == "PERMIT_NOT_READY" and "Pier" in i.title]
    assert pier == []


def test_past_days_are_not_reported(prod):
    later = date(2026, 12, 2)
    assert all((i.date or later) >= date(2026, 11, 20) for i in find_issues(prod, later))
    assert not [i for i in find_issues(prod, later) if i.code == "CALL_SHEET_MISMATCH"]


def test_missing_call_sheet_for_next_day(prod):
    issues = find_issues(prod, date(2026, 11, 27))  # next shoot day Nov 30 has no call sheet
    assert any(i.code == "MISSING_CALL_SHEET" and str(i.date) == "2026-11-30" for i in issues)
