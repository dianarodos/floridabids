"""bids.json: the running list of open solicitations.

Direct-read sources are replaced wholesale on every successful read.
Email and backfill items stay until their due date passes (or 60 days with no due date).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .dates import is_future
from .models import Bid, now_et

DATA = Path(__file__).resolve().parent.parent / "data"
BIDS_FILE = DATA / "bids.json"
NO_DUE_MAX_DAYS = 45   # alert-only bids without a due date (OpenGov emails don't include one)


def load() -> dict[str, Bid]:
    if not BIDS_FILE.exists():
        return {}
    raw = json.loads(BIDS_FILE.read_text())
    return {d["key"]: Bid.from_dict(d) for d in raw.get("bids", [])}


def save(bids: dict[str, Bid], meta: dict) -> None:
    DATA.mkdir(exist_ok=True)
    ordered = sorted(bids.values(), key=lambda b: (b.due or "9999", b.county, b.title))
    BIDS_FILE.write_text(json.dumps({"meta": meta, "bids": [b.to_dict() for b in ordered]}, indent=1, ensure_ascii=False))


def replace_source(bids: dict[str, Bid], source_id: str, fresh: list[Bid]) -> tuple[int, int]:
    """Swap in today's rows for one direct source. Returns (count, new_count)."""
    stamp = now_et().isoformat(timespec="minutes")
    old = {k: b for k, b in bids.items() if b.source_id == source_id and b.origin == "direct"}
    for k in old:
        del bids[k]
    new = 0
    for b in fresh:
        prev = old.get(b.key)
        b.first_seen = prev.first_seen if prev else stamp
        b.last_seen = stamp
        if not prev:
            new += 1
        bids[b.key] = b
    return len(fresh), new


def upsert(bids: dict[str, Bid], b: Bid) -> bool:
    """Add or update an email/backfill item. Returns True if new."""
    stamp = now_et().isoformat(timespec="minutes")
    prev = bids.get(b.key)
    b.first_seen = prev.first_seen if prev else stamp
    b.last_seen = stamp
    if prev:
        # keep known fields the update email left blank
        for f in ("number", "due", "bid_url", "type", "category", "posted"):
            if not getattr(b, f) and getattr(prev, f):
                setattr(b, f, getattr(prev, f))
    bids[b.key] = b
    return prev is None


def prune(bids: dict[str, Bid]) -> int:
    """Drop closed items. Returns number removed."""
    now = now_et()
    gone = []
    for k, b in bids.items():
        open_ = is_future(b.due)
        if open_ is False:
            gone.append(k)
        elif open_ is None and b.origin != "direct" and b.first_seen:
            if datetime.fromisoformat(b.first_seen) < now - timedelta(days=NO_DUE_MAX_DAYS):
                gone.append(k)
    for k in gone:
        del bids[k]
    return len(gone)
