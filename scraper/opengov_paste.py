"""Turn copied OpenGov portal pages (Cmd+A, Cmd+C) into the backfill CSV.

    python -m scraper.opengov_paste data/backfill/raw/*.txt

Each project in the pasted text looks like:
    [Title](https://procurement.opengov.com/portal/<slug>?status=open#)
    <optional solicitation number>
    Open
    <number of Q&A>
    <release date>
    <due date>
The portal slug comes from the link, so pastes can be mixed in any order.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "backfill" / "opengov.csv"
LINK = re.compile(r"^\[(.+)\]\(https?://procurement\.opengov\.com/portal/([\w-]+)[^)]*\)\s*$")
DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
STATUSES = {"open", "pending", "evaluation", "closed", "awarded"}
FIELDS = ["county", "agency", "number", "title", "due", "posted", "status", "bid_url", "source_url", "type"]


def parse(text: str, alerts: dict) -> list[dict]:
    lines = [l.strip() for l in text.splitlines()]
    rows = []
    i = 0
    while i < len(lines):
        m = LINK.match(lines[i])
        if not m or m.group(1).lower().startswith("skip to") or m.group(1).lower() == "advanced search":
            i += 1
            continue
        title, slug = m.group(1).strip(), m.group(2).lower()
        j = i + 1
        number = ""
        if j < len(lines) and lines[j] and lines[j].lower() not in STATUSES and not DATE.match(lines[j]):
            number = lines[j]
            j += 1
        status = lines[j] if j < len(lines) else ""
        dates = [l for l in lines[j + 1:j + 4] if DATE.match(l)]
        i = j + 1
        if status.lower() != "open" or len(dates) < 2:
            continue
        county, agency = alerts.get(slug, ["", slug])
        if number.lower() == "doing business post":
            number, typ = "", "Notice"
        else:
            typ = ""
        if not number:
            nm = re.match(r"^((?:ITB|RFP|RFQ|IFB|ITN)?\s?\d{2}-\d{2,4}[A-Z]?)\s+", title)
            if nm:
                number = nm.group(1)
        portal = f"https://procurement.opengov.com/portal/{slug}"
        rows.append({"county": county, "agency": agency, "number": number, "title": title, "due": dates[1],
                     "posted": dates[0], "status": "Open", "bid_url": portal, "source_url": portal, "type": typ})
    return rows


def main(paths):
    alerts = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())["alerts"]["opengov"]
    rows = []
    for p in paths:
        rows.extend(parse(Path(p).read_text(), alerts))
    seen, unique = set(), []
    for r in rows:
        k = (r["agency"], r["number"] or r["title"])
        if k not in seen:
            seen.add(k)
            unique.append(r)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(unique)
    unknown = sorted({r["agency"] for r in unique if not r["county"]})
    print(f"{len(unique)} open bids from {len({r['agency'] for r in unique})} agencies -> {OUT}")
    if unknown:
        print("Unknown portal slugs (add to sources.yaml):", ", ".join(unknown))


if __name__ == "__main__":
    main(sys.argv[1:])
