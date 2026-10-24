"""Turn copied Bonfire portal pages (Cmd+A, Cmd+C) into the backfill CSV.

    python -m scraper.bonfire_paste data/backfill/raw/bonfire_*.txt

A pasted page looks like:
    Procurement Portal
    City of St. Pete Beach            <- agency name
    ...
    Status  Ref. #  Project  Close Date  Days Left  Action
    Open
    7th Ave Pier 2026<TAB>7th Avenue Pier Rehabilitation<TAB>Nov 4th 2026, 9:00 AM EST
Several pages can be pasted into one file. A line with the portal link
(https://<slug>.bonfirehub.com/...) anywhere in a page tells us the slug;
otherwise the agency name is looked up in sources.yaml (alerts.bonfire_names).
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "backfill" / "bonfire.csv"
FIELDS = ["county", "agency", "number", "title", "due", "posted", "status", "bid_url", "source_url", "type"]
SLUG = re.compile(r"https?://([\w-]+)\.bonfirehub\.com", re.I)
DATE = re.compile(r"^[A-Z][a-z]{2,8}\.? \d{1,2}(st|nd|rd|th)?,? \d{4}", re.I)


def parse(text: str, cfg: dict) -> tuple[list[dict], set[str]]:
    by_slug = cfg.get("bonfire", {}) or {}
    by_name = {k.lower(): v for k, v in (cfg.get("bonfire_names", {}) or {}).items()}
    rows, unknown = [], set()
    pages = re.split(r"(?m)^[ \t]*(?:[A-Za-z]+ )*(?:Procurement|Purchasing|Bid|Bidding|Vendor|Solicitations?) Portal[ \t]*$", text)
    for page in pages[1:]:
        lines = [l.rstrip("\r") for l in page.splitlines()]
        agency = next((l.strip() for l in lines if l.strip()), "")
        m = SLUG.search(page)
        slug = m.group(1).lower() if m else ""
        county, name = "", agency
        if slug and slug in by_slug:
            county, name = by_slug[slug]
        elif agency.lower() in by_name:
            entry = by_name[agency.lower()]
            county = entry[0] if isinstance(entry, list) else entry
            if isinstance(entry, list) and len(entry) > 1:
                name = entry[1]
            if isinstance(entry, list) and len(entry) > 2:
                slug = slug or entry[2]
        if not county:
            unknown.add(agency + (f" ({slug})" if slug else ""))
        portal = f"https://{slug}.bonfirehub.com/portal/?tab=openOpportunities" if slug else ""
        # column order comes from the header; rows omit the Status cell (it sits on its own line)
        header = next(([c.strip().lower() for c in l.split("\t")] for l in lines
                       if l.lower().startswith("status\t")), [])
        cols = header[1:] if header else []
        p_idx = cols.index("project") if "project" in cols else None
        r_idx = cols.index("ref. #") if "ref. #" in cols else None
        for i, l in enumerate(lines):
            if l.strip().lower() != "open" or i + 1 >= len(lines):
                continue
            cells = [c.strip() for c in lines[i + 1].split("\t")]
            d = next((k for k, c in enumerate(cells) if DATE.match(c)), None)
            if d is None or d == 0:
                continue
            if p_idx is not None and p_idx < d:
                title = cells[p_idx]
                number = cells[r_idx] if r_idx is not None and r_idx < len(cells) else ""
            else:
                title = cells[d - 1]
                number = " ".join(c for c in cells[:d - 1] if c)
            if not title:
                continue
            rows.append({"county": county, "agency": name, "number": number, "title": title, "due": cells[d],
                         "posted": "", "status": "Open", "bid_url": portal, "source_url": portal, "type": ""})
    return rows, unknown


def main(paths):
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())["alerts"]
    rows, unknown = [], set()
    for p in paths:
        r, u = parse(Path(p).read_text(), cfg)
        rows += r
        unknown |= u
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
    print(f"{len(unique)} open bids from {len({r['agency'] for r in unique})} agencies -> {OUT}")
    if unknown:
        print("Agencies missing a county in sources.yaml:", "; ".join(sorted(unknown)))


if __name__ == "__main__":
    main(sys.argv[1:])
