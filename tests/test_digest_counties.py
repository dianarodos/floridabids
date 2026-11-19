from scraper.digest import build, in_counties
from scraper.models import now_et

BIDS = [
    {"title": "Roof repair", "county": "Broward", "agency": "A", "first_seen": "2099-01-01T00:00-05:00", "due": "2099-02-01"},
    {"title": "Paving", "county": "Miami-Dade", "agency": "B", "first_seen": "2099-01-01T00:00-05:00", "due": "2099-02-01"},
    {"title": "Mowing", "county": "St. Johns", "agency": "C", "first_seen": "2099-01-01T00:00-05:00", "due": "2099-02-01"},
]


def test_no_counties_means_all():
    assert in_counties(BIDS, []) == BIDS
    assert in_counties(BIDS, None) == BIDS


def test_filters_case_insensitive_and_ignores_blanks():
    assert [b["title"] for b in in_counties(BIDS, ["broward", " St. Johns ", ""])] == ["Roof repair", "Mowing"]


def test_build_limits_email_to_chosen_counties():
    sub = {"token": "t", "interests": [], "keywords": "", "counties": ["Broward"]}
    subject, html, text = build(BIDS, {"total": 3}, "weekly", "https://floridabids.org", "https://x/u", now_et(), None, sub)
    assert "Roof repair" in html and "Paving" not in html and "Mowing" not in html
    assert "1 open" in subject and "Showing bids in: Broward" in text


def test_attachment_only_has_chosen_counties(tmp_path):
    import base64, io
    from openpyxl import load_workbook
    from scraper.digest import county_attachment
    cache = {}
    att = county_attachment(BIDS, ["Broward", "st. johns"], "Nov 18", "2026-11-18", cache)
    ws = load_workbook(io.BytesIO(base64.b64decode(att["content"]))).active
    assert sorted(r[0] for r in ws.iter_rows(min_row=2, values_only=True)) == ["Broward", "St. Johns"]
    assert county_attachment(BIDS, ["St. Johns", "broward"], "Nov 18", "2026-11-18", cache) is att   # same set, built once
