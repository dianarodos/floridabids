"""One-time backfill: bids that were already open before the email alerts started.

Drop CSV files into data/backfill/ with these headers (extra columns are ignored):
    county, agency, number, title, due, bid_url, source_url, type, status
Rows load on every run (idempotent) and drop off once their due date passes.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import Bid
from .readers import make_bid

FOLDER = Path(__file__).resolve().parent.parent / "data" / "backfill"


def load() -> list[Bid]:
    out = []
    if not FOLDER.exists():
        return out
    for f in sorted(FOLDER.glob("*.csv")):
        with f.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                if not row.get("title"):
                    continue
                slug = re.sub(r"[^a-z0-9]+", "-", f"{row.get('agency', '')}".lower()).strip("-")
                src = {"id": f"backfill-{slug}", "county": row.get("county", ""), "agency": row.get("agency", ""),
                       "url": row.get("source_url") or row.get("bid_url", "")}
                b = make_bid(src, title=row["title"], number=row.get("number", ""), due_raw=row.get("due", ""),
                             type_=row.get("type", ""), status=row.get("status") or "Open", posted_raw=row.get("posted", ""),
                             bid_url=row.get("bid_url", ""), notes="Added by one-time backfill.")
                b.origin = "backfill"
                out.append(b)
    return out
