"""Post one of today's prepared posts (site/social/today.json) to the Florida Bids Facebook Page and/or Instagram.

    python -m social.post --slot am                                   # Facebook, default caption, right now
    python -m social.post --slot pm --at 15:00                        # Facebook schedules it for 3 PM Eastern
    python -m social.post --slot am --platforms facebook,instagram --caption-file caption.txt
    python -m social.post --slot am --dry-run                         # print what would be posted

Run by .github/workflows/post.yml (started after Diana approves in the morning chat), so the Meta token
only ever lives in GitHub secrets. Every post is logged in data/social_posts.json, and a slot that was
already posted today is skipped unless --force: approving twice never double-posts.

Env: META_PAGE_TOKEN (Page token from the "Florida Bids Autoposter" app), FB_PAGE_ID, IG_USER_ID.
Facebook can schedule a post (--at, 10 min to 30 days ahead); Instagram's API can't, so it posts right away.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TODAY_JSON = ROOT / "site" / "social" / "today.json"
LOG = ROOT / "data" / "social_posts.json"
GRAPH = "https://graph.facebook.com/v27.0"
# floridabids.org blocks GitHub's servers (bot protection); workers.dev serves the same files directly
CHECK_BASE = "https://floridabids.weddingboca.workers.dev"

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:                   # pragma: no cover
    ET = None


class PostError(Exception):
    pass


def _token():
    t = os.environ.get("META_PAGE_TOKEN", "").strip()
    if not t:
        raise PostError("META_PAGE_TOKEN is not set (GitHub: Settings > Secrets and variables > Actions)")
    return t


def _call(method, path, **params):
    """Graph API call; the token never appears in what we print or raise."""
    tok = _token()
    r = requests.request(method, f"{GRAPH}/{path}", data={**params, "access_token": tok} if method == "POST" else None,
                         params={**params, "access_token": tok} if method == "GET" else None, timeout=60)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    if r.status_code >= 400 or "error" in body:
        err = body.get("error", body)
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        hint = ""
        if isinstance(err, dict) and err.get("code") in (190, 102):
            hint = " -> the Page token expired or was revoked: make a new one (Graph API Explorer > Extend) and update META_PAGE_TOKEN"
        raise PostError(f"{method} {path.split('?')[0]}: {msg.replace(tok, '***')}{hint}")
    return body


def load_log():
    try:
        return json.loads(LOG.read_text())
    except (OSError, ValueError):
        return []


def already(log, day, slot, platform):
    return next((e for e in log if e.get("date") == day and e.get("slot") == slot and e.get("platform") == platform
                 and e.get("status") in ("posted", "scheduled")), None)


def wait_until_live(image_path: str, tries=18):
    """The card is committed by the morning run; make sure Cloudflare has deployed it before Meta fetches it."""
    url = f"{CHECK_BASE}/{image_path}"
    for _ in range(tries):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "FloridaBids-poster/1.0"})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                return
        except requests.RequestException:
            pass
        time.sleep(10)
    raise PostError(f"image not live yet: {url}")


def when_ts(at: str, day: date):
    """'15:00' (Eastern) on `day` -> unix time, or None to post now (also when that time is under 12 min away)."""
    if not at:
        return None
    h, m = (int(x) for x in at.strip().split(":"))
    t = datetime(day.year, day.month, day.day, h, m, tzinfo=ET)
    return int(t.timestamp()) if t - datetime.now(ET) > timedelta(minutes=12) else None


def post_facebook(page_id, image_url, caption, ts):
    params = {"url": image_url, "message": caption}
    if ts:
        params.update(published="false", scheduled_publish_time=str(ts))
    r = _call("POST", f"{page_id}/photos", **params)
    return r.get("post_id") or r.get("id")


def post_instagram(ig_id, image_url, caption):
    c = _call("POST", f"{ig_id}/media", image_url=image_url, caption=caption)["id"]
    for _ in range(30):                                          # Instagram fetches and processes the image
        s = _call("GET", c, fields="status_code").get("status_code")
        if s == "FINISHED":
            break
        if s in ("ERROR", "EXPIRED"):
            raise PostError(f"Instagram could not process the image (status {s})")
        time.sleep(4)
    return _call("POST", f"{ig_id}/media_publish", creation_id=c)["id"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=["am", "pm"], required=True)
    ap.add_argument("--platforms", default="facebook", help="facebook, instagram or facebook,instagram")
    ap.add_argument("--caption", help="post text (default: the prepared default caption)")
    ap.add_argument("--caption-file")
    ap.add_argument("--at", default="", help="HH:MM Eastern; Facebook schedules the post (blank = now)")
    ap.add_argument("--date", help="YYYY-MM-DD that today.json must be for (default: today, Eastern)")
    ap.add_argument("--force", action="store_true", help="post even if this slot was already posted today")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    data = json.loads(TODAY_JSON.read_text())
    day = date.fromisoformat(a.date) if a.date else datetime.now(ET).date()
    if data["date"] != day.isoformat():
        print(f"post: today.json is for {data['date']}, not {day}; the morning run may not have finished. Not posting.")
        return 1
    slot = data[a.slot]
    caption = (Path(a.caption_file).read_text() if a.caption_file else a.caption or "").strip() or slot["caption_default"]
    platforms = [p.strip() for p in a.platforms.replace("both", "facebook,instagram").split(",") if p.strip()]
    ts = when_ts(a.at, day)

    print(f"post: {day} {a.slot} ({slot['theme']}) -> {', '.join(platforms)}"
          + (f", scheduled {a.at} ET" if ts else ", now") + f"\n  image: {slot['image_url']}\n  caption:\n"
          + "\n".join("    " + line for line in caption.splitlines()))
    if a.dry_run:
        return 0

    log = load_log()
    wait_until_live(slot["image"])
    failed = False
    for p in platforms:
        prev = already(log, day.isoformat(), a.slot, p)
        if prev and not a.force:
            print(f"  {p}: already {prev['status']} today (id {prev.get('id')}); skipped")
            continue
        entry = {"date": day.isoformat(), "slot": a.slot, "platform": p, "theme": slot["theme"],
                 "at": datetime.now(ET).isoformat(timespec="minutes")}
        try:
            if p == "facebook":
                entry["id"] = post_facebook(os.environ.get("FB_PAGE_ID", ""), slot["image_url"], caption, ts)
                entry["status"] = "scheduled" if ts else "posted"
                if ts:
                    entry["scheduled_for"] = a.at
            elif p == "instagram":
                entry["id"] = post_instagram(os.environ.get("IG_USER_ID", ""), slot["image_url"], caption)
                entry["status"] = "posted"
            else:
                raise PostError(f"unknown platform {p}")
            print(f"  {p}: {entry['status']} (id {entry['id']})")
        except PostError as e:
            failed = True
            entry.update(status="failed", error=str(e))
            print(f"  {p}: FAILED: {e}")
        log.append(entry)
    LOG.write_text(json.dumps(log[-400:], indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
