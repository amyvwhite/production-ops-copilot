"""Domain model for a film/TV production: schedule, call sheets, checklist, issues.

Every record carries a ``source`` (the document it came from, e.g. ``schedule.csv#sc-14``)
so anything the app says, including AI answers, can point back to where it came from.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime, time
from enum import StrEnum

from pydantic import BaseModel, Field


def pages_str(eighths: int) -> str:
    """Script length the way film schedules write it: 4 1/8, 7/8, 2."""
    whole, rest = divmod(eighths, 8)
    if not rest:
        return str(whole)
    return f"{whole} {rest}/8" if whole else f"{rest}/8"


class CastMember(BaseModel):
    id: str = Field(description="Cast number as used on the call sheet, e.g. '1'")
    name: str
    role: str
    minor: bool = False
    source: str = "cast.csv"


class Location(BaseModel):
    id: str
    name: str
    address: str
    parking: str | None = None
    nearest_hospital: str | None = None
    permit_required: bool = False
    source: str = "locations.csv"


class Scene(BaseModel):
    number: str
    set_name: str
    int_ext: str = Field(pattern="^(INT|EXT|INT/EXT)$")
    day_night: str = Field(pattern="^(DAY|NIGHT|DUSK|DAWN)$")
    pages_eighths: int = Field(ge=1, description="Script length in eighths of a page")
    cast_ids: list[str] = []
    location_id: str
    synopsis: str = ""
    source: str = "schedule.csv"

    @property
    def pages(self) -> str:
        return pages_str(self.pages_eighths)


class ShootDay(BaseModel):
    day_number: int
    date: Date
    scene_numbers: list[str]
    crew_call: time
    est_wrap: time
    notes: str = ""
    source: str = "schedule.csv"


class CastCall(BaseModel):
    cast_id: str
    pickup: time | None = None
    hmu: time | None = Field(default=None, description="Hair / makeup / wardrobe call")
    on_set: time


class CrewCall(BaseModel):
    department: str
    call: time


class CallSheet(BaseModel):
    date: Date
    day_number: int
    crew_call: time
    shooting_call: time
    est_wrap: time
    weather: str | None = None
    sunrise: time | None = None
    sunset: time | None = None
    location_ids: list[str]
    nearest_hospital: str | None = None
    scene_numbers: list[str]
    cast_calls: list[CastCall]
    crew_calls: list[CrewCall] = []
    notes: str = ""
    source: str = ""


class Status(StrEnum):
    open = "open"
    in_progress = "in_progress"
    done = "done"


class ChecklistItem(BaseModel):
    id: str
    phase: str = Field(pattern="^(prep|shoot|wrap)$")
    department: str
    task: str
    owner: str | None = None
    due: Date
    status: Status = Status.open
    depends_on: list[str] = []
    location_id: str | None = None
    cast_id: str | None = None
    notes: str = ""
    source: str = "checklist.csv"


class Severity(StrEnum):
    critical = "critical"
    warning = "warning"
    info = "info"


class Issue(BaseModel):
    code: str = Field(description="Stable rule id, e.g. TURNAROUND")
    severity: Severity
    title: str
    detail: str
    fix: str = Field(description="Suggested next action")
    date: Date | None = None
    sources: list[str] = []


class Production(BaseModel):
    """Everything the app knows about one show."""

    title: str
    company: str
    start: Date
    end: Date
    cast: list[CastMember]
    locations: list[Location]
    scenes: list[Scene]
    days: list[ShootDay]
    call_sheets: list[CallSheet] = []
    checklist: list[ChecklistItem] = []
    loaded_at: datetime | None = None

    # ---- lookups ------------------------------------------------------------
    def scene(self, number: str) -> Scene | None:
        return next((s for s in self.scenes if s.number == number), None)

    def location(self, location_id: str) -> Location | None:
        return next((loc for loc in self.locations if loc.id == location_id), None)

    def cast_member(self, cast_id: str) -> CastMember | None:
        return next((c for c in self.cast if c.id == cast_id), None)

    def day_on(self, when: Date) -> ShootDay | None:
        return next((d for d in self.days if d.date == when), None)

    def call_sheet_on(self, when: Date) -> CallSheet | None:
        return next((c for c in self.call_sheets if c.date == when), None)

    def checklist_item(self, item_id: str) -> ChecklistItem | None:
        return next((i for i in self.checklist if i.id == item_id), None)

    def day_locations(self, day: ShootDay) -> list[str]:
        seen: list[str] = []
        for number in day.scene_numbers:
            scene = self.scene(number)
            if scene and scene.location_id not in seen:
                seen.append(scene.location_id)
        return seen

    def day_cast(self, day: ShootDay) -> list[str]:
        cast: list[str] = []
        for number in day.scene_numbers:
            scene = self.scene(number)
            for cid in scene.cast_ids if scene else []:
                if cid not in cast:
                    cast.append(cid)
        return sorted(cast, key=lambda c: (len(c), c))

    def day_pages_eighths(self, day: ShootDay) -> int:
        return sum(s.pages_eighths for n in day.scene_numbers if (s := self.scene(n)))
