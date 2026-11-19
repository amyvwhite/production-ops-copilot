"""AI layer with a scripted fake model: tool loop, citation checking, caching, fallbacks."""

from __future__ import annotations

from datetime import date

import pytest

from app.ai import AIUnavailable, Assistant, DailyBudget, build_tools, extract_call_sheet
from app.models import Status
from tests.conftest import TODAY, ScriptedModel, say, tool


def test_tool_loop_answers_with_verified_citations(prod, cache):
    model = ScriptedModel(
        [
            tool("get_day", day_number=4),
            say(
                "Day 4 is at the Cherry St. Warehouse [schedule.csv#day-4] but the agreement is unsigned "
                "[checklist.csv#CL-01]. Also see [made-up.csv#1]."
            ),
        ]
    )
    a = Assistant(prod, TODAY, model, cache).ask("Is the warehouse ready?")
    assert a.tools_used == ["get_day"]
    assert "schedule.csv#day-4" in a.citations
    # CL-01 wasn't in any tool result the model saw, and made-up never existed: both flagged.
    assert set(a.unverified_citations) == {"checklist.csv#CL-01", "made-up.csv#1"}
    # The tool result was sent back to the model before it answered.
    assert model.calls[1][-1]["role"] == "tool"


def test_answers_are_cached_per_question_and_data_version(prod, cache):
    model = ScriptedModel([say("Day 1 is Nov 23 [schedule.csv#day-1].")])
    assistant = Assistant(prod, TODAY, model, cache)
    first = assistant.ask("When is day 1?")
    again = assistant.ask("  WHEN IS DAY 1?  ")
    assert again.cached and again.text == first.text and len(model.calls) == 1
    prod.checklist_item("CL-01").status = Status.done  # data changed: cache key changes
    with pytest.raises(IndexError):  # script is empty, so a new model call was attempted
        Assistant(prod, TODAY, model, cache).ask("When is day 1?")


def test_bad_tool_arguments_go_back_to_the_model_as_errors(prod, cache):
    model = ScriptedModel([tool("get_day", date_iso="not-a-date"), say("I couldn't find that day.")])
    a = Assistant(prod, TODAY, model, cache).ask("what about day x?")
    assert "error" in model.calls[1][-1]["results"][0]["result"]
    assert a.text == "I couldn't find that day."


def test_too_many_tool_rounds_stops(prod, cache):
    model = ScriptedModel([tool("get_issues")] * 10)
    with pytest.raises(AIUnavailable, match="too many lookups"):
        Assistant(prod, TODAY, model, cache).ask("loop forever")


def test_no_key_means_no_ai_but_briefing_still_works(prod, cache):
    assistant = Assistant(prod, TODAY, None, cache)
    with pytest.raises(AIUnavailable):
        assistant.ask("anything")
    b = assistant.briefing(date(2026, 11, 25))
    assert not b["ai"] and "Turnaround" in b["text"] and "4 1/8 pages" in b["text"]


def test_ai_briefing_is_written_from_computed_facts(prod, cache):
    model = ScriptedModel([say("- Day 3: 07:00 call [schedule.csv#day-3]")])
    b = Assistant(prod, TODAY, model, cache).briefing(date(2026, 11, 25))
    assert b["ai"] and b["text"].startswith("- Day 3")
    prompt = model.calls[0][0]["text"]
    assert "Turnaround" in prompt and "issues_for_day" in prompt  # facts went in, not the raw data
    assert Assistant(prod, TODAY, model, cache).briefing(date(2026, 11, 25))["cached"]


def test_tools_return_sources(prod):
    tools = {t.name: t.fn for t in build_tools(prod, TODAY)}
    day = tools["get_day"](day_number=3)
    assert day["source"] == "schedule.csv#day-3" and day["call_sheet"]["source"] == "call_sheet_2026-11-25.pdf"
    hits = tools["find_scenes"](text="kane house")
    assert {h["scene"] for h in hits["matches"]} == {"13", "14", "15", "16", "24", "25", "26"}
    person = tools["get_person_or_place"](name="lily")
    assert person["cast"][0]["minor"] and person["cast"][0]["working_days"] == ["Day 5 2026-11-27", "Day 8 2026-12-02"]
    assert tools["get_checklist"](status="done")["count"] == 5
    assert tools["get_issues"](severity="critical")["count"] == 7


def test_daily_budget_caps_calls(tmp_path):
    budget = DailyBudget(tmp_path / "calls.json", cap=2)
    budget.spend()
    budget.spend()
    with pytest.raises(AIUnavailable, match="cap"):
        budget.spend()


def test_pdf_extraction_validates_and_caches(cache):
    extracted = {
        "date": "2026-11-25",
        "day_number": 3,
        "crew_call": "07:00",
        "shooting_call": "08:00",
        "est_wrap": "18:30",
        "location_ids": ["L1"],
        "scene_numbers": ["4", "6"],
        "cast_calls": [{"cast_id": "1", "on_set": "07:00", "hmu": "06:15"}],
    }
    model = ScriptedModel([], extracted=extracted)
    sheet = extract_call_sheet(b"%PDF-1.7 fake", model, cache, "day3.pdf")
    assert sheet.day_number == 3 and sheet.cast_calls[0].hmu.hour == 6 and sheet.source == "day3.pdf"
    extract_call_sheet(b"%PDF-1.7 fake", model, cache, "day3.pdf")
    assert model.extract_calls == 1  # second read came from the cache


def test_pdf_extraction_rejects_invalid_output(cache):
    model = ScriptedModel([], extracted={"date": "someday", "day_number": "x"})
    with pytest.raises(ValueError):
        extract_call_sheet(b"%PDF-1.7 other", model, cache, "bad.pdf")
