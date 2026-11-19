"""Loader validation, documents and the HTTP API (no AI key: the app must still work)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.documents import draft_call_sheet, render_call_sheet
from app.loader import LoadError, load_production
from tests.conftest import TODAY


def test_loader_rejects_dangling_references(data_dir):
    path = data_dir / "scenes.csv"
    path.write_text(path.read_text().replace(",L3,", ",L9,", 1))
    with pytest.raises(LoadError, match="unknown location L9"):
        load_production(data_dir)


def test_loader_reports_the_bad_row(data_dir):
    path = data_dir / "schedule.csv"
    path.write_text(path.read_text().replace("2026-11-25", "25/11/2026"))
    with pytest.raises(LoadError, match=r"schedule\.csv row 4"):
        load_production(data_dir)


def test_draft_call_sheet_from_schedule(prod):
    sheet = draft_call_sheet(prod, date(2026, 11, 30))
    assert sheet.source.startswith("DRAFT") and sheet.nearest_hospital == "St. Brigid General, 2.1 km"
    assert [c.cast_id for c in sheet.cast_calls] == ["1", "2", "3", "4", "6"]
    assert sheet.cast_calls[0].on_set.isoformat() == "08:00:00"


def test_rendered_call_sheet_flags_issues_and_missing_values(prod):
    html = render_call_sheet(prod, date(2026, 11, 26), TODAY)
    assert "TBC - REQUIRED" in html  # no hospital on the Day 4 call sheet
    assert "Fix before this goes out" in html and "Cherry St. Warehouse" in html
    assert "<script" not in html.split("</head>")[1]  # template output is escaped, nothing injected


@pytest.fixture
def client(data_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("PRODOPS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PRODOPS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_overview_and_issues(client):
    o = client.get("/api/overview").json()
    assert o["today"] == "2026-11-24" and o["next_day"] == "2026-11-25" and not o["ai_enabled"]
    assert o["counts"] == {"critical": 7, "warning": 7, "info": 4}
    assert len(client.get("/api/issues").json()) == 18


def test_checklist_update_persists_and_changes_issues(client, data_dir):
    r = client.patch("/api/checklist/CL-01", json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert (
        "CL-01,prep,Locations,Location agreement signed - Cherry St. Warehouse,Sam Ortiz (Locations),2026-11-20,done"
        in (data_dir / "checklist.csv").read_text()
    )
    codes = {i["code"] for i in client.get("/api/issues").json()}
    assert "PERMIT_NOT_READY" not in codes
    assert client.patch("/api/checklist/CL-99", json={"status": "done"}).status_code == 404
    assert client.patch("/api/checklist/CL-02", json={"status": "finished"}).status_code == 422


def test_briefing_without_ai(client):
    b = client.get("/api/briefing").json()
    assert b["facts"]["shoot_day"]["day"] == 3 and not b["ai"]


def test_ask_without_key_is_a_clear_503(client):
    r = client.post("/api/ask", json={"question": "Is the warehouse ready?"})
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]
    assert client.post("/api/ask", json={"question": "?"}).status_code == 422


def test_documents_and_upload_guards(client):
    assert client.get("/documents/call-sheet/2026-11-30").status_code == 200
    assert client.get("/documents/call-sheet/2026-11-28").status_code == 404  # not a shoot day
    bad = client.post("/api/call-sheets/upload", files={"file": ("x.txt", b"hello", "text/plain")})
    assert bad.status_code == 400
    fake = client.post("/api/call-sheets/upload", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert fake.status_code == 400
