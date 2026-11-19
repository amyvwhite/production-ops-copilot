"""Generate documents from the production data: a call-sheet draft for any shoot day.

Deterministic on purpose: a call sheet is a legal/safety document, so every value comes
from the schedule, cast list and location file, never from a model. If a value isn't
known, the draft says "TBC" in red instead of guessing. Issues the rules engine found for
that day are printed in a box at the top so they're fixed before the sheet goes out.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from app.loader import fmt_time
from app.models import CallSheet, CastCall, Production, pages_str
from app.rules import find_issues

PICKUP_BEFORE = timedelta(minutes=75)
HMU_BEFORE = timedelta(minutes=45)
FIRST_SHOT_AFTER_CREW_CALL = timedelta(hours=1)

_env = Environment(loader=PackageLoader("app", "templates"), autoescape=select_autoescape(["html"]))
_env.filters["t"] = fmt_time


def _minus(t: time, delta: timedelta) -> time:
    return (datetime.combine(date(2000, 1, 2), t) - delta).time()


def draft_call_sheet(prod: Production, day_date: date) -> CallSheet:
    """The issued call sheet if there is one, otherwise a draft built from the schedule."""
    if existing := prod.call_sheet_on(day_date):
        return existing
    day = prod.day_on(day_date)
    if not day:
        raise ValueError(f"No shoot day on {day_date}")
    shooting = _minus(day.crew_call, -FIRST_SHOT_AFTER_CREW_CALL)
    locs = prod.day_locations(day)
    first_loc = prod.location(locs[0]) if locs else None
    return CallSheet(
        date=day.date,
        day_number=day.day_number,
        crew_call=day.crew_call,
        shooting_call=shooting,
        est_wrap=day.est_wrap,
        location_ids=locs,
        scene_numbers=day.scene_numbers,
        nearest_hospital=first_loc.nearest_hospital if first_loc else None,
        cast_calls=[
            CastCall(
                cast_id=c, pickup=_minus(shooting, PICKUP_BEFORE), hmu=_minus(shooting, HMU_BEFORE), on_set=shooting
            )
            for c in prod.day_cast(day)
        ],
        notes=day.notes,
        source=f"DRAFT generated from {day.source}",
    )


def render_call_sheet(prod: Production, day_date: date, today: date, flags: bool = True) -> str:
    sheet = draft_call_sheet(prod, day_date)
    day = prod.day_on(day_date)
    is_draft = sheet.source.startswith("DRAFT")
    scenes: list[dict[str, Any]] = []
    for n in sheet.scene_numbers:
        s = prod.scene(n)
        scenes.append(
            {
                "number": n,
                "set": f"{s.int_ext}. {s.set_name}" if s else "UNKNOWN SCENE",
                "dn": s.day_night if s else "",
                "pages": s.pages if s else "",
                "cast": ", ".join(s.cast_ids) if s else "",
                "location": (loc.name if s and (loc := prod.location(s.location_id)) else ""),
                "synopsis": s.synopsis if s else "",
            }
        )
    eighths = sum(sc.pages_eighths for n in sheet.scene_numbers if (sc := prod.scene(n)))
    return _env.get_template("call_sheet.html").render(
        prod=prod,
        sheet=sheet,
        day=day,
        draft=is_draft,
        scenes=scenes,
        total_pages=pages_str(eighths),
        cast=[{"call": c, "member": prod.cast_member(c.cast_id)} for c in sheet.cast_calls],
        locations=[loc for i in sheet.location_ids if (loc := prod.location(i))],
        issues=[i for i in find_issues(prod, today) if i.date == day_date] if flags else [],
        show_tools=flags,
        total_days=len(prod.days),
        next_day=next((d for d in prod.days if d.date > day_date), None),
    )
