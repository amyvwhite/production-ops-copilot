"""Find problems in a production before they cost a shoot day.

Deterministic rules, no AI: these are the checks a production coordinator or 1st AD runs
in their head, written down so they run every time. Each Issue cites the records it came
from. The AI layer narrates and answers questions *about* these issues; it never decides
whether something is a problem (see docs/adr/0001-rules-before-ai.md).

Thresholds are named constants so a production can tune them to its union agreements.
They are sensible defaults, not legal advice.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta
from itertools import pairwise

from app.loader import fmt_time
from app.models import Issue, Production, Severity, ShootDay, Status

TURNAROUND_HOURS = 12  # minimum rest between wrap and next call for performers
LOOKAHEAD_DAYS = 3  # how far ahead "must be done before the shoot" items become critical
MAX_PAGES_EIGHTHS = 56  # 7 pages a day
MINOR_LATEST_WRAP = time(21, 0)  # check minors' hours if work runs past this
PAPERWORK = re.compile(r"\b(agreement|permit|contract|insurance|certificate)\b", re.I)

Rule = Callable[[Production, date], Iterator[Issue]]


def _dt(day: date, t: time) -> datetime:
    return datetime.combine(day, t)


def _upcoming(prod: Production, today: date, days: int = LOOKAHEAD_DAYS) -> list[ShootDay]:
    return [d for d in prod.days if today <= d.date <= today + timedelta(days=days)]


def _cast_name(prod: Production, cast_id: str) -> str:
    c = prod.cast_member(cast_id)
    return f"{c.name} (cast {cast_id})" if c else f"cast {cast_id}"


# ---- performers ----------------------------------------------------------------


def turnaround(prod: Production, today: date) -> Iterator[Issue]:
    """Performer called too soon after the previous day's wrap."""
    days = [d for d in prod.days if d.date >= today - timedelta(days=1)]
    for prev, nxt in pairwise(days):
        sheet = prod.call_sheet_on(nxt.date)
        prev_sheet = prod.call_sheet_on(prev.date)
        wrap = _dt(prev.date, (prev_sheet or prev).est_wrap)
        for cast_id in prod.day_cast(prev):
            if cast_id not in prod.day_cast(nxt):
                continue
            call_t = nxt.crew_call
            if sheet:
                cc = next((c for c in sheet.cast_calls if c.cast_id == cast_id), None)
                if cc:  # the performer's own first call: makeup if they have one
                    call_t = cc.hmu or cc.on_set
            rest = (_dt(nxt.date, call_t) - wrap).total_seconds() / 3600
            if rest < TURNAROUND_HOURS:
                yield Issue(
                    code="TURNAROUND",
                    severity=Severity.critical,
                    date=nxt.date,
                    title=f"Turnaround: {_cast_name(prod, cast_id)} gets {rest:.1f}h rest",
                    detail=f"Day {prev.day_number} wraps {fmt_time(wrap.time())} (est.) and the Day {nxt.day_number} "
                    f"call is {fmt_time(call_t)}: {rest:.1f}h, below the {TURNAROUND_HOURS}h minimum.",
                    fix=f"Push the call to {fmt_time((wrap + timedelta(hours=TURNAROUND_HOURS)).time())} or later, "
                    "move their scenes later in the day, or budget the penalty.",
                    sources=[s for s in [(prev_sheet or prev).source, (sheet or nxt).source] if s],
                )


def minors(prod: Production, today: date) -> Iterator[Issue]:
    """Minor on an upcoming day without a finished work permit, or working late."""
    flagged_permit: set[str] = set()
    for day in [d for d in prod.days if d.date >= today]:
        for cast_id in prod.day_cast(day):
            member = prod.cast_member(cast_id)
            if not member or not member.minor:
                continue
            permit = [i for i in prod.checklist if i.cast_id == cast_id and PAPERWORK.search(i.task)]
            not_done = [i for i in permit if i.status != Status.done]
            soon = day.date <= today + timedelta(days=LOOKAHEAD_DAYS)
            if cast_id not in flagged_permit and soon and (not permit or not_done):
                flagged_permit.add(cast_id)
                item = not_done[0] if not_done else None
                yield Issue(
                    code="MINOR_PERMIT",
                    severity=Severity.critical,
                    date=day.date,
                    title=f"Work permit not done for minor {_cast_name(prod, cast_id)}",
                    detail=f"Working Day {day.day_number} ({day.date:%a %b %d}). "
                    + (
                        f"Checklist {item.id} is '{item.status.value}' ({item.notes or 'no notes'})."
                        if item
                        else "No permit task exists on the checklist."
                    ),
                    fix="Get the permit issued before the shoot day, or reschedule the minor's scenes.",
                    sources=[day.source] + ([item.source] if item else []),
                )
            night = [
                n
                for n in day.scene_numbers
                if (s := prod.scene(n)) and cast_id in s.cast_ids and s.day_night == "NIGHT"
            ]
            if night or day.est_wrap > MINOR_LATEST_WRAP:
                yield Issue(
                    code="MINOR_HOURS",
                    severity=Severity.warning,
                    date=day.date,
                    title=f"Check minor hours: {_cast_name(prod, cast_id)} on Day {day.day_number}",
                    detail=(f"Night scene(s) {', '.join(night)}; " if night else "")
                    + f"day wraps {fmt_time(day.est_wrap)} (est.).",
                    fix="Confirm the minor's latest finish and on-set hours with the guardian/tutor and the "
                    "applicable rules; shoot their night work first.",
                    sources=[day.source],
                )


