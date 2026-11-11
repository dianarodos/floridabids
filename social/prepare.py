"""Get the day's social posts ready (run by the daily GitHub job right after run.py).

    python -m social.prepare                 # today (Eastern)
    python -m social.prepare --date 2026-11-10 --no-images

Writes, all public on floridabids.org once the commit deploys:
    site/social/today.json         what's new today, the morning + afternoon post data, video highlights,
                                   and a plain default caption for each post (used if nobody writes a better one)
    site/social/<date>-am.jpg      morning card: today's new bids
    site/social/<date>-pm.jpg      afternoon card: a rotating theme (closing soon, county / category spotlight, recap)

Claude's 7 AM task reads today.json to write the captions and the video script; social/post.py posts them.
Images are 1080x1350 (4:5), which Facebook and Instagram both show full-size in the feed.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIDS = ROOT / "site" / "data" / "bids.json"
OUT = ROOT / "site" / "social"
ASSETS = Path(__file__).resolve().parent
SITE = "https://floridabids.org"
KEEP_DAYS = 14                      # older card images are deleted so the repo doesn't grow forever

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:                   # pragma: no cover
    ET = None

# ---------------------------------------------------------------- data

ACRONYMS = {"RFP", "RFQ", "RFI", "ITB", "IFB", "ITN", "RFB", "CEI", "HVAC", "IT", "ADA", "LED", "US", "FL", "II", "III",
            "IV", "CCTV", "GIS", "ERP", "LLC", "FDOT", "SR", "CR", "AV", "EMS", "ERU", "PVC", "UV", "SCADA", "CIP",
            "FY", "PBC", "MDC", "WWTP", "WTP", "HOA", "K-12", "AC", "DPW", "ROW", "CM", "CMAR", "GMP", "A/E", "MEP"}
SMALL = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with", "from", "into"}


def nice_title(t: str) -> str:
    """Agency titles are often ALL CAPS; make them readable without wrecking acronyms."""
    t = " ".join((t or "").split())
    letters = [c for c in t if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.7:
        return t
    out = []
    for i, w in enumerate(t.split(" ")):
        core = re.sub(r"[^\w/-]", "", w).upper()
        if core in ACRONYMS or re.fullmatch(r"[A-Z]*\d[\w-]*", core or "x"):
            out.append(w.upper())
        elif i and w.lower() in SMALL:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def _day(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def slim(b):
    return {"county": b.get("county") or "", "agency": b.get("agency") or "", "title": nice_title(b.get("title")),
            "category": b.get("category") or "", "due": (b.get("due") or "")[:10],
            "url": b.get("bid_url") or b.get("source_url") or SITE}


def pick_highlights(bids, today, n=4):
    """The bids worth showing: still open long enough to respond, readable titles, one per county."""
    def score(b):
        due = _day(b.get("due"))
        t = b.get("title") or ""
        return ((due is not None and due >= today + timedelta(days=5)),
                25 <= len(t) <= 110,
                b.get("category") not in ("", "Other"),
                due or date.max)
    ranked = sorted(bids, key=score, reverse=True)
    out, counties = [], set()
    for b in ranked:
        if b.get("county") in counties:
            continue
        out.append(b)
        counties.add(b.get("county"))
        if len(out) == n:
            break
    if len(out) < n:                                             # few counties today: allow repeats
        out += [b for b in ranked if b not in out][: n - len(out)]
    return out


def build(bids, today: date):
    wd = today.weekday()                                         # Mon=0 … Sun=6
    week = today.isocalendar()[1]
    new_today = [b for b in bids if _day(b.get("first_seen")) == today]
    new_week = [b for b in bids if (d := _day(b.get("first_seen"))) and today - timedelta(days=6) <= d <= today]
    closing = sorted([b for b in bids if (d := _day(b.get("due"))) and today <= d <= today + timedelta(days=7)],
                     key=lambda b: b["due"])
    # what to show on a "closing" card: still time to act (due in 2-7 days), one per county, soonest first
    actionable = [b for b in closing if _day(b["due"]) >= today + timedelta(days=2)] or closing
    closing_show = sorted(pick_highlights(actionable, today, 5), key=lambda b: b["due"])
    open_n = len(bids)
    nice_date = f"{today:%A, %B} {today.day}"

    # ---- morning: today's new bids (falls back to closing-soon on a day with nothing new)
    hl = pick_highlights(new_today, today)
    if new_today:
        n_c = len({b.get("county") for b in new_today})
        am = {"theme": "new_today", "headline": f"{len(new_today)} new Florida bid{'s' * (len(new_today) != 1)} today",
              "count": len(new_today), "counties": n_c, "items": [slim(b) for b in hl]}
        cap = (f"🦎 {len(new_today)} new government bids posted in Florida today, across {n_c} "
               f"count{'ies' if n_c != 1 else 'y'}.\n\n"
               + "\n".join(f"📍 {b['county']}: {nice_title(b['title'])}" for b in hl[:3])
               + f"\n\nAll {open_n} open bids, free, updated every morning 👉 {SITE}\n\n#FloridaBids #GovernmentContracts #RFP #SmallBusiness")
    else:
        am = {"theme": "closing_soon", "headline": f"{len(closing)} bids close this week", "count": len(closing),
              "items": [slim(b) for b in closing_show[:4]]}
        cap = (f"⏰ {len(closing)} Florida government bids close in the next 7 days.\n\n"
               + "\n".join(f"📍 {b['county']}: {nice_title(b['title'])} (due {_day(b['due']):%b} {_day(b['due']).day})" for b in closing_show[:3])
               + f"\n\nSee them all 👉 {SITE}\n\n#FloridaBids #GovernmentContracts #RFP")
    am["caption_default"] = cap

    # ---- afternoon: rotating theme
    counties = [c for c, _ in Counter(b.get("county") for b in new_week).most_common(5) if c]
    cats = [c for c, _ in Counter(b.get("category") for b in new_week).most_common(6) if c and c != "Other"]
    if wd in (0, 3) or not new_week:
        pm = {"theme": "closing_soon", "headline": "Closing this week", "count": len(closing),
              "items": [slim(b) for b in closing_show]}
        pcap = (f"⏰ Last call: {len(closing)} Florida bids close in the next 7 days. Don't miss a deadline.\n\n"
                + "\n".join(f"• {b['county']}: {nice_title(b['title'])} (due {_day(b['due']):%b} {_day(b['due']).day})" for b in closing_show[:4])
                + f"\n\nFull list 👉 {SITE}")
    elif wd == 1 and counties:
        c = counties[week % len(counties)]
        pool = [b for b in bids if b.get("county") == c]
        pm = {"theme": "county_spotlight", "headline": f"{c} County", "subject": c,
              "count": len(pool), "new_this_week": sum(b.get("county") == c for b in new_week),
              "items": [slim(b) for b in pick_highlights(pool, today, 99)[:5]]}
        pcap = (f"📍 County spotlight: {c}. {pm['count']} open bids right now, {pm['new_this_week']} posted this week.\n\n"
                + "\n".join(f"• {i['title']}" for i in pm["items"][:4]) + f"\n\nEvery {c} bid 👉 {SITE}")
    elif wd in (2, 5) and cats:
        c = cats[(week + (wd == 5)) % len(cats)]
        pool = [b for b in bids if b.get("category") == c]
        ranked = sorted(pick_highlights(pool, today, 99), key=lambda b: b.get("county") or "")
        pm = {"theme": "category_spotlight", "headline": c, "subject": c, "count": len(pool),
              "new_this_week": sum(b.get("category") == c for b in new_week),
              "items": [slim(b) for b in pick_highlights(pool, today, 5)]}
        pcap = (f"🔎 {c}: {pm['count']} open Florida bids, {pm['new_this_week']} new this week.\n\n"
                + "\n".join(f"• {i['county']}: {i['title']}" for i in pm["items"][:4]) + f"\n\nFilter by your business 👉 {SITE}")
    else:                                                        # Friday (and fallbacks): the week in numbers
        top = Counter(b.get("county") for b in new_week).most_common(6)
        pm = {"theme": "week_recap", "headline": "This week in Florida bids", "count": len(new_week),
              "counties": [{"county": c, "new": n} for c, n in top if c], "open": open_n}
        pcap = (f"📊 This week: {len(new_week)} new Florida government bids.\n\n"
                + "\n".join(f"• {c}: {n} new" for c, n in top[:5] if c)
                + f"\n\nGet them in your inbox every morning, free 👉 {SITE}")
    pm["caption_default"] = pcap

    return {
        "date": today.isoformat(), "weekday": f"{today:%A}", "nice_date": nice_date,
        "post_days": "Mon-Sat", "posts_today": wd != 6,
        "stats": {"open": open_n, "new_today": len(new_today), "new_this_week": len(new_week),
                  "closing_7_days": len(closing)},
        "am": am, "pm": pm,
        "video": {"note": "Pick 2-3 of these for the script: interesting to a small business, still time to respond.",
                  "highlights": [slim(b) for b in pick_highlights(new_today or new_week, today, 6)]},
        "new_today": [slim(b) for b in sorted(new_today, key=lambda b: (b.get("county") or "", b.get("due") or ""))][:80],
        "closing_soon": [slim(b) for b in closing[:25]],
    }

# ---------------------------------------------------------------- images

def _data_uri(p: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def _css():
    f = ASSETS / "fonts"
    faces = "".join(
        f"@font-face{{font-family:'{fam}';font-weight:{w};src:url({_data_uri(f / file, 'font/woff2')}) format('woff2')}}"
        for fam, w, file in [("Plex", 400, "ibm-plex-sans-latin-400-normal.woff2"),
                             ("Plex", 500, "ibm-plex-sans-latin-500-normal.woff2"),
                             ("Plex", 600, "ibm-plex-sans-latin-600-normal.woff2"),
                             ("Serif", 600, "source-serif-4-latin-600-normal.woff2"),
                             ("Serif", 700, "source-serif-4-latin-700-normal.woff2")])
    return faces + """
