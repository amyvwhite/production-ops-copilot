"""Load a production from a folder of plain files (CSV + call-sheet JSON).

The folder layout is the "contract" between a production office's exports and the app:

    production.json          title, company, start, end (optional demo_today)
    cast.csv  locations.csv  scenes.csv  schedule.csv  checklist.csv
    call_sheets/*.json       one per day (PDF call sheets are converted by app.extract)

Every row is validated by the Pydantic models, so a bad export fails loudly with the file
and row, instead of producing wrong answers later.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from app.models import CallSheet, CastMember, ChecklistItem, Location, Production, Scene, ShootDay


class LoadError(ValueError):
    pass


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def _ids(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _bool(value: str) -> bool:
    return value.strip().lower() in ("true", "yes", "y", "1")


def _build(model: Any, data: dict, where: str) -> Any:
    try:
        return model(**data)
    except Exception as exc:  # pydantic.ValidationError, ValueError
        raise LoadError(f"{where}: {exc}") from exc


def load_production(folder: Path) -> Production:
    folder = Path(folder)
    meta = json.loads((folder / "production.json").read_text(encoding="utf-8"))

    cast = [
        _build(
            CastMember,
            {
                "id": r["id"],
                "name": r["name"],
                "role": r["role"],
                "minor": _bool(r["minor"]),
                "source": f"cast.csv#{r['id']}",
            },
            f"cast.csv row {i}",
        )
        for i, r in enumerate(_rows(folder / "cast.csv"), start=2)
    ]
    locations = [
        _build(
            Location,
            {
                "id": r["id"],
                "name": r["name"],
                "address": r["address"],
                "parking": r["parking"] or None,
                "nearest_hospital": r["nearest_hospital"] or None,
                "permit_required": _bool(r["permit_required"]),
                "source": f"locations.csv#{r['id']}",
            },
            f"locations.csv row {i}",
        )
        for i, r in enumerate(_rows(folder / "locations.csv"), start=2)
    ]
    scenes = [
        _build(
            Scene,
            {
                "number": r["scene"],
                "set_name": r["set_name"],
                "int_ext": r["int_ext"],
                "day_night": r["day_night"],
                "pages_eighths": int(r["pages_eighths"]),
                "cast_ids": _ids(r["cast_ids"]),
                "location_id": r["location_id"],
                "synopsis": r["synopsis"],
                "source": f"scenes.csv#sc-{r['scene']}",
            },
            f"scenes.csv row {i}",
        )
        for i, r in enumerate(_rows(folder / "scenes.csv"), start=2)
    ]
    days = [
        _build(
            ShootDay,
            {
                "day_number": int(r["day"]),
                "date": r["date"],
                "scene_numbers": _ids(r["scenes"]),
                "crew_call": r["crew_call"],
                "est_wrap": r["est_wrap"],
                "notes": r["notes"],
                "source": f"schedule.csv#day-{r['day']}",
            },
            f"schedule.csv row {i}",
        )
        for i, r in enumerate(_rows(folder / "schedule.csv"), start=2)
    ]
    checklist = [
        _build(
            ChecklistItem,
            {
                "id": r["id"],
                "phase": r["phase"],
                "department": r["department"],
                "task": r["task"],
                "owner": r["owner"] or None,
                "due": r["due"],
                "status": r["status"],
                "depends_on": _ids(r["depends_on"]),
                "location_id": r["location_id"] or None,
                "cast_id": r["cast_id"] or None,
                "notes": r["notes"],
                "source": f"checklist.csv#{r['id']}",
            },
            f"checklist.csv row {i}",
        )
        for i, r in enumerate(_rows(folder / "checklist.csv"), start=2)
    ]
    sheets = []
    for path in sorted((folder / "call_sheets").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("source", path.name.replace(".json", ".pdf"))
        sheets.append(_build(CallSheet, data, path.name))

    prod = Production(
        title=meta["title"],
        company=meta["company"],
        start=meta["start"],
        end=meta["end"],
        cast=cast,
        locations=locations,
        scenes=scenes,
        days=sorted(days, key=lambda d: d.date),
        call_sheets=sheets,
        checklist=checklist,
        loaded_at=datetime.now(UTC),
    )
    _check_references(prod)
    return prod


def _check_references(prod: Production) -> None:
    """Fail on dangling ids (a scene at an unknown location, a day with an unknown scene, ...)."""
    loc_ids = {loc.id for loc in prod.locations}
    cast_ids = {c.id for c in prod.cast}
    scene_ids = {s.number for s in prod.scenes}
    item_ids = {i.id for i in prod.checklist}
    problems = []
    for s in prod.scenes:
        if s.location_id not in loc_ids:
            problems.append(f"scene {s.number}: unknown location {s.location_id}")
        problems += [f"scene {s.number}: unknown cast {c}" for c in s.cast_ids if c not in cast_ids]
    for d in prod.days:
        problems += [f"day {d.day_number}: unknown scene {n}" for n in d.scene_numbers if n not in scene_ids]
    for i in prod.checklist:
        problems += [f"{i.id}: depends on unknown {dep}" for dep in i.depends_on if dep not in item_ids]
    if problems:
        raise LoadError("; ".join(problems))


def demo_today(folder: Path) -> date | None:
    meta = json.loads((Path(folder) / "production.json").read_text(encoding="utf-8"))
    return date.fromisoformat(meta["demo_today"]) if meta.get("demo_today") else None


def fmt_time(t: time | None) -> str:
    return t.strftime("%H:%M") if t else "-"