# ---- locations ------------------------------------------------------------------


def location_paperwork(prod: Production, today: date) -> Iterator[Issue]:
    """Shooting at a permit location soon, but its agreement/permit isn't done."""
    for day in _upcoming(prod, today):
        for loc_id in prod.day_locations(day):
            loc = prod.location(loc_id)
            if not loc or not loc.permit_required:
                continue
            items = [
                i for i in prod.checklist if i.location_id == loc_id and PAPERWORK.search(i.task) and i.due <= day.date
            ]
            open_items = [i for i in items if i.status != Status.done]
            if open_items or not items:
                detail = (
                    "; ".join(
                        f"{i.id} '{i.task}' is {i.status.value}" + (f" ({i.notes})" if i.notes else "")
                        for i in open_items
                    )
                    or "No agreement or permit task exists for this location."
                )
                yield Issue(
                    code="PERMIT_NOT_READY",
                    severity=Severity.critical,
                    date=day.date,
                    title=f"{loc.name}: paperwork not done for Day {day.day_number} ({day.date:%a %b %d})",
                    detail=detail,
                    fix="Escalate to the locations manager today; have a cover set ready if it isn't signed "
                    "by end of day before.",
                    sources=[day.source, loc.source] + [i.source for i in open_items],
                )


# ---- call sheets ------------------------------------------------------------------


def call_sheet_vs_schedule(prod: Production, today: date) -> Iterator[Issue]:
    for sheet in prod.call_sheets:
        if sheet.date < today:
            continue
        day = prod.day_on(sheet.date)
        if not day:
            yield Issue(
                code="CALL_SHEET_MISMATCH",
                severity=Severity.warning,
                date=sheet.date,
                title=f"Call sheet for {sheet.date:%b %d} has no shoot day on the schedule",
                detail="The schedule has no shoot day on this date.",
                fix="Check the date on the call sheet.",
                sources=[sheet.source],
            )
            continue
        extra = [n for n in sheet.scene_numbers if n not in day.scene_numbers]
        missing = [n for n in day.scene_numbers if n not in sheet.scene_numbers]
        called = {c.cast_id for c in sheet.cast_calls}
        needed = set(prod.day_cast(day))
        for n in extra:  # cast for an extra scene must be called too
            needed |= set(s.cast_ids) if (s := prod.scene(n)) else set()
        not_called = sorted(needed - called)
        if extra or missing or not_called:
            parts = []
            for n in extra:
                other = next((d for d in prod.days if n in d.scene_numbers), None)
                parts.append(
                    f"sc. {n} is on the call sheet but scheduled "
                    + (f"on Day {other.day_number} ({other.date:%b %d})" if other else "on no day")
                )
            parts += [f"sc. {n} is scheduled but missing from the call sheet" for n in missing]
            if not_called:
                parts.append("not called: " + ", ".join(_cast_name(prod, c) for c in not_called))
            yield Issue(
                code="CALL_SHEET_MISMATCH",
                severity=Severity.warning,
                date=sheet.date,
                title=f"Day {sheet.day_number} call sheet doesn't match the schedule",
                detail="; ".join(parts) + ".",
                fix="Confirm with the 1st AD which is right, then reissue the call sheet before it goes out.",
                sources=[sheet.source, day.source],
            )