*{box-sizing:border-box;margin:0}
body{width:1080px;height:1350px;background:#fbf6ec;color:#14211e;font-family:Plex,sans-serif;display:flex;flex-direction:column}
.top{padding:64px 72px 0;display:flex;justify-content:space-between;align-items:center;font-size:30px;font-weight:600;letter-spacing:.06em}
.brand{color:#0d5c50;text-transform:uppercase}.date{color:#5a6a66;font-weight:500;letter-spacing:0}
.hero{padding:44px 72px 8px}
.kicker{font-size:30px;color:#9a5b00;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px}
.big{font-family:Serif,serif;font-weight:700;font-size:200px;line-height:.9;color:#0d5c50}
.h1{font-family:Serif,serif;font-weight:700;font-size:84px;line-height:1.02;color:#0d5c50}
.sub{font-size:36px;color:#14211e;margin-top:14px;font-weight:500}
.list{padding:26px 72px 0;display:flex;flex-direction:column;gap:18px;flex:1;overflow:hidden}
.row{background:#fff;border:2px solid #e3e8e3;border-radius:22px;padding:22px 28px}
.meta{display:flex;gap:14px;align-items:center;font-size:24px;color:#5a6a66;margin-bottom:8px}
.pill{background:#e1efeb;color:#0d5c50;font-weight:600;border-radius:999px;padding:4px 16px}
.due{margin-left:auto;font-weight:600;color:#9a5b00}
.t{font-size:32px;line-height:1.22;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.bars{padding:48px 72px 0;display:flex;flex-direction:column;gap:36px;flex:1}
.bar{display:grid;grid-template-columns:300px 1fr 90px;align-items:center;font-size:40px;font-weight:500;gap:20px}
.fill{height:44px;background:#0d5c50;border-radius:12px}.n{text-align:right;font-weight:600;color:#0d5c50}
.foot{margin-top:22px;background:#0d5c50;color:#fff;display:flex;align-items:center;gap:30px;padding:0 72px 0 40px;height:210px}
.foot img{height:190px;align-self:flex-end;border-radius:24px 24px 0 0}
.url{font-family:Serif,serif;font-size:58px;font-weight:700}.tag{font-size:28px;opacity:.9;margin-top:6px}
"""


def _rows(items, show_due=True):
    e = html.escape
    out = []
    for i in items:
        d = _day(i.get("due"))
        due = f'<span class="due">Due {d:%b} {d.day}</span>' if (d and show_due) else ""
        out.append(f'<div class="row"><div class="meta"><span class="pill">{e(i["county"])}</span>'
                   f'<span>{e(i["agency"][:40])}</span>{due}</div><div class="t">{e(i["title"])}</div></div>')
    return "".join(out)


def card_html(slot: dict, nice_date: str, open_n: int) -> str:
    e = html.escape
    th = slot["theme"]
    if th == "new_today":
        hero = (f'<div class="kicker">New today</div><div class="big">{slot["count"]}</div><div class="sub">government bids posted in '
                f'{slot["counties"]} Florida count{"ies" if slot["counties"] != 1 else "y"}</div>')
        body = f'<div class="list">{_rows(slot["items"])}</div>'
    elif th == "closing_soon":
        hero = (f'<div class="kicker">Don\'t miss the deadline</div><div class="h1">{slot["count"]} bids close<br>this week</div>')
        body = f'<div class="list">{_rows(slot["items"][:4])}</div>'
    elif th in ("county_spotlight", "category_spotlight"):
        kick = "County spotlight" if th == "county_spotlight" else "Industry spotlight"
        hero = (f'<div class="kicker">{kick}</div><div class="h1">{e(slot["headline"])}</div>'
                f'<div class="sub">{slot["count"]} open bids · {slot["new_this_week"]} new this week</div>')
        body = f'<div class="list">{_rows(slot["items"][:4])}</div>'
    else:                                                        # week_recap
        mx = max([c["new"] for c in slot["counties"]] or [1])
        bars = "".join(f'<div class="bar"><span>{e(c["county"])}</span><div class="fill" style="width:{max(4, 100 * c["new"] / mx):.0f}%"></div>'
                       f'<span class="n">{c["new"]}</span></div>' for c in slot["counties"])
        hero = (f'<div class="kicker">The week in Florida bids</div><div class="big">{slot["count"]}</div>'
                f'<div class="sub">new government bids this week · {open_n} open now</div>')
        body = f'<div class="bars">{bars}</div>'
    iggy = _data_uri(ASSETS / "assets" / "iggy.png", "image/png")
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{_css()}</style></head><body>"
            f'<div class="top"><span class="brand">Florida Bids</span><span class="date">{e(nice_date)}</span></div>'
            f'<div class="hero">{hero}</div>{body}'
            f'<div class="foot"><img src="{iggy}"><div><div class="url">floridabids.org</div>'
            f'<div class="tag">Every open Florida bid. Free, every morning.</div></div></div></body></html>')


def render(pages: dict[Path, str]):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
        for path, doc in pages.items():
            page.set_content(doc, wait_until="load")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(path), type="jpeg", quality=90, full_page=False)
        browser.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Eastern)")
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args(argv)
    today = date.fromisoformat(args.date) if args.date else datetime.now(ET).date()

    bids = json.loads(BIDS.read_text())["bids"]
    data = build(bids, today)
    OUT.mkdir(parents=True, exist_ok=True)
    for slot in ("am", "pm"):
        data[slot]["image"] = f"social/{today}-{slot}.jpg"
        data[slot]["image_url"] = f"{SITE}/social/{today}-{slot}.jpg"
    if not args.no_images:
        render({OUT / f"{today}-{s}.jpg": card_html(data[s], data["nice_date"], data["stats"]["open"]) for s in ("am", "pm")})
    (OUT / "today.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    for old in OUT.glob("*.jpg"):                                # keep two weeks of card images
        d = _day(old.name)
        if d and d < today - timedelta(days=KEEP_DAYS):
            old.unlink()
    print(f"social: {data['stats']['new_today']} new today; am={data['am']['theme']} pm={data['pm']['theme']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
