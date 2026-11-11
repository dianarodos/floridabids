"""Download every post from the Florida Bids Instagram account (photos, carousel images, videos).

    python -m social.ig_export --out ig-export        # files + index.csv (date, type, caption, link)

Run by .github/workflows/instagram-export.yml, which zips the folder for download.
Env: META_PAGE_TOKEN, IG_USER_ID. Instagram's media links expire after a while, so files are fetched right away.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import requests

GRAPH = "https://graph.facebook.com/v27.0"
FIELDS = "id,media_type,media_url,thumbnail_url,timestamp,permalink,caption,children{id,media_type,media_url}"


def get(url, params=None):
    tok = os.environ["META_PAGE_TOKEN"]
    r = requests.get(url, params={**(params or {}), "access_token": tok} if params is not None else None, timeout=60)
    body = r.json()
    if "error" in body:
        raise SystemExit("Instagram API: " + body["error"].get("message", "error").replace(tok, "***"))
    return body


def ext(media_type, url):
    if media_type == "VIDEO":
        return ".mp4"
    path = url.split("?")[0].lower()
    return ".png" if path.endswith(".png") else ".webp" if path.endswith(".webp") else ".jpg"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="ig-export")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    posts, page = [], get(f"{GRAPH}/{os.environ['IG_USER_ID']}/media", {"fields": FIELDS, "limit": 50})
    while True:
        posts += page.get("data", [])
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            break
        page = get(nxt)                                  # 'next' already carries the token and fields

    rows, files = [], 0
    for p in posts:
        day = p["timestamp"][:10]
        items = p.get("children", {}).get("data") if p["media_type"] == "CAROUSEL_ALBUM" else [p]
        for n, m in enumerate(items or [], 1):
            url = m.get("media_url")
            if not url:                                  # e.g. a video whose file Instagram won't hand out
                continue
            name = f"{day}_{p['id']}" + (f"_{n}" if len(items) > 1 else "") + ext(m["media_type"], url)
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            (out / name).write_bytes(r.content)
            files += 1
            rows.append({"file": name, "date": p["timestamp"], "type": m["media_type"],
                         "link": p.get("permalink", ""), "caption": (p.get("caption") or "").replace("\r", "")})
        if p["media_type"] == "VIDEO" and p.get("thumbnail_url"):
            r = requests.get(p["thumbnail_url"], timeout=60)
            if r.ok:
                (out / f"{day}_{p['id']}_cover.jpg").write_bytes(r.content)
                files += 1

    with open(out / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "date", "type", "link", "caption"])
        w.writeheader()
        w.writerows(rows)
    print(f"instagram export: {len(posts)} posts, {files} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