def call_sheet_safety(prod: Production, today: date) -> Iterator[Issue]:
    for sheet in prod.call_sheets:
        if sheet.date < today:
            continue
        missing = []
        if not sheet.nearest_hospital:
            missing.append("nearest hospital")
        exteriors = [n for n in sheet.scene_numbers if (s := prod.scene(n)) and s.int_ext != "INT"]
        if exteriors and not sheet.weather:
            missing.append("weather (exterior scenes)")
        if exteriors and not sheet.sunset:
            missing.append("sunset time (exterior scenes)")
        if missing:
            hospitals = [
                loc.nearest_hospital for i in sheet.location_ids if (loc := prod.location(i)) and loc.nearest_hospital
            ]
            yield Issue(
                code="MISSING_SAFETY_INFO",
                severity=Severity.warning,
                date=sheet.date,
                title=f"Day {sheet.day_number} call sheet is missing safety info",
                detail="Missing: "
                + ", ".join(missing)
                + "."
                + (
                    f" Location file lists: {'; '.join(hospitals)}." if hospitals and not sheet.nearest_hospital else ""
                ),
                fix="Add it before the call sheet is distributed.",
                sources=[sheet.source] + [loc.source for i in sheet.location_ids if (loc := prod.location(i))],
            )


def missing_call_sheet(prod: Production, today: date) -> Iterator[Issue]:
    nxt = next((d for d in prod.days if d.date > today), None)
    if nxt and not prod.call_sheet_on(nxt.date):
        yield Issue(
            code="MISSING_CALL_SHEET",
            severity=Severity.warning,
            date=nxt.date,
            title=f"No call sheet yet for Day {nxt.day_number} ({nxt.date:%a %b %d})",
            detail="The next shoot day has no call sheet loaded.",
            fix="Generate a draft from the schedule (Documents tab) and send it for review.",
            sources=[nxt.source],
        )


# ---- schedule ---------------------------------------------------------------------


def schedule_load(prod: Production, today: date) -> Iterator[Issue]:
    for day in [d for d in prod.days if d.date >= today]:
        eighths = prod.day_pages_eighths(day)
        if eighths > MAX_PAGES_EIGHTHS:
            whole, rest = divmod(eighths, 8)
            yield Issue(
                code="OVERLOADED_DAY",
                severity=Severity.warning,
                date=day.date,
                title=f"Day {day.day_number} is {whole} {rest}/8 pages",
                detail=f"{len(day.scene_numbers)} scenes, above the {MAX_PAGES_EIGHTHS // 8}-page target.",
                fix="Move a scene to a lighter day or plan for overtime.",
                sources=[day.source],
            )
        locs = prod.day_locations(day)
        if len(locs) > 1:
            names = [loc.name for i in locs if (loc := prod.location(i))]
            yield Issue(
                code="COMPANY_MOVE",
                severity=Severity.info,
                date=day.date,
                title=f"Day {day.day_number}: company move ({' to '.join(names)})",
                detail="Moving the unit mid-day usually costs 1 to 2 hours.",
                fix="Make sure transport, parking and the move time are on the call sheet.",
                sources=[day.source],
            )


# ---- checklist --------------------------------------------------------------------


def checklist(prod: Production, today: date) -> Iterator[Issue]:
    for item in prod.checklist:
        if item.status == Status.done:
            continue
        if item.due < today:
            yield Issue(
                code="OVERDUE_TASK",
                severity=Severity.warning,
                date=item.due,
                title=f"Overdue: {item.task}",
                detail=f"{item.id} was due {item.due:%b %d} ({(today - item.due).days} days ago), "
                f"status {item.status.value}, owner {item.owner or 'nobody'}.",
                fix="Chase the owner for a new date, or escalate.",
                sources=[item.source],
            )
        blockers = [b for dep in item.depends_on if (b := prod.checklist_item(dep)) and b.status != Status.done]
        if blockers:
            yield Issue(
                code="BLOCKED_TASK",
                severity=Severity.warning,
                date=item.due,
                title=f"Blocked: {item.task}",
                detail=f"{item.id} (due {item.due:%b %d}) waits on "
                + ", ".join(f"{b.id} '{b.task}' ({b.status.value}, {b.owner or 'no owner'})" for b in blockers)
                + ".",
                fix=f"Unblock {blockers[0].id} first.",
                sources=[item.source] + [b.source for b in blockers],
            )
        if not item.owner:
            yield Issue(
                code="NO_OWNER",
                severity=Severity.info,
                date=item.due,
                title=f"No owner: {item.task}",
                detail=f"{item.id} is due {item.due:%b %d} and nobody owns it.",
                fix="Assign an owner at the next production meeting.",
                sources=[item.source],
            )


RULES: list[Rule] = [
    turnaround,
    minors,
    location_paperwork,
    call_sheet_vs_schedule,
    call_sheet_safety,
    missing_call_sheet,
    schedule_load,
    checklist,
]

_ORDER = {Severity.critical: 0, Severity.warning: 1, Severity.info: 2}


def find_issues(prod: Production, today: date) -> list[Issue]:
    issues = [issue for rule in RULES for issue in rule(prod, today)]
    return sorted(issues, key=lambda i: (_ORDER[i.severity], i.date or date.max, i.code))
