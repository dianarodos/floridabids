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
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

import requests
import yaml

from scraper import backfill, browser, emails, store
from scraper.export import write_site_json, write_xlsx
from scraper.interests import export_public
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
        if hit is not None and rank.get(b.origin, 9) >= rank.get(hit.origin, 9):   # b loses: lend hit what it lacks
            if not hit.due and b.due:
                hit.due = b.due
            if hit.number.startswith("#") and b.number and not b.number.startswith("#"):
                hit.number = b.number
        if hit is None or rank.get(b.origin, 9) < rank.get(hit.origin, 9):
            if hit is not None:          # the loser goes away under every key it held
                if b.number.startswith("#") and hit.number and not hit.number.startswith("#"):
                    b.number = hit.number    # keep the agency's real bid number over a portal id
                if not b.due and hit.due:
                    b.due = hit.due          # e.g. an OpenGov alert gets its due date from a pasted portal list
                if hit.first_seen and (not b.first_seen or hit.first_seen < b.first_seen):
                    b.first_seen = hit.first_seen   # a bid we already listed isn't "new" again
                for k in [k for k, v in best.items() if v is hit]:
                    del best[k]
            for k in keys:
                best[k] = b
    return list({id(b): b for b in best.values()}.values())


# Readers that drive the headless browser. Playwright's sync API stays on the main thread;
# everything else runs in a small pool of worker threads so one slow site can't hold up the rest.
BROWSER_READERS = {"lake", "vendorlink", "oracle_jax", "pbc_vss", "miamidade_informs"}
WORKERS = 8
BUDGET = float(os.environ.get("RUN_BUDGET_MIN", "35")) * 60      # whole source step
PER_SOURCE = float(os.environ.get("SOURCE_BUDGET_MIN", "8")) * 60
_closed = threading.Event()


def read_one(src, bids, lock):
    t0 = time.monotonic()
    entry = {"id": src["id"], "county": src["county"], "agency": src["agency"], "url": src["url"]}
    try:
        fresh = get_reader(src["reader"])(src)
        with lock:
            if _closed.is_set():          # abandoned after its time ran out; leave yesterday's bids alone
                return entry
            count, new = store.replace_source(bids, src["id"], fresh)
        entry.update(status="ok", count=count, new=new)
        if count == 0 and not src.get("may_be_empty"):
            entry["status"] = "empty"     # page read fine but nothing open; worth a look if it persists
    except Blocked as e:
        entry.update(status="blocked", error=str(e))
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code in (401, 403, 429):   # the site refuses automated reading; we don't work around that
            entry.update(status="blocked", error=f"HTTP {code} from {e.request.url if e.request else ''}")
        else:
            entry.update(status="error", error=f"HTTPError: {e}")
            log.error("%s failed:\n%s", src["id"], traceback.format_exc())
    except Exception as e:   # one broken site must not stop the rest
        entry.update(status="error", error=f"{type(e).__name__}: {e}")
        log.error("%s failed:\n%s", src["id"], traceback.format_exc())
    entry["seconds"] = round(time.monotonic() - t0, 1)
    log.info("%-32s %-7s %6.1fs %s", src["id"], entry["status"], entry["seconds"],
             entry.get("count", entry.get("error", "")))
    return entry


def run_sources(sources, bids):
    start = time.monotonic()
    deadline = start + BUDGET
    lock = threading.Lock()
    results, started = {}, {}
    work = queue.Queue()
    for s in sources:
        if s["reader"] not in BROWSER_READERS:
            work.put(s)

    def worker():
        while True:
            try:
                s = work.get_nowait()
            except queue.Empty:
                return
            if time.monotonic() > deadline:
                results[s["id"]] = {"id": s["id"], "county": s["county"], "agency": s["agency"], "url": s["url"],
                                    "status": "skipped", "error": "out of time this run"}
                continue
            started[s["id"]] = time.monotonic()
            results[s["id"]] = read_one(s, bids, lock)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
    for t in threads:
        t.start()

    # browser sources, one at a time on this thread, while the pool works
    for s in sources:
        if s["reader"] in BROWSER_READERS:
            if time.monotonic() > deadline:
                results[s["id"]] = {"id": s["id"], "county": s["county"], "agency": s["agency"], "url": s["url"],
                                    "status": "skipped", "error": "out of time this run"}
                continue
            results[s["id"]] = read_one(s, bids, lock)
    browser.close()

    # wait for the pool; a source stuck past its own budget (or the run budget) is abandoned
    while any(t.is_alive() for t in threads) and time.monotonic() < deadline:
        now = time.monotonic()
        stuck = [sid for sid, t0 in started.items() if sid not in results and now - t0 > PER_SOURCE]
        if stuck and len(stuck) >= sum(t.is_alive() for t in threads):
            break                      # every live worker is stuck on one source
        time.sleep(2)

    with lock:
        _closed.set()
    health = []
    for s in sources:
        e = results.get(s["id"])
        if e is None:
            e = {"id": s["id"], "county": s["county"], "agency": s["agency"], "url": s["url"],
                 "status": "timeout" if s["id"] in started else "skipped",
                 "error": "took too long; kept yesterday's bids" if s["id"] in started else "out of time this run"}
            log.warning("%-32s %s", s["id"], e["status"])
        health.append(e)
    log.info("sources done in %.0fs", time.monotonic() - start)
    return health


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

    sources = [s for s in cfg["direct"] if not only or s["id"] in only]
    health = run_sources(sources, bids)
    if only:   # a test run of a few sources keeps everyone else's last status in the report
        try:
            prev = json.loads((ROOT / "data" / "bids.json").read_text()).get("meta", {}).get("sources", [])
        except (OSError, ValueError):
            prev = []
        fresh = {h["id"]: h for h in health}
        health = [fresh.pop(h["id"], h) for h in prev] + list(fresh.values())

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
    export_public()                      # business types for the sign-up form and preferences page
    log.info("open bids: %d across %d counties (removed %d closed)", len(public), meta["counties"], removed)

    failed = [h for h in health if h["status"] in ("error",)]
    return 0 if len(failed) < max(3, len(health) // 2) else 1   # fail the job only if many sources broke


if __name__ == "__main__":
    sys.exit(main())
