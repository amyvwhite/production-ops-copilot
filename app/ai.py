"""The AI layer: question answering with citations, daily briefings, and PDF call-sheet
extraction, on Google Gemini (free tier by default).

Design (docs/adr/0002-grounded-answers.md):

* **Grounded, not generative.** The model never sees "the whole production" in a prompt.
  It must call tools (functions below) that return records, and it must cite each fact
  with the record's source id, e.g. [schedule.csv#day-3]. Citations are checked: the app
  shows which ones came from real tool results and flags any that didn't.
* **The tool loop lives here, not in the SDK,** behind a tiny ``ChatModel`` interface. The
  real implementation talks to Gemini; tests use a scripted fake, so CI never calls the
  API and costs nothing.
* **Free-tier guardrails.** Responses are cached on disk (same question + same data = no
  new call), there's a per-day call cap, and every failure degrades to a non-AI answer
  instead of an error page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from app.config import Settings
from app.loader import fmt_time
from app.models import CallSheet, Production, pages_str
from app.rules import find_issues

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6
CITATION = re.compile(r"\[([A-Za-z0-9_.\-]+(?:#[A-Za-z0-9_.\-]+)?)\]")


class AIUnavailable(RuntimeError):
    """No key, over the daily cap, or the API failed. Callers fall back to non-AI output."""


# ---- the model interface -------------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class ModelTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    fn: Callable[..., Any]


class ChatModel(Protocol):
    def respond(self, system: str, history: list[dict[str, Any]], tools: list[ToolSpec]) -> ModelTurn: ...

    def extract(self, system: str, pdf: bytes, schema: type) -> dict[str, Any]: ...


# ---- Gemini implementation -----------------------------------------------------------


class GeminiChat:
    """ChatModel on the google-genai SDK. History items are our own simple dicts."""

    def __init__(self, settings: Settings) -> None:
        if not settings.ai_enabled:
            raise AIUnavailable("GEMINI_API_KEY is not set: AI features are off, rules and documents still work.")
        from google import genai

        self._genai = genai
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model
        self.budget = DailyBudget(settings.cache_dir / "ai_calls.json", settings.max_ai_calls_per_day)

    def _contents(self, history: list[dict[str, Any]]) -> list[Any]:
        t = self._genai.types
        out = []
        for h in history:
            if h["role"] == "user":
                out.append(t.Content(role="user", parts=[t.Part.from_text(text=h["text"])]))
            elif h["role"] == "model":
                parts = [t.Part.from_text(text=h["text"])] if h.get("text") else []
                parts += [t.Part(function_call=t.FunctionCall(name=c.name, args=c.args)) for c in h["tool_calls"]]
                out.append(t.Content(role="model", parts=parts))
            elif h["role"] == "tool":
                out.append(
                    t.Content(
                        role="user",
                        parts=[
                            t.Part.from_function_response(name=r["name"], response={"result": r["result"]})
                            for r in h["results"]
                        ],
                    )
                )
        return out

    def _call(self, **kwargs: Any) -> Any:
        self.budget.spend()
        from google.genai import errors

        try:
            return self.client.models.generate_content(model=self.model, **kwargs)
        except errors.ClientError as exc:
            if getattr(exc, "code", None) == 429:
                raise AIUnavailable("Gemini free-tier rate limit reached; try again in a minute.") from exc
            raise AIUnavailable(f"Gemini rejected the request: {exc}") from exc
        except errors.APIError as exc:
            raise AIUnavailable(f"Gemini is unavailable: {exc}") from exc

    def respond(self, system: str, history: list[dict[str, Any]], tools: list[ToolSpec]) -> ModelTurn:
        t = self._genai.types
        config = t.GenerateContentConfig(
            system_instruction=system,
            temperature=0.1,
            tools=[
                t.Tool(
                    function_declarations=[
                        t.FunctionDeclaration(
                            name=s.name, description=s.description, parameters_json_schema=s.parameters
                        )
                        for s in tools
                    ]
                )
            ]
            if tools
            else None,
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = self._call(contents=self._contents(history), config=config)
        calls = [ToolCall(name=c.name or "", args=dict(c.args or {})) for c in (resp.function_calls or [])]
        return ModelTurn(text=(resp.text or "") if not calls else "", tool_calls=calls)

    def extract(self, system: str, pdf: bytes, schema: type) -> dict[str, Any]:
        t = self._genai.types
        resp = self._call(
            contents=[t.Part.from_bytes(data=pdf, mime_type="application/pdf"), "Extract the call sheet."],
            config=t.GenerateContentConfig(
                system_instruction=system, temperature=0, response_mime_type="application/json", response_schema=schema
            ),
        )
        return json.loads(resp.text or "{}")


class DailyBudget:
    """Counts AI calls per UTC day in a small JSON file and refuses past the cap."""

    def __init__(self, path: Path, cap: int) -> None:
        self.path, self.cap = path, cap

    def spend(self) -> None:
        today = datetime.now(UTC).date().isoformat()
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        used = data.get(today, 0)
        if used >= self.cap:
            raise AIUnavailable(f"Daily AI call cap reached ({self.cap}); set MAX_AI_CALLS_PER_DAY to change it.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({today: used + 1}))


class Cache:
    """Disk cache for AI results, keyed by everything that affects the answer."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    @staticmethod
    def key(*parts: Any) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.folder / f"{key}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{key}.json").write_text(json.dumps(value, default=str), encoding="utf-8")


