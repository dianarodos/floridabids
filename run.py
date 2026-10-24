"""Daily job: read every source, update the running list, write the site files.

    python run.py                 # everything
    python run.py --only lake-county,polk-county   # a few direct sources (for testing)
    python run.py --no-email      # skip the inbox
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import traceback
from pathlib import Path

import yaml

from scraper import backfill, browser, emails, store
from scraper.export import write_site_json, write_xlsx
from scraper.models import now_et
from scraper.net import Blocked
from scraper.readers import get_reader

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
log = logging.getLogger("run")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def dedupe(bids):
    """Same agency + same title (or number) from two origins: keep direct > email > backfill."""
    rank = {"direct": 0, "email": 1, "backfill": 2}
    best = {}
    for b in bids:
        keys = [("t", _norm(b.agency), _norm(b.title))]
        if b.number and not b.number.startswith("#"):
            keys.append(("n", _norm(b.agency), _norm(b.number)))
        hit = next((best[k] for k in keys if k in best), None)
        if hit is None or rank.get(b.origin, 9) < rank.get(hit.origin, 9):
            for k in keys:
                best[k] = b
    return list({id(b): b for b in best.values()}.values())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-email", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    bids = store.load()
    health = []

    for src in cfg["direct"]:
        if only and src["id"] not in only:
            continue
        t0 = time.monotonic()
        entry = {"id": src["id"], "county": src["county"], "agency": src["agency"], "url": src["url"]}
        try:
            fresh = get_reader(src["reader"])(src)
            count, new = store.replace_source(bids, src["id"], fresh)
            entry.update(status="ok", count=count, new=new)
            if count == 0 and not src.get("may_be_empty"):
                entry["status"] = "empty"     # page read fine but nothing open; worth a look if it persists
        except Blocked as e:
            entry.update(status="blocked", error=str(e))
        except Exception as e:   # one broken site must not stop the rest
            entry.update(status="error", error=f"{type(e).__name__}: {e}")
            log.error("%s failed:\n%s", src["id"], traceback.format_exc())
        entry["seconds"] = round(time.monotonic() - t0, 1)
        log.info("%-28s %-7s %s", src["id"], entry["status"], entry.get("count", entry.get("error", "")))
        health.append(entry)
    browser.close()

    email_info = {"status": "skipped"}
    if not args.no_email and not only:
        try:
            found, email_info = emails.fetch_and_parse(cfg.get("alerts", {}))
            for b in found:
                store.upsert(bids, b)
        except Exception as e:
            email_info = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            log.error("email step failed:\n%s", traceback.format_exc())

    for b in backfill.load():
        if b.key not in bids:
            store.upsert(bids, b)

    removed = store.prune(bids)
    updated = now_et().strftime("%Y-%m-%d %I:%M %p")
    meta = {
        "updated": updated,
        "updated_iso": now_et().isoformat(timespec="minutes"),
        "sources": health,
        "email": email_info,
        "alert_portals": {p: len(v) for p, v in cfg.get("alerts", {}).items()},
        "skipped": cfg.get("skipped", []),
        "removed_today": removed,
    }
    store.save(bids, meta)

    public = dedupe(list(bids.values()))
    public.sort(key=lambda b: (b.due or "9999", b.county, b.title))
    meta["total"] = len(public)
    meta["counties"] = len({b.county for b in public})
    write_site_json(public, meta, SITE / "data" / "bids.json")
    write_xlsx(public, SITE / "data" / "florida-open-bids.xlsx", updated)
    log.info("open bids: %d across %d counties (removed %d closed)", len(public), meta["counties"], removed)

    failed = [h for h in health if h["status"] in ("error",)]
    return 0 if len(failed) < max(3, len(health) // 2) else 1   # fail the job only if many sources broke


if __name__ == "__main__":
    sys.exit(main())
