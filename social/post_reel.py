"""Post a finished Reel (MP4 in the repo) to Facebook Reels and/or Instagram Reels.

    python -m social.post_reel --video site/social/reels/2026-11-11-intro.mp4 --platforms facebook --caption-file c.txt

Facebook: upload the file straight to Meta (start -> upload bytes -> finish/publish).
Instagram: Meta fetches it from floridabids.org (the file is committed under site/social/reels/, which deploys).
Facebook Reels must be 3-90 s, 9:16. Logged in data/social_posts.json (slot "reel"); a video already posted
to a platform is skipped unless --force. Env: META_PAGE_TOKEN (Page token), FB_PAGE_ID, IG_USER_ID.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from social.post import ET, GRAPH, LOG, PostError, _call, _token, load_log

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://floridabids.org"


def fb_reel(page_id: str, path: Path, caption: str) -> str:
    start = _call("POST", f"{page_id}/video_reels", upload_phase="start")
    vid = start["video_id"]
    size = path.stat().st_size
    r = requests.post(f"https://rupload.facebook.com/video-upload/v27.0/{vid}",
                      headers={"Authorization": f"OAuth {_token()}", "offset": "0", "file_size": str(size)},
                      data=path.read_bytes(), timeout=600)
    if r.status_code >= 400 or not r.json().get("success"):
        raise PostError(f"Facebook upload failed: {r.text[:300].replace(_token(), '***')}")
    _call("POST", f"{page_id}/video_reels", upload_phase="finish", video_id=vid, video_state="PUBLISHED",
          description=caption)
    for _ in range(60):                                  # processing usually takes 10-60 s
        st = _call("GET", vid, fields="status").get("status", {})
        if st.get("video_status") == "ready" or st.get("publishing_phase", {}).get("status") == "complete":
            break
        if st.get("video_status") == "error" or st.get("processing_phase", {}).get("status") == "error":
            raise PostError(f"Facebook could not process the video: {json.dumps(st)[:300]}")
        time.sleep(5)
    return vid


def ig_reel(ig_id: str, url: str, caption: str) -> str:
    c = _call("POST", f"{ig_id}/media", media_type="REELS", video_url=url, caption=caption, share_to_feed="true")["id"]
    for _ in range(90):
        s = _call("GET", c, fields="status_code").get("status_code")
        if s == "FINISHED":
            break
        if s in ("ERROR", "EXPIRED"):
            raise PostError(f"Instagram could not process the video (status {s})")
        time.sleep(5)
    return _call("POST", f"{ig_id}/media_publish", creation_id=c)["id"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="path in the repo, under site/social/reels/")
    ap.add_argument("--platforms", default="facebook")
    ap.add_argument("--caption-file", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    path = ROOT / a.video
    if not path.exists():
        print(f"reel: {a.video} not found"); return 1
    caption = Path(a.caption_file).read_text().strip()
    platforms = [p.strip() for p in a.platforms.replace("both", "facebook,instagram").split(",") if p.strip()]
    log, failed = load_log(), False
    for p in platforms:
        if any(e.get("video") == a.video and e.get("platform") == p and e.get("status") == "posted" for e in log) and not a.force:
            print(f"  {p}: this video was already posted; skipped"); continue
        entry = {"date": datetime.now(ET).date().isoformat(), "slot": "reel", "platform": p, "video": a.video,
                 "at": datetime.now(ET).isoformat(timespec="minutes")}
        try:
            if p == "facebook":
                entry["id"] = fb_reel(os.environ["FB_PAGE_ID"], path, caption)
            elif p == "instagram":
                entry["id"] = ig_reel(os.environ["IG_USER_ID"], f"{SITE}/{a.video.removeprefix('site/')}", caption)
            else:
                raise PostError(f"unknown platform {p}")
            entry["status"] = "posted"
            print(f"  {p}: posted Reel (id {entry['id']})")
        except PostError as e:
            failed = True
            entry.update(status="failed", error=str(e))
            print(f"  {p}: FAILED: {e}")
        log.append(entry)
    LOG.write_text(json.dumps(log[-400:], indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