# ---- tools the model can call ------------------------------------------------------------


def data_version(prod: Production) -> str:
    """Changes whenever the production data changes, so cached answers expire with it."""
    return Cache.key(prod.model_dump(exclude={"loaded_at"}))


def build_tools(prod: Production, today: date) -> list[ToolSpec]:
    def scene_dict(n: str) -> dict[str, Any]:
        s = prod.scene(n)
        if not s:
            return {"scene": n, "error": "unknown scene"}
        loc = prod.location(s.location_id)
        return {
            "scene": s.number,
            "set": f"{s.int_ext}. {s.set_name} - {s.day_night}",
            "pages": s.pages,
            "cast": [f"{c} {m.name}" for c in s.cast_ids if (m := prod.cast_member(c))],
            "location": loc.name if loc else s.location_id,
            "synopsis": s.synopsis,
            "source": s.source,
        }

    def get_day(day_number: int = 0, date_iso: str = "") -> dict[str, Any]:
        day = next((d for d in prod.days if d.day_number == day_number), None) if day_number else None
        if date_iso:
            day = prod.day_on(date.fromisoformat(date_iso))
        if not day:
            return {"error": "no shoot day found", "shoot_days": [f"Day {d.day_number} {d.date}" for d in prod.days]}
        sheet = prod.call_sheet_on(day.date)
        out: dict[str, Any] = {
            "day": day.day_number,
            "date": day.date.isoformat(),
            "weekday": f"{day.date:%A}",
            "crew_call": fmt_time(day.crew_call),
            "est_wrap": fmt_time(day.est_wrap),
            "notes": day.notes,
            "locations": [loc.name for i in prod.day_locations(day) if (loc := prod.location(i))],
            "scenes": [scene_dict(n) for n in day.scene_numbers],
            "source": day.source,
        }
        if sheet:
            out["call_sheet"] = {
                "source": sheet.source,
                "shooting_call": fmt_time(sheet.shooting_call),
                "weather": sheet.weather,
                "sunset": fmt_time(sheet.sunset),
                "nearest_hospital": sheet.nearest_hospital,
                "notes": sheet.notes,
                "cast_calls": [
                    {
                        "cast": f"{c.cast_id} {m.name if (m := prod.cast_member(c.cast_id)) else ''}",
                        "pickup": fmt_time(c.pickup),
                        "hmu": fmt_time(c.hmu),
                        "on_set": fmt_time(c.on_set),
                    }
                    for c in sheet.cast_calls
                ],
            }
        return out

    def find_scenes(text: str) -> dict[str, Any]:
        q = text.lower()
        hits = []
        for s in prod.scenes:
            loc = prod.location(s.location_id)
            names = " ".join(m.name + " " + m.role for c in s.cast_ids if (m := prod.cast_member(c)))
            hay = f"{s.number} {s.set_name} {s.synopsis} {loc.name if loc else ''} {names}".lower()
            if all(re.search(rf"\b{re.escape(word)}", hay) for word in q.split()):
                day = next((d for d in prod.days if s.number in d.scene_numbers), None)
                hits.append(
                    {
                        **scene_dict(s.number),
                        "day": day.day_number if day else None,
                        "date": day.date.isoformat() if day else None,
                    }
                )
        return {"matches": hits[:15], "count": len(hits)}

    def get_checklist(status: str = "", department: str = "", owner: str = "", due_before: str = "") -> dict[str, Any]:
        items = prod.checklist
        if status:
            items = [i for i in items if i.status.value == status]
        if department:
            items = [i for i in items if department.lower() in i.department.lower()]
        if owner:
            items = [i for i in items if i.owner and owner.lower() in i.owner.lower()]
        if due_before:
            items = [i for i in items if i.due <= date.fromisoformat(due_before)]
        return {"items": [i.model_dump(mode="json") for i in items], "count": len(items)}

    def get_issues(severity: str = "", on_date: str = "") -> dict[str, Any]:
        issues = find_issues(prod, today)
        if severity:
            issues = [i for i in issues if i.severity.value == severity]
        if on_date:
            issues = [i for i in issues if i.date and i.date.isoformat() == on_date]
        return {"issues": [i.model_dump(mode="json") for i in issues], "count": len(issues)}

    def get_person_or_place(name: str) -> dict[str, Any]:
        q = name.lower()
        cast = [c for c in prod.cast if q in c.name.lower() or q in c.role.lower() or q == c.id]
        locs = [loc for loc in prod.locations if q in loc.name.lower() or q in loc.address.lower()]
        out: dict[str, Any] = {"cast": [], "locations": []}
        for c in cast:
            working = [f"Day {d.day_number} {d.date}" for d in prod.days if c.id in prod.day_cast(d)]
            out["cast"].append({**c.model_dump(mode="json"), "working_days": working})
        for loc in locs:
            used = [f"Day {d.day_number} {d.date}" for d in prod.days if loc.id in prod.day_locations(d)]
            out["locations"].append({**loc.model_dump(mode="json"), "shoot_days": used})
        return out

    s = {"type": "string"}
    return [
        ToolSpec(
            "get_day",
            "Schedule, scenes, cast and call sheet for one shoot day (by day number or date).",
            {
                "type": "object",
                "properties": {"day_number": {"type": "integer"}, "date_iso": {**s, "description": "YYYY-MM-DD"}},
            },
            get_day,
        ),
        ToolSpec(
            "find_scenes",
            "Search scenes by words in set, synopsis, location, cast name or role.",
            {"type": "object", "properties": {"text": s}, "required": ["text"]},
            find_scenes,
        ),
        ToolSpec(
            "get_checklist",
            "Production checklist items, optionally filtered.",
            {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "in_progress", "done"]},
                    "department": s,
                    "owner": s,
                    "due_before": {**s, "description": "YYYY-MM-DD"},
                },
            },
            get_checklist,
        ),
        ToolSpec(
            "get_issues",
            "Problems found by the production rules engine (turnaround, permits, ...).",
            {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                    "on_date": {**s, "description": "YYYY-MM-DD"},
                },
            },
            get_issues,
        ),
        ToolSpec(
            "get_person_or_place",
            "Look up a cast member (name, role or cast number) or a location.",
            {"type": "object", "properties": {"name": s}, "required": ["name"]},
            get_person_or_place,
        ),
    ]


