"""Offline tests for the daily Facebook post text."""
from datetime import datetime

from scraper.facebook import compose, highlights
from scraper.models import ET

NOW = datetime(2026, 11, 3, 6, 30, tzinfo=ET)


def bid(title, county, cat="Construction", due="2026-11-07", seen="2026-11-03T05:00-05:00"):
    return dict(title=title, county=county, agency=f"{county} County BOCC", category=cat, due=due, first_seen=seen)


def test_new_bids_post_has_hook_highlights_and_link():
    bids = [bid("Road Resurfacing", "Polk"), bid("LAPTOP PURCHASE", "Lee", "IT & Technology"),
            bid("Old one", "Bay", seen="2026-10-01T05:00-04:00", due="2026-12-30")]
    text = compose(bids, NOW)
    assert "2 " in text.splitlines()[0]             # hook counts only today's new bids
    assert "Road Resurfacing" in text and "Laptop Purchase" in text and "Old one" not in text
    assert "https://floridabids.org" in text and "#FloridaBids" in text
    assert "2 bids close in the next 7 days" in text


def test_quiet_day_falls_back_to_closing_soon():
    bids = [bid("Old one", "Bay", seen="2026-10-01T05:00-04:00", due="2026-11-05")]
    text = compose(bids, NOW)
    assert "Closing soon" in text and "Old one" in text


def test_nothing_to_post():
    assert compose([], NOW) is None


def test_highlights_spread_across_counties():
    new = [bid(f"Job {i}", "Polk") for i in range(4)] + [bid("Other county", "Lee")]
    picks = highlights(new, limit=2)
    assert {b["county"] for b in picks} == {"Polk", "Lee"}
