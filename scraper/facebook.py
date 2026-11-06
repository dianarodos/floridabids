"""Post the day's bids to the Florida Bids Facebook Page (run by the daily GitHub job after run.py).

    python -m scraper.facebook --dry-run   # print today's post, send nothing
    python -m scraper.facebook             # post it (once per Eastern day)
    python -m scraper.facebook --force     # post even if today's post already went out

Needs env: FB_PAGE_ID, FB_PAGE_TOKEN (a Page access token with pages_manage_posts).
Optional: SITE_URL (default https://floridabids.org), FB_GRAPH_VERSION (default v24.0).
With no FB_PAGE_ID / FB_PAGE_TOKEN it prints the post and exits quietly, so the daily run never fails on it.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests

from .models import ET, now_et

ROOT = Path(__file__).resolve().parent.parent
BIDS = ROOT / "site" / "data" / "bids.json"
STATE = ROOT / "data" / "facebook_state.json"
log = logging.getLogger("facebook")

EMOJI = {
    "Construction": "🏗️",
    "Facilities & Maintenance": "🔧",
    "Goods & Supplies": "📦",
    "Consulting & Professional Services": "💼",
    "Engineering & Architecture": "📐",
    "IT & Technology": "💻",
    "Concessions & Programs": "🎟️",
    "Property & Real Estate": "🏢",
}
SKIP_CATEGORIES = {"Notices & Events"}

# {n} = new bids today, {total} = open bids, {counties} = counties with new bids. Rotated by date.
HOOKS_NEW = [
    "🚨 {n} NEW Florida government bids just dropped!",
    "💰 Florida agencies want to hire you. {n} new bids posted today.",
    "🔥 Fresh contracts alert: {n} new public bids across {counties} Florida counties.",
    "📢 Contractors, vendors, consultants: {n} new opportunities hit the street today.",
    "👀 Did you see these? {n} new Florida bids went live today.",
    "🌴 Good morning, Florida! {n} new government contracts are open for bids.",
    "⚡ {n} new chances to win public work in Florida, posted today.",
]
HOOKS_QUIET = [
    "⏰ Deadlines are coming fast. {soon} Florida bids close in the next 7 days.",
    "📋 {total} Florida government bids are open right now. Is one of them yours?",
    "💡 Your next contract could already be posted. {total} Florida bids are open today.",
]
CLOSERS = [
    "Don't leave money on the table.",
    "The early bidder gets the questions answered first.",
    "Your competitors are reading this too.",
    "Small businesses win these every day. Why not you?",
]
HASHTAGS = "#FloridaBids #GovernmentContracts #PublicProcurement #RFP #SmallBusiness #Florida"


def _d(iso: str | None):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso if "T" in iso else iso + "T00:00:00")
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=ET)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1))


def pick(bids, now, since=None):
    """New = first seen since the last post (fallback: last 24 hours). Soon = due within 7 days."""
    since = since or now - timedelta(days=1)
    new = [b for b in bids if (_d(b.get("first_seen")) or since) > since]
    soon = [b for b in bids if b.get("due") and now <= (_d(b["due"]) or now) <= now + timedelta(days=7)]
    return new, soon


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if sum(c.isupper() for c in text) > 0.7 * sum(c.isalpha() for c in text):
        text = text.title()  # ALL-CAPS titles read as shouting on Facebook
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def highlights(new, limit=5):
    """A varied handful: real solicitations, spread across counties and categories, soonest due first."""
    pool = [b for b in new if b.get("category") not in SKIP_CATEGORIES and b.get("title")]
    pool.sort(key=lambda b: b.get("due") or "9999")
    out, counties, cats = [], set(), Counter()
    for b in pool:
        if len(out) >= limit:
            break
        if b.get("county") in counties or cats[b.get("category")] >= 2:
            continue
        out.append(b)
        counties.add(b.get("county"))
        cats[b.get("category")] += 1
    for b in pool:  # top up if variety rules left room
        if len(out) >= limit:
            break
        if b not in out:
            out.append(b)
    return out


def _line(b) -> str:
    due = _d(b.get("due"))
    due_s = f" · due {due.strftime('%b %-d')}" if due else ""
    where = b.get("agency") or ""
    if b.get("county") and b["county"] not in where:
        where += f" ({b['county']})"
    return f"{EMOJI.get(b.get('category'), '📌')} {_short(b['title'], 90)}\n    {where}{due_s}"


def compose(bids, now, since=None, site="https://floridabids.org") -> str | None:
    """Build the post text. Returns None when there is nothing worth posting."""
    if not bids:
        return None
    new, soon = pick(bids, now, since)
    day = now.toordinal()
    counties = len({b.get("county") for b in new if b.get("county")})
    fmt = dict(n=len(new), total=len(bids), soon=len(soon), counties=counties)
    parts = []
    if new:
        parts.append(HOOKS_NEW[day % len(HOOKS_NEW)].format(**fmt))
        cats = Counter(b.get("category") for b in new if b.get("category") not in SKIP_CATEGORIES | {"Other", None, ""})
        if cats:
            top = ", ".join(f"{c} ({k})" for c, k in cats.most_common(3))
            parts.append(f"Top categories today: {top}.")
        picks = highlights(new)
        if picks:
            parts.append("🔎 A few that caught our eye:\n" + "\n".join(_line(b) for b in picks))
    else:
        parts.append(HOOKS_QUIET[day % len(HOOKS_QUIET)].format(**fmt))
        picks = highlights(soon, limit=3)
        if picks:
            parts.append("⏳ Closing soon:\n" + "\n".join(_line(b) for b in picks))
    if soon and new:
        parts.append(f"⏰ {len(soon)} bids close in the next 7 days. {CLOSERS[day % len(CLOSERS)]}")
    parts.append(f"👉 See all {len(bids)} open Florida bids, free: {site}\n"
                 f"📩 Get the daily list in your inbox, free, at {site}")
    parts.append(HASHTAGS)
    return "\n\n".join(parts)


def post(page_id: str, token: str, message: str, link: str, version: str) -> str:
    r = requests.post(f"https://graph.facebook.com/{version}/{page_id}/feed",
                      data={"message": message, "link": link, "access_token": token}, timeout=60)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    if r.status_code != 200 or "id" not in body:
        err = body.get("error", body)
        raise RuntimeError(f"Facebook said {r.status_code}: {err.get('message', err) if isinstance(err, dict) else err}")
    return body["id"]


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the post, send nothing")
    ap.add_argument("--force", action="store_true", help="post even if today's post already went out")
    args = ap.parse_args(argv)

    site = os.environ.get("SITE_URL", "https://floridabids.org")
    page_id, token = os.environ.get("FB_PAGE_ID", "").strip(), os.environ.get("FB_PAGE_TOKEN", "").strip()
    version = os.environ.get("FB_GRAPH_VERSION", "v24.0")
    now = now_et()
    today = now.strftime("%Y-%m-%d")
    state = load_state()

    if state.get("last_date") == today and not args.force and not args.dry_run:
        log.info("Facebook: already posted today (%s), skipping.", state.get("last_id"))
        return 0
    bids = json.loads(BIDS.read_text()).get("bids", [])
    message = compose(bids, now, _d(state.get("last_posted")), site)
    if not message:
        log.info("Facebook: no bids to post about.")
        return 0
    if args.dry_run or not (page_id and token):
        if not args.dry_run:
            log.info("Facebook: FB_PAGE_ID / FB_PAGE_TOKEN not set, printing instead of posting.")
        print(message)
        return 0
    try:
        post_id = post(page_id, token, message, site, version)
    except Exception as e:  # the workflow step has continue-on-error, so this shows red without stopping the run
        log.error("Facebook: post failed: %s", e)
        return 1
    log.info("Facebook: posted %s", post_id)
    state.update(last_date=today, last_posted=now.isoformat(timespec="minutes"), last_id=post_id)
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