# ---- features -----------------------------------------------------------------------------


@dataclass
class Answer:
    text: str
    citations: list[str]
    unverified_citations: list[str]
    tools_used: list[str]
    cached: bool = False
    ai: bool = True


def _sources_in(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("source", "sources"):
                found |= {v} if isinstance(v, str) else set(v or [])
            else:
                found |= _sources_in(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= _sources_in(v)
    return found


def system_prompt(prod: Production, today: date) -> str:
    return (
        f"You are the production office assistant for '{prod.title}' ({prod.company}). Today is "
        f"{today:%A %B %d, %Y}. Shoot days run {prod.start} to {prod.end}.\n"
        "Rules:\n"
        "1. Use the tools to look things up. Never answer from memory or guess dates, times or names.\n"
        "2. After every fact, cite the record it came from with its source id in square brackets, exactly as "
        "the tool returned it, e.g. [schedule.csv#day-3] or [call_sheet_2026-11-25.pdf].\n"
        "3. If the tools don't have the answer, say so plainly.\n"
        "4. Be brief and practical, like a production coordinator: lead with the answer, then details. "
        "Use 24-hour times as given."
    )


class Assistant:
    def __init__(self, prod: Production, today: date, model: ChatModel | None, cache: Cache) -> None:
        self.prod, self.today, self.model, self.cache = prod, today, model, cache
        self.tools = build_tools(prod, today)
        self.version = data_version(prod)

    def ask(self, question: str) -> Answer:
        question = question.strip()[:1000]
        key = Cache.key("ask", self.version, self.today, question.lower())
        if hit := self.cache.get(key):
            return Answer(**{**hit, "cached": True})
        if self.model is None:
            raise AIUnavailable("GEMINI_API_KEY is not set: AI answers are off.")
        by_name = {t.name: t for t in self.tools}
        history: list[dict[str, Any]] = [{"role": "user", "text": question}]
        seen_sources: set[str] = set()
        used: list[str] = []
        for _ in range(MAX_TOOL_ROUNDS):
            turn = self.model.respond(system_prompt(self.prod, self.today), history, self.tools)
            if not turn.tool_calls:
                cited = list(dict.fromkeys(CITATION.findall(turn.text)))
                answer = Answer(
                    text=turn.text.strip(),
                    citations=[c for c in cited if c in seen_sources],
                    unverified_citations=[c for c in cited if c not in seen_sources],
                    tools_used=used,
                )
                self.cache.put(key, answer.__dict__)
                return answer
            history.append({"role": "model", "text": turn.text, "tool_calls": turn.tool_calls})
            results = []
            for call in turn.tool_calls:
                tool = by_name.get(call.name)
                try:
                    result = tool.fn(**call.args) if tool else {"error": f"unknown tool {call.name}"}
                except (TypeError, ValueError) as exc:  # bad arguments from the model
                    result = {"error": str(exc)}
                seen_sources |= _sources_in(result)
                used.append(call.name)
                results.append({"name": call.name, "result": result})
            history.append({"role": "tool", "results": results})
        raise AIUnavailable("The assistant needed too many lookups for this question; try asking more narrowly.")

    def briefing(self, day: date) -> dict[str, Any]:
        """Facts are computed in code; the model only turns them into a short readable brief."""
        facts = briefing_facts(self.prod, self.today, day)
        out = {"facts": facts, "text": fallback_briefing(facts), "ai": False, "cached": False}
        if self.model is None:
            return out
        key = Cache.key("brief", self.version, self.today, day)
        if hit := self.cache.get(key):
            return {**out, "text": hit["text"], "ai": True, "cached": True}
        prompt = (
            "Write the morning production brief for the day below for department heads: 5 to 8 short bullet "
            "points, most urgent first. Use only these facts and keep every time exactly as given. End each "
            "bullet that comes from an issue with its source ids in square brackets.\n\n"
            + json.dumps(facts, indent=1, default=str)
        )
        try:
            turn = self.model.respond(system_prompt(self.prod, self.today), [{"role": "user", "text": prompt}], [])
        except AIUnavailable as exc:
            return {**out, "note": str(exc)}
        self.cache.put(key, {"text": turn.text.strip()})
        return {**out, "text": turn.text.strip(), "ai": True}


def briefing_facts(prod: Production, today: date, day: date) -> dict[str, Any]:
    shoot = prod.day_on(day)
    issues = find_issues(prod, today)
    facts: dict[str, Any] = {
        "date": day.isoformat(),
        "weekday": f"{day:%A}",
        "shoot_day": None,
        "issues_for_day": [],
        "other_critical": [],
    }
    if shoot:
        sheet = prod.call_sheet_on(day)
        facts["shoot_day"] = {
            "day": shoot.day_number,
            "crew_call": fmt_time(shoot.crew_call),
            "est_wrap": fmt_time((sheet or shoot).est_wrap),
            "notes": shoot.notes,
            "locations": [loc.name for i in prod.day_locations(shoot) if (loc := prod.location(i))],
            "scenes": [f"{n} {s.set_name} ({s.pages} pgs)" for n in shoot.scene_numbers if (s := prod.scene(n))],
            "pages": pages_str(prod.day_pages_eighths(shoot)),
            "weather": sheet.weather if sheet else None,
            "sunset": fmt_time(sheet.sunset) if sheet else None,
            "call_sheet": sheet.source if sheet else None,
        }
    facts["issues_for_day"] = [
        {"severity": i.severity.value, "title": i.title, "fix": i.fix, "sources": i.sources}
        for i in issues
        if i.date == day
    ]
    facts["other_critical"] = [
        {"title": i.title, "date": str(i.date), "sources": i.sources}
        for i in issues
        if i.severity.value == "critical" and i.date != day
    ]
    due = [i for i in prod.checklist if i.due == day and i.status.value != "done"]
    facts["checklist_due"] = [f"{i.id} {i.task} ({i.owner or 'no owner'})" for i in due]
    return facts


def fallback_briefing(facts: dict[str, Any]) -> str:
    """The same brief without AI: plain bullet points."""
    lines = []
    s = facts.get("shoot_day")
    if s:
        lines.append(
            f"- Day {s['day']} at {', '.join(s['locations'])}: crew call {s['crew_call']}, "
            f"est. wrap {s['est_wrap']}, {s['pages']} pages."
        )
        if s.get("weather"):
            lines.append(f"- Weather: {s['weather']}; sunset {s['sunset']}.")
        if s.get("notes"):
            lines.append(f"- Note: {s['notes']}")
    else:
        lines.append(f"- No shoot on {facts['weekday']} {facts['date']}.")
    lines += [f"- {i['severity'].upper()}: {i['title']}. {i['fix']}" for i in facts["issues_for_day"]]
    lines += [f"- Coming up: {i['title']} ({i['date']})" for i in facts["other_critical"][:4]]
    lines += [f"- Checklist due that day: {t}" for t in facts.get("checklist_due", [])]
    return "\n".join(lines)


class _CastCallText(BaseModel):
    cast_id: str
    pickup: str | None = None
    hmu: str | None = None
    on_set: str


class _CrewCallText(BaseModel):
    department: str
    call: str


class CallSheetText(BaseModel):
    """What the model fills in: plain strings (HH:MM, YYYY-MM-DD). Validated into CallSheet after."""

    date: str
    day_number: int
    crew_call: str
    shooting_call: str
    est_wrap: str
    weather: str | None = None
    sunrise: str | None = None
    sunset: str | None = None
    location_ids: list[str]
    nearest_hospital: str | None = None
    scene_numbers: list[str]
    cast_calls: list[_CastCallText]
    crew_calls: list[_CrewCallText] = []
    notes: str = ""


EXTRACT_SYSTEM = (
    "You read film/TV call sheets. Extract exactly what is printed; use null for anything missing. Times "
    "are 24-hour HH:MM. Cast are listed by cast number. Location ids look like L1, L2 (use the id printed "
    "next to the location). Never invent scenes, people or times."
)


def extract_call_sheet(pdf: bytes, model: ChatModel | None, cache: Cache, filename: str) -> CallSheet:
    """PDF call sheet -> validated CallSheet (Gemini structured output, cached by file hash)."""
    key = Cache.key("extract", hashlib.sha256(pdf).hexdigest())
    data = cache.get(key)
    if data is None:
        if model is None:
            raise AIUnavailable("Reading PDF call sheets needs GEMINI_API_KEY.")
        data = model.extract(EXTRACT_SYSTEM, pdf, CallSheetText)
        cache.put(key, data)
    data["source"] = filename
    return CallSheet(**data)


def make_assistant(prod: Production, today: date, settings: Settings) -> Assistant:
    try:
        model: ChatModel | None = GeminiChat(settings)
    except AIUnavailable:
        model = None
    return Assistant(prod, today, model, Cache(settings.cache_dir))
