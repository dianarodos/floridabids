"""Delete posts from the Florida Bids Instagram account. PERMANENT: Instagram has no undo.

    python -m social.ig_delete                       # list what would be deleted (all posts), delete nothing
    python -m social.ig_delete --only photos         # photos + carousels, keep videos/reels
    python -m social.ig_delete --before 2026-11-01   # only posts older than this date
    python -m social.ig_delete --confirm DELETE      # actually delete

Needs the instagram_manage_contents permission on the Page token (META_PAGE_TOKEN), and IG_USER_ID.
Run by .github/workflows/instagram-delete.yml. Export first (instagram-export.yml) if you want a copy.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import requests

GRAPH = "https://graph.facebook.com/v27.0"
KINDS = {"all": {"IMAGE", "CAROUSEL_ALBUM", "VIDEO"}, "photos": {"IMAGE", "CAROUSEL_ALBUM"}, "videos": {"VIDEO"}}


def call(method, url, params=None):
    tok = os.environ["META_PAGE_TOKEN"]
    p = None if params is None else {**params, "access_token": tok}
    r = requests.request(method, url, params=p, timeout=60)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400 or "error" in body:
        err = body.get("error", {})
        msg = (err.get("message") or r.text[:200]).replace(tok, "***")
        if err.get("code") in (10, 200) or "permission" in msg.lower():
            msg += " -> the token is missing instagram_manage_contents: add it in the app, make a new Page token, update META_PAGE_TOKEN"
        raise RuntimeError(msg)
    return body


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(KINDS), default="all")
    ap.add_argument("--before", default="", help="YYYY-MM-DD: only posts published before this date")
    ap.add_argument("--confirm", default="", help="type DELETE to really delete")
    a = ap.parse_args(argv)
    ig = os.environ["IG_USER_ID"]

    posts, page = [], call("GET", f"{GRAPH}/{ig}/media", {"fields": "id,media_type,timestamp,permalink", "limit": 50})
    while True:
        posts += page.get("data", [])
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            break
        page = call("GET", nxt)
    pick = [p for p in posts if p["media_type"] in KINDS[a.only] and (not a.before or p["timestamp"][:10] < a.before)]
    print(f"instagram: {len(posts)} posts on the account; {len(pick)} match (--only {a.only}"
          + (f", before {a.before}" if a.before else "") + ")")
    for p in pick[:10]:
        print(f"  {p['timestamp'][:10]} {p['media_type']:<15} {p.get('permalink', '')}")
    if len(pick) > 10:
        print(f"  ... and {len(pick) - 10} more")
    if a.confirm != "DELETE":
        print("Nothing deleted. To delete these, run again with confirm = DELETE.")
        return 0

    done = failed = 0
    for p in pick:
        try:
            call("DELETE", f"{GRAPH}/{p['id']}", {})
            done += 1
        except RuntimeError as e:
            failed += 1
            print(f"  could not delete {p['timestamp'][:10]} {p.get('permalink', '')}: {e}")
            if "too many actions" in str(e).lower() or "rate limit" in str(e).lower():
                print("Stopping: Instagram's rate limit. Wait an hour or two, then run it again; it picks up the rest.")
                break
            if failed >= 3 and done == 0:
                print("Stopping: the first deletes all failed.")
                break
        time.sleep(8)                                   # Instagram blocks fast deleting ("too many actions")
    print(f"instagram: deleted {done}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
