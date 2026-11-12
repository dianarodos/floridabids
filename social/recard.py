"""Re-pick the bids shown on today's card so the image matches the caption, then re-render it.

    python -m social.recard --slot pm --pick "Osceola:Custodial Services" --pick "Polk:Dumpster" \
        --rename 2="Choctaw Beach Fishing Pier Construction"

Each --pick is COUNTY:part-of-the-title (case-insensitive, open bids in site/data/bids.json).
--rename N=TEXT shortens the Nth title (1-based) so it fits on one line. Writes site/social/today.json
and site/social/<date>-<slot>.jpg; commit and push them before posting.
"""
from __future__ import annotations

import argparse
import json

from social.prepare import BIDS, OUT, card_html, render, slim


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=["am", "pm"], required=True)
    ap.add_argument("--pick", action="append", default=[], help="COUNTY:title words")
    ap.add_argument("--rename", action="append", default=[], help="N=shorter title")
    a = ap.parse_args(argv)
    d = json.loads((OUT / "today.json").read_text())
    bids = json.loads(BIDS.read_text())["bids"]
    items = []
    for p in a.pick:
        county, _, words = p.partition(":")
        m = [b for b in bids if b["county"].lower() == county.strip().lower() and words.strip().lower() in b["title"].lower()]
        if not m:
            raise SystemExit(f"no open bid in {county} matching '{words}'")
        items.append(slim(m[0]))
    if items:
        d[a.slot]["items"] = items
    for r in a.rename:
        n, _, text = r.partition("=")
        d[a.slot]["items"][int(n) - 1]["title"] = text.strip()
    (OUT / "today.json").write_text(json.dumps(d, indent=1, ensure_ascii=False))
    render({OUT / f"{d['date']}-{a.slot}.jpg": card_html(d[a.slot], d["nice_date"], d["stats"]["open"])})
    for i in d[a.slot]["items"]:
        print(f"  {i['county']}: {i['title']} (due {i['due'] or '-'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
