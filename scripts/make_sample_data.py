"""Write the fictional sample production "Harbour Lights" to sample_data/.

Everything here is invented: the show, people, addresses and hospitals. The data
deliberately contains the kinds of problems a production office has to catch, so the
rules engine and the AI have something real to find (see EXPECTED_ISSUES at the bottom,
which the tests check against):

* cast 1 and 2 wrap a night shoot at 23:30 on Day 2 and have early calls on Day 3 (turnaround)
* the Cherry St. Warehouse agreement is still unsigned the day before the shoot there
* the 12-year-old actor's work permit isn't done, and Day 5 has her in a night exterior
* the Day 3 call sheet lists scene 14, which the schedule has on Day 5
* the Day 4 call sheet has no nearest hospital
* Day 6 is 8 4/8 pages; Day 2 and Day 9 have company moves
* the stunt coordinator can't be booked until the stunt budget is approved
* overdue and unowned checklist items

    python scripts/make_sample_data.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "sample_data"

SHOW = {
    "title": "Harbour Lights (S1, Ep. 3-4 block)",
    "company": "Northlight Pictures (fictional)",
    "start": "2026-11-23",
    "end": "2026-12-04",
    "demo_today": "2026-11-24",
}

CAST = [  # id, name, role, minor
    ("1", "Maya Okafor", "Det. Jo Reyes", False),
    ("2", "Daniel Brandt", "Sgt. Tom Hale", False),
    ("3", "Priya Nair", "Dr. Lena Shah", False),
    ("4", "Owen Mercer", "Victor Kane", False),
    ("5", "Lily Chen", "Ruby Kane (age 12)", True),
    ("6", "Marcus Bell", "Officer Diaz", False),
    ("7", "Hannah Volkov", "Nadia Kane", False),
]

LOCATIONS = [  # id, name, address, parking, hospital, permit_required
    (
        "L1",
        "Studio 3 - Precinct set",
        "55 Studio Way, Toronto (fictional)",
        "Studio lot B",
        "St. Brigid General, 2.1 km",
        False,
    ),
    (
        "L2",
        "Cherry St. Warehouse",
        "Unit 4, 120 Harbour Rd, Toronto (fictional)",
        "Shuttle from studio lot B",
        "Harbourview Hospital, 3.4 km",
        True,
    ),
    (
        "L3",
        "Kane House",
        "18 Maple Crescent, Toronto (fictional)",
        "Church lot, 2 blocks north",
        "Eastgate Hospital, 1.8 km",
        True,
    ),
    (
        "L4",
        "Harbourfront Pier",
        "Pier 7, Queens Quay (fictional)",
        "Basecamp at Pier 6",
        "Harbourview Hospital, 1.2 km",
        True,
    ),
    (
        "L5",
        "Lakeview Diner",
        "2200 Lakeview Ave, Toronto (fictional)",
        "Rear lot (8 spaces) + street",
        "St. Brigid General, 4.0 km",
        True,
    ),
]

SCENES = [  # number, set, I/E, D/N, eighths, cast, location, synopsis
    ("1", "PRECINCT - BULLPEN", "INT", "DAY", 12, "1,2,6", "L1", "Jo is handed the harbour case."),
    ("2", "PRECINCT - INTERVIEW ROOM", "INT", "DAY", 18, "1,2", "L1", "First interview with the dock foreman."),
    ("3", "PRECINCT - BULLPEN", "INT", "DAY", 6, "1,6", "L1", "Diaz brings the CCTV stills."),
    ("5", "PRECINCT - CAPTAIN'S OFFICE", "INT", "DAY", 9, "1,2", "L1", "Hale pushes back on the warrant."),
    ("7", "LAKEVIEW DINER", "INT", "DAY", 14, "1,4", "L5", "Jo meets Victor Kane for the first time."),
    ("8", "HARBOURFRONT PIER", "EXT", "NIGHT", 11, "1,2", "L4", "The body at the end of Pier 7."),
    ("4", "PRECINCT - MORGUE", "INT", "DAY", 10, "1,3", "L1", "Dr. Shah's first findings."),
    ("6", "PRECINCT - BULLPEN", "INT", "DAY", 8, "1,2", "L1", "The tide-chart clue."),
    ("9", "PRECINCT - INTERVIEW ROOM", "INT", "DAY", 15, "1,2,3", "L1", "Shah walks them through the timeline."),
    ("10", "WAREHOUSE - LOADING DOCK", "EXT", "DAY", 9, "1,2", "L2", "Surveillance on the loading dock."),
    ("11", "WAREHOUSE - OFFICE", "INT", "DAY", 16, "1,2,4", "L2", "Kane's office is searched."),
    ("12", "WAREHOUSE - COLD ROOM", "INT", "DAY", 7, "1,4", "L2", "Jo finds the ledger."),
    ("13", "KANE HOUSE - KITCHEN", "INT", "DAY", 12, "4,5,7", "L3", "Family breakfast, tension."),
    ("14", "KANE HOUSE - RUBY'S ROOM", "INT", "DAY", 8, "5,7", "L3", "Nadia comforts Ruby."),
    ("15", "KANE HOUSE - STUDY", "INT", "DAY", 10, "4,7", "L3", "Nadia confronts Victor."),
    ("16", "KANE HOUSE - BACKYARD", "EXT", "NIGHT", 6, "4,5", "L3", "Ruby sees the boat lights."),
    ("17", "PRECINCT - BULLPEN", "INT", "DAY", 13, "1,2,6", "L1", "The team maps the shipments."),
    ("18", "PRECINCT - INTERVIEW ROOM", "INT", "DAY", 20, "1,4", "L1", "Victor's formal interview."),
    ("19", "PRECINCT - MORGUE", "INT", "DAY", 9, "1,3", "L1", "Second autopsy result."),
    ("20", "PRECINCT - CAPTAIN'S OFFICE", "INT", "DAY", 11, "1,2", "L1", "Warrant approved."),
    ("21", "PRECINCT - HALLWAY", "INT", "DAY", 15, "1,2,6", "L1", "Leak to the press."),
    ("22", "HARBOURFRONT PIER", "EXT", "DAY", 14, "1,2,4", "L4", "Foot chase along the pier (stunt)."),
    ("23", "HARBOURFRONT PIER - BOATHOUSE", "INT", "DAY", 10, "1,4", "L4", "Kane cornered (stunt)."),
    ("24", "KANE HOUSE - LIVING ROOM", "INT", "DAY", 12, "1,7", "L3", "Jo questions Nadia."),
    ("25", "KANE HOUSE - FRONT PORCH", "EXT", "DAY", 5, "1,5,7", "L3", "Ruby gives Jo the drawing."),
    ("26", "KANE HOUSE - STUDY", "INT", "DAY", 9, "1,2", "L3", "The hidden safe."),
    ("27", "LAKEVIEW DINER", "INT", "DAY", 11, "1,2", "L5", "Jo and Hale regroup."),
    ("28", "PRECINCT - BULLPEN", "INT", "DAY", 10, "1,2,3,6", "L1", "Case board comes together."),
    ("29", "PRECINCT - INTERVIEW ROOM", "INT", "DAY", 18, "1,4", "L1", "Victor breaks."),
    ("30", "PRECINCT - BULLPEN", "INT", "NIGHT", 6, "1,2", "L1", "Jo alone with the file."),
]

DAYS = [  # day, date, scenes, crew call, est wrap, notes
    (1, "2026-11-23", "1,2,3,5", "07:00", "19:00", ""),
    (2, "2026-11-24", "7,8", "11:00", "23:30", "Company move: diner to pier at 17:30. Night exterior."),
    (3, "2026-11-25", "4,6,9", "07:00", "18:30", ""),
    (4, "2026-11-26", "10,11,12", "07:30", "19:00", "Crew shuttle from studio lot B."),
    (5, "2026-11-27", "13,14,15,16", "12:00", "23:00", "Split day. Sc. 16 night exterior."),
    (6, "2026-11-30", "17,18,19,20,21", "07:00", "20:00", ""),
    (7, "2026-12-01", "22,23", "07:00", "19:00", "Stunt day. Safety meeting at crew call."),
    (8, "2026-12-02", "24,25,26", "07:30", "18:30", ""),
    (9, "2026-12-03", "27,28", "07:00", "19:30", "Company move: diner to studio at 12:30."),
    (10, "2026-12-04", "29,30", "08:00", "20:00", "Final day of the block."),
]

CALL_SHEETS = [
    {
        "date": "2026-11-23",
        "day_number": 1,
        "crew_call": "07:00",
        "shooting_call": "08:00",
        "est_wrap": "19:00",
        "weather": "Cloudy, 3C",
        "sunrise": "07:24",
        "sunset": "16:45",
        "location_ids": ["L1"],
        "nearest_hospital": "St. Brigid General, 2.1 km",
        "scene_numbers": ["1", "2", "3", "5"],
        "cast_calls": [
            {"cast_id": "1", "pickup": "06:15", "hmu": "06:45", "on_set": "08:00"},
            {"cast_id": "2", "pickup": "06:30", "hmu": "07:00", "on_set": "08:00"},
            {"cast_id": "6", "pickup": "07:30", "hmu": "08:00", "on_set": "09:00"},
        ],
        "crew_calls": [
            {"department": "Camera", "call": "07:00"},
            {"department": "Grip/Electric", "call": "06:45"},
            {"department": "Hair/Makeup", "call": "06:30"},
        ],
        "notes": "Welcome to day 1. Closed set for sc. 2.",
    },
    {
        "date": "2026-11-24",
        "day_number": 2,
        "crew_call": "11:00",
        "shooting_call": "12:00",
        "est_wrap": "23:30",
        "weather": "Clear, -1C overnight",
        "sunrise": "07:25",
        "sunset": "16:44",
        "location_ids": ["L5", "L4"],
        "nearest_hospital": "Harbourview Hospital, 1.2 km (pier)",
        "scene_numbers": ["7", "8"],
        "cast_calls": [
            {"cast_id": "1", "pickup": "10:15", "hmu": "10:45", "on_set": "12:00"},
            {"cast_id": "4", "pickup": "10:30", "hmu": "11:00", "on_set": "12:00"},
            {"cast_id": "2", "pickup": "16:30", "hmu": "17:00", "on_set": "18:30"},
        ],
        "crew_calls": [{"department": "Camera", "call": "11:00"}, {"department": "Grip/Electric", "call": "10:30"}],
        "notes": "Company move to the pier at 17:30. Night exterior: dress warmly. Safety meeting at the pier.",
    },
    {
        # Planted: lists sc. 14 (scheduled on Day 5). Cast 1 called 07:00 after a 23:30 wrap.
        "date": "2026-11-25",
        "day_number": 3,
        "crew_call": "07:00",
        "shooting_call": "08:00",
        "est_wrap": "18:30",
        "weather": "Light rain, 4C",
        "sunrise": "07:27",
        "sunset": "16:43",
        "location_ids": ["L1"],
        "nearest_hospital": "St. Brigid General, 2.1 km",
        "scene_numbers": ["4", "6", "9", "14"],
        "cast_calls": [
            {"cast_id": "1", "pickup": "05:45", "hmu": "06:15", "on_set": "07:00"},
            {"cast_id": "2", "pickup": "06:30", "hmu": "07:00", "on_set": "08:00"},
            {"cast_id": "3", "pickup": "07:30", "hmu": "08:00", "on_set": "09:30"},
        ],
        "crew_calls": [{"department": "Camera", "call": "07:00"}, {"department": "Hair/Makeup", "call": "05:45"}],
        "notes": "",
    },
    {
        # Planted: no nearest hospital listed.
        "date": "2026-11-26",
        "day_number": 4,
        "crew_call": "07:30",
        "shooting_call": "08:30",
        "est_wrap": "19:00",
        "weather": "Overcast, 2C",
        "sunrise": "07:28",
        "sunset": "16:42",
        "location_ids": ["L2"],
        "nearest_hospital": None,
        "scene_numbers": ["10", "11", "12"],
        "cast_calls": [
            {"cast_id": "1", "pickup": "06:45", "hmu": "07:15", "on_set": "08:30"},
            {"cast_id": "2", "pickup": "06:45", "hmu": "07:15", "on_set": "08:30"},
            {"cast_id": "4", "pickup": "09:00", "hmu": "09:30", "on_set": "10:30"},
        ],
        "crew_calls": [{"department": "Camera", "call": "07:30"}, {"department": "Transport", "call": "06:30"}],
        "notes": "Crew shuttle from studio lot B every 15 minutes from 06:45. No parking at the warehouse.",
    },
    {
        "date": "2026-11-27",
        "day_number": 5,
        "crew_call": "12:00",
        "shooting_call": "13:00",
        "est_wrap": "23:00",
        "weather": "Clear, -2C overnight",
        "sunrise": "07:29",
        "sunset": "16:42",
        "location_ids": ["L3"],
        "nearest_hospital": "Eastgate Hospital, 1.8 km",
        "scene_numbers": ["13", "14", "15", "16"],
        "cast_calls": [
            {"cast_id": "4", "pickup": "11:15", "hmu": "11:45", "on_set": "13:00"},
            {"cast_id": "5", "pickup": "12:30", "hmu": "13:00", "on_set": "14:00"},
            {"cast_id": "7", "pickup": "11:30", "hmu": "12:00", "on_set": "13:00"},
        ],
        "crew_calls": [{"department": "Camera", "call": "12:00"}, {"department": "Locations", "call": "10:00"}],
        "notes": "Minor on set (cast 5): tutor and guardian required. Sc. 16 night exterior.",
    },
]

CHECKLIST = [  # id, phase, dept, task, owner, due, status, depends, location, cast, notes
    (
        "CL-01",
        "prep",
        "Locations",
        "Location agreement signed - Cherry St. Warehouse",
        "Sam Ortiz (Locations)",
        "2026-11-20",
        "open",
        "",
        "L2",
        "",
        "Owner's lawyer reviewing the indemnity clause.",
    ),
    (
        "CL-02",
        "prep",
        "Locations",
        "Location agreement signed - Kane House",
        "Sam Ortiz (Locations)",
        "2026-11-18",
        "done",
        "",
        "L3",
        "",
        "",
    ),
    (
        "CL-03",
        "prep",
        "Locations",
        "Film permit - Harbourfront Pier",
        "Sam Ortiz (Locations)",
        "2026-11-19",
        "done",
        "",
        "L4",
        "",
        "",
    ),
    (
        "CL-04",
        "prep",
        "Locations",
        "Location agreement signed - Lakeview Diner",
        "Sam Ortiz (Locations)",
        "2026-11-19",
        "done",
        "",
        "L5",
        "",
        "",
    ),
    ("CL-05", "prep", "Production", "Distribute crew list v2", "", "2026-11-20", "open", "", "", "", ""),
    (
        "CL-06",
        "prep",
        "Production",
        "Minor work permit - Lily Chen (cast 5)",
        "Jess Kim (Prod. Coordinator)",
        "2026-11-25",
        "in_progress",
        "",
        "",
        "5",
        "Waiting on school letter.",
    ),
    (
        "CL-07",
        "prep",
        "Stunts",
        "Stunt budget approved",
        "Ravi Patel (Line Producer)",
        "2026-11-24",
        "open",
        "",
        "",
        "",
        "",
    ),
    (
        "CL-08",
        "prep",
        "Stunts",
        "Book stunt coordinator for pier chase",
        "Alex Moreau (1st AD)",
        "2026-11-27",
        "open",
        "CL-07",
        "L4",
        "",
        "Needed for Day 7 rehearsal on Nov 30.",
    ),
    (
        "CL-09",
        "prep",
        "Safety",
        "Safety meeting plan - night pier shoot",
        "Alex Moreau (1st AD)",
        "2026-11-23",
        "done",
        "",
        "L4",
        "",
        "",
    ),
    (
        "CL-10",
        "prep",
        "Transport",
        "Crew shuttle studio lot B to warehouse",
        "Dee Grant (Transport)",
        "2026-11-25",
        "in_progress",
        "",
        "L2",
        "",
        "",
    ),
    (
        "CL-11",
        "prep",
        "Art",
        "Dress Kane House (kitchen, study, Ruby's room)",
        "Noor Haddad (Art)",
        "2026-11-26",
        "in_progress",
        "",
        "L3",
        "",
        "",
    ),
    (
        "CL-12",
        "prep",
        "Wardrobe",
        "Fittings - cast 4 and 7",
        "Iris Lund (Wardrobe)",
        "2026-11-21",
        "done",
        "",
        "",
        "",
        "",
    ),
    (
        "CL-13",
        "prep",
        "Locations",
        "Neighbour notification letters - Maple Crescent",
        "Sam Ortiz (Locations)",
        "2026-11-25",
        "open",
        "",
        "L3",
        "",
        "",
    ),
    (
        "CL-14",
        "prep",
        "Production",
        "Parking permits - Harbourfront basecamp",
        "Jess Kim (Prod. Coordinator)",
        "2026-11-30",
        "open",
        "",
        "L4",
        "",
        "",
    ),
    (
        "CL-15",
        "prep",
        "Camera",
        "Book drone and operator for pier chase",
        "Theo Brooks (DP)",
        "2026-11-27",
        "open",
        "",
        "L4",
        "",
        "",
    ),
    (
        "CL-16",
        "shoot",
        "Accounting",
        "Weekly cost report - week 1",
        "Mei Tan (Accountant)",
        "2026-11-27",
        "open",
        "",
        "",
        "",
        "",
    ),
    (
        "CL-17",
        "wrap",
        "Locations",
        "Location wrap walkthrough and photos",
        "Sam Ortiz (Locations)",
        "2026-12-08",
        "open",
        "",
        "",
        "",
        "",
    ),
    ("CL-18", "wrap", "Art", "Return rentals and props", "Noor Haddad (Art)", "2026-12-09", "open", "", "", "", ""),
    (
        "CL-19",
        "wrap",
        "Accounting",
        "Final cost report for the block",
        "Mei Tan (Accountant)",
        "2026-12-18",
        "open",
        "",
        "",
        "",
        "",
    ),
    ("CL-20", "wrap", "Production", "Wrap party venue", "", "2026-12-04", "open", "", "", "", ""),
]

# What the rules engine must find on demo_today (2026-11-24). Checked by tests/test_rules.py.
EXPECTED_ISSUES = {
    # 12-01 was not planted: the engine found it (Day 6 wraps 20:00, Day 7 crew call 07:00).
    "TURNAROUND": ["1@2026-11-25", "2@2026-11-25", "1@2026-12-01", "2@2026-12-01", "4@2026-12-01"],
    "PERMIT_NOT_READY": ["L2@2026-11-26"],
    "MINOR_PERMIT": ["5@2026-11-27"],
    "MINOR_HOURS": ["5@2026-11-27"],
    "CALL_SHEET_MISMATCH": ["2026-11-25"],
    "MISSING_SAFETY_INFO": ["2026-11-26"],
    "OVERLOADED_DAY": ["2026-11-30"],
    "BLOCKED_TASK": ["CL-08"],
    "OVERDUE_TASK": ["CL-01", "CL-05"],
    "NO_OWNER": ["CL-05", "CL-20"],
    "COMPANY_MOVE": ["2026-11-24", "2026-12-03"],
}


def write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "call_sheets").mkdir(exist_ok=True)
    (OUT / "production.json").write_text(json.dumps(SHOW, indent=2) + "\n", encoding="utf-8")
    write_csv(OUT / "cast.csv", ["id", "name", "role", "minor"], [(i, n, r, str(m).lower()) for i, n, r, m in CAST])
    write_csv(
        OUT / "locations.csv",
        ["id", "name", "address", "parking", "nearest_hospital", "permit_required"],
        [(*row[:5], str(row[5]).lower()) for row in LOCATIONS],
    )
    write_csv(
        OUT / "scenes.csv",
        ["scene", "set_name", "int_ext", "day_night", "pages_eighths", "cast_ids", "location_id", "synopsis"],
        SCENES,
    )
    write_csv(OUT / "schedule.csv", ["day", "date", "scenes", "crew_call", "est_wrap", "notes"], DAYS)
    write_csv(
        OUT / "checklist.csv",
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
        ],
        CHECKLIST,
    )
    for sheet in CALL_SHEETS:
        (OUT / "call_sheets" / f"call_sheet_{sheet['date']}.json").write_text(
            json.dumps(sheet, indent=2) + "\n", encoding="utf-8"
        )
    (OUT / "expected_issues.json").write_text(json.dumps(EXPECTED_ISSUES, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote sample production to {OUT}")


if __name__ == "__main__":
    main()
