"""Web app: FastAPI JSON API + a single-page UI (app/static).

uvicorn app.main:app --reload        # http://localhost:8000
"""

from __future__ import annotations

import csv
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.ai import AIUnavailable, Assistant, Cache, extract_call_sheet, make_assistant
from app.config import PROJECT_ROOT, Settings, get_settings
from app.documents import render_call_sheet
from app.loader import demo_today, fmt_time, load_production
from app.models import Production, Status, pages_str
from app.rules import find_issues

log = logging.getLogger(__name__)
STATIC = PROJECT_ROOT / "app" / "static"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class State:
    settings: Settings
    prod: Production
    today: date
    assistant: Assistant


state = State()


def reload_state(settings: Settings | None = None) -> None:
    state.settings = settings or get_settings()
    state.prod = load_production(state.settings.data_dir)
    state.today = state.settings.today_override or demo_today(state.settings.data_dir) or date.today()
    state.assistant = make_assistant(state.prod, state.today, state.settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=logging.INFO)
    reload_state()
    yield


app = FastAPI(title="Production Ops Copilot", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    p, today = state.prod, state.today
    issues = find_issues(p, today)
    nxt = next((d for d in p.days if d.date > today), None)
    return {
        "title": p.title,
        "company": p.company,
        "today": today.isoformat(),
        "start": p.start,
        "end": p.end,
        "ai_enabled": state.assistant.model is not None,
        "model": state.settings.gemini_model,
        "next_day": nxt.date.isoformat() if nxt else None,
        "counts": {s: sum(1 for i in issues if i.severity.value == s) for s in ("critical", "warning", "info")},
        "checklist": {s.value: sum(1 for i in p.checklist if i.status == s) for s in Status},
        "days": [
            {
                "day": d.day_number,
                "date": d.date.isoformat(),
                "weekday": f"{d.date:%a}",
                "locations": [loc.name for i in p.day_locations(d) if (loc := p.location(i))],
                "scenes": d.scene_numbers,
                "pages": pages_str(p.day_pages_eighths(d)),
                "crew_call": fmt_time(d.crew_call),
                "est_wrap": fmt_time(d.est_wrap),
                "has_call_sheet": p.call_sheet_on(d.date) is not None,
                "issues": sum(1 for i in issues if i.date == d.date and i.severity.value != "info"),
            }
            for d in p.days
        ],
    }


@app.get("/api/issues")
def issues() -> list[dict[str, Any]]:
    return [i.model_dump(mode="json") for i in find_issues(state.prod, state.today)]


@app.get("/api/checklist")
def checklist() -> list[dict[str, Any]]:
    return [
        i.model_dump(mode="json") for i in sorted(state.prod.checklist, key=lambda i: (i.status == Status.done, i.due))
    ]


class StatusUpdate(BaseModel):
    status: Status


@app.patch("/api/checklist/{item_id}")
def update_item(item_id: str, body: StatusUpdate) -> dict[str, Any]:
    item = state.prod.checklist_item(item_id)
    if not item:
        raise HTTPException(404, f"No checklist item {item_id}")
    item.status = body.status
    _save_checklist()
    state.assistant = make_assistant(state.prod, state.today, state.settings)  # data changed: new cache version
    return item.model_dump(mode="json")


def _save_checklist() -> None:
    path = state.settings.data_dir / "checklist.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "id",
                "phase",
                "department",
                "task",
                "owner",
                "due",
                "status",
                "depends_on",
                "location_id",
                "cast_id",
                "notes",
            ]
        )
        for i in state.prod.checklist:
            w.writerow(
                [
                    i.id,
                    i.phase,
                    i.department,
                    i.task,
                    i.owner or "",
                    i.due.isoformat(),
                    i.status.value,
                    ",".join(i.depends_on),
                    i.location_id or "",
                    i.cast_id or "",
                    i.notes,
                ]
            )


@app.get("/api/briefing")
def briefing(day: date | None = None) -> dict[str, Any]:
    target = day or next((d.date for d in state.prod.days if d.date > state.today), state.today + timedelta(days=1))
    return state.assistant.briefing(target)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@app.post("/api/ask")
def ask(q: Question) -> dict[str, Any]:
    try:
        return state.assistant.ask(q.question).__dict__
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/documents/call-sheet/{day}", response_class=HTMLResponse)
def call_sheet(day: date) -> str:
    try:
        return render_call_sheet(state.prod, day, state.today)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/call-sheets/upload")
async def upload_call_sheet(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a PDF call sheet.")
    pdf = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(pdf) > MAX_UPLOAD_BYTES or not pdf.startswith(b"%PDF"):
        raise HTTPException(400, "Not a PDF, or larger than 5 MB.")
    try:
        sheet = extract_call_sheet(pdf, state.assistant.model, Cache(state.settings.cache_dir), file.filename or "")
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:  # the model returned something that doesn't validate
        raise HTTPException(422, f"Couldn't read a valid call sheet from that PDF: {exc}") from exc
    state.prod.call_sheets = [s for s in state.prod.call_sheets if s.date != sheet.date] + [sheet]
    state.assistant = make_assistant(state.prod, state.today, state.settings)
    new = [i.model_dump(mode="json") for i in find_issues(state.prod, state.today) if i.date == sheet.date]
    return {"call_sheet": sheet.model_dump(mode="json"), "issues_for_day": new}
