"""Offline tests for the social post preparation (no browser, no network)."""
from datetime import date, timedelta

from social.prepare import build, nice_title


def bid(county, title, first_seen, due, category="Construction"):
    return {"county": county, "agency": f"{county} County BOCC", "title": title, "category": category,
            "first_seen": f"{first_seen}T05:20-05:00", "due": due, "bid_url": "https://example.gov/b"}


def test_nice_title_keeps_acronyms():
    assert nice_title("CRA ROOF REHAB FOR THE HVAC BUILDING - RFP 26-07") == "Cra Roof Rehab for the HVAC Building - RFP 26-07"
    assert nice_title("Grant Assistance Services") == "Grant Assistance Services"


def sample(today):
    d = lambda n: (today + timedelta(days=n)).isoformat()
    return [bid("Miami-Dade", "Roof replacement at fire station 4", d(0), d(20)),
            bid("Miami-Dade", "Janitorial services for county buildings", d(0), d(15), "Facilities & Maintenance"),
            bid("Broward", "Sidewalk repairs citywide phase two", d(-2), d(3)),
            bid("Polk", "IT network refresh and support services", d(-3), d(1), "IT & Technology"),
            bid("Lee", "Due today: mowing", d(-10), d(0), "Facilities & Maintenance")]


def test_themes_rotate_mon_to_sat():
    monday = date(2026, 11, 9)
    themes = {}
    for i in range(6):
        day = monday + timedelta(days=i)
        themes[day.strftime("%a")] = build(sample(day), day)["pm"]["theme"]
    assert themes == {"Mon": "closing_soon", "Tue": "county_spotlight", "Wed": "category_spotlight",
                      "Thu": "closing_soon", "Fri": "week_recap", "Sat": "category_spotlight"}


def test_morning_counts_new_today_and_falls_back():
    day = date(2026, 11, 10)
    out = build(sample(day), day)
    assert out["am"]["theme"] == "new_today" and out["am"]["count"] == 2 and out["stats"]["new_today"] == 2
    quiet = build([b for b in sample(day) if not b["first_seen"].startswith(day.isoformat())], day)
    assert quiet["am"]["theme"] == "closing_soon"


def test_closing_card_skips_bids_due_today():
    day = date(2026, 11, 12)                                   # Thursday: closing-soon afternoon
    out = build(sample(day), day)
    assert all(i["due"] != day.isoformat() for i in out["pm"]["items"])
    assert out["pm"]["caption_default"].startswith("⏰")
