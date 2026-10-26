"""Status email for Diana after each daily run: what was read, what wasn't, and what changed.

Sent after every scheduled daily run (the workflow passes --always), and on test runs only when
something needs attention. Includes coverage: every Florida county, its agencies, the source each is
read from, whether it was read today, and the counties with no source yet.

    python -m scraper.report            # decide by day / problems
    python -m scraper.report --always   # send the full report now

Env: BREVO_API_KEY, REPORT_EMAIL (where to send), FROM_EMAIL.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import requests
import yaml

from .models import now_et
from .readers import FL_COUNTIES as _FL

FL_COUNTIES = sorted(_FL)

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("report")
LABEL = {"ok": "Read", "empty": "Read, nothing open", "blocked": "Site refuses us", "error": "Broken",
         "timeout": "Too slow", "skipped": "Skipped (out of time)"}
COLOR = {"ok": "#0d5c50", "empty": "#5b6b67", "blocked": "#9a6700", "error": "#b42318",
         "timeout": "#b42318", "skipped": "#9a6700"}


def previous_sources():
    """Yesterday's source statuses, from the last committed version of data/bids.json."""
    try:
        old = subprocess.run(["git", "show", "HEAD:data/bids.json"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
        return {s["id"]: s for s in json.loads(old)["meta"].get("sources", [])}
    except Exception:
        return {}


def coverage(meta, bids, cfg):
    """Every Florida county -> [(agency, source, ok, note)], and the counties with nothing at all."""
    per = {c: [] for c in FL_COUNTIES}
    n_bids = Counter((b["county"], b["agency"]) for b in bids)
    seen = set()

    def add(county, agency, source, ok, note):
        per.setdefault(county, []).append((agency, source, ok, note))
        seen.add((county, agency.lower()))

    for s in meta.get("sources", []):
        st = s["status"]
        note = (f'{s.get("count", 0)} open' if st == "ok" else LABEL.get(st, st))
        add(s["county"], s["agency"], _platform(s["url"]), st in ("ok", "empty"), note)
    inbox_ok = (meta.get("email") or {}).get("status") == "ok"
    alerts = cfg.get("alerts", {})
    for kind, table in (("OpenGov alerts", alerts.get("opengov") or {}), ("Bonfire alerts", alerts.get("bonfire") or {}),
                        ("Bonfire alerts", {v[2] if len(v) > 2 else k: v for k, v in (alerts.get("bonfire_names") or {}).items()})):
        for county, agency in (v[:2] for v in table.values()):
            if (county, agency.lower()) in seen:
                continue
            n = n_bids.get((county, agency), 0)
            add(county, agency, kind, inbox_ok, (f"{n} open" if n else "nothing open") + ("" if inbox_ok else " (inbox not read)"))
    direct_ids = {s["id"] for s in meta.get("sources", [])}
    copies = Counter((b["county"], b["agency"]) for b in bids if b.get("source_id") not in direct_ids)
    for (county, agency), n in copies.items():
        if (county, agency.lower()) not in seen:
            add(county, agency, "Pasted by hand", False, f"{n} open, not refreshed daily")
    for s in cfg.get("skipped") or []:
        add(s["county"], s["agency"], _platform(s["url"]), False, "Skipped: " + s["reason"])
    missing = [c for c in FL_COUNTIES if not per.get(c)]
    return per, missing


def _platform(url):
    host = (url or "").split("/")[2].lower() if "//" in (url or "") else ""
    for key, name in (("bidnetdirect", "BidNet"), ("demandstar", "DemandStar"), ("opengov", "OpenGov"),
                      ("bonfirehub", "Bonfire"), ("planetbids", "PlanetBids"), ("vendorlink", "VendorLink"),
                      ("ionwave", "IonWave"), ("bidsandtenders", "Bids&Tenders"), ("infor", "Infor"),
                      ("oracle", "Oracle"), ("vendorregistry", "VendorRegistry")):
        if key in host:
            return name
    return "Own website"


def coverage_html(per, missing):
    e = html.escape
    ok_mark = '<span style="color:#0d5c50;font-weight:bold">&#10003;</span>'
    bad_mark = '<span style="color:#b42318;font-weight:bold">&#10007;</span>'
    have = [c for c in FL_COUNTIES if per.get(c)]
    out = [f'<h3 style="font-size:15px;margin:22px 0 4px">Counties with no source yet ({len(missing)} of {len(FL_COUNTIES)})</h3>',
           f'<p style="margin:0 0 6px">{e(", ".join(missing)) if missing else "None, every county has at least one source."}</p>',
           f'<h3 style="font-size:15px;margin:22px 0 6px">Coverage by county ({len(have)} counties)</h3>',
           '<table style="border-collapse:collapse;font-size:13px;width:100%"><tr style="text-align:left;color:#5b6b67">'
           '<th style="padding:4px 8px">County</th><th style="padding:4px 8px">Agency</th>'
           '<th style="padding:4px 8px">Source</th><th style="padding:4px 8px">Read today</th></tr>']
    for c in have:
        rows = sorted(per[c], key=lambda r: r[0].lower())
        for i, (agency, source, ok, note) in enumerate(rows):
            top = "border-top:2px solid #cfd8d5;" if i == 0 else ""
            out.append(f'<tr><td style="padding:4px 8px;{top}font-weight:bold;vertical-align:top">{e(c) if i == 0 else ""}</td>'
                       f'<td style="padding:4px 8px;{top}border-bottom:1px solid #eee">{e(agency)}</td>'
                       f'<td style="padding:4px 8px;{top}border-bottom:1px solid #eee">{e(source)}</td>'
                       f'<td style="padding:4px 8px;{top}border-bottom:1px solid #eee">{ok_mark if ok else bad_mark} '
                       f'<span style="color:#5b6b67">{e(note)}</span></td></tr>')
    out.append("</table>")
    return "".join(out)


def build(meta, prev, cov=""):
    sources = meta.get("sources", [])
    by = Counter(s["status"] for s in sources)
    newly_broken = [s for s in sources if s["status"] in ("error", "timeout", "blocked")
                    and prev.get(s["id"], {}).get("status") == "ok"]
    went_empty = [s for s in sources if s["status"] == "empty" and (prev.get(s["id"], {}).get("count") or 0) > 0]
    fixed = [s for s in sources if s["status"] == "ok" and prev.get(s["id"], {}).get("status") in ("error", "timeout")]
    email = meta.get("email", {})
    attention = newly_broken or went_empty or email.get("status") == "error"
    e = html.escape

    def lst(title, items, note=""):
        if not items:
            return ""
        li = "".join(f'<li>{e(s["agency"])} ({e(s["county"])}){(" - " + e(str(s.get("error", ""))[:140])) if s.get("error") else ""}</li>'
                     for s in items)
        return f'<h3 style="font-size:15px;margin:16px 0 4px">{title}</h3>{note}<ul style="margin:0;padding-left:18px">{li}</ul>'

    summary = " · ".join(f"{n} {LABEL.get(k, k).lower()}" for k, n in by.most_common())
    em = (f'Alert inbox: {email.get("status")}, {email.get("messages", 0)} emails read, '
          f'{email.get("bids", 0)} bids found, {email.get("unparsed", 0)} not understood.')
    body = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#1b2b28;max-width:720px">
<h2 style="font-family:Georgia,serif;margin:0 0 6px">Florida Bids daily check</h2>
<p style="margin:0 0 10px;color:#5b6b67">{e(meta.get('updated', ''))} Eastern · <b>{meta.get('total')}</b> open bids in
 <b>{meta.get('counties')}</b> counties · {meta.get('removed_today', 0)} closed bids removed</p>
<p style="margin:0 0 6px"><b>{len(sources)} sites:</b> {e(summary)}</p>
<p style="margin:0 0 6px">{e(em)}</p>
{lst("Started failing today", newly_broken)}
{lst("Had bids yesterday, empty today", went_empty, '<p style="margin:0;color:#5b6b67;font-size:13px">Often fine (bids closed), but worth a look if it lasts.</p>')}
{lst("Working again", fixed)}
{cov}</div>"""
    subject = (f"Florida Bids: {len(newly_broken)} site(s) broke" if newly_broken
               else "Florida Bids: check empty sites" if went_empty
               else "Florida Bids: alert inbox problem" if email.get("status") == "error"
               else f"Florida Bids daily check: {by.get('ok', 0) + by.get('empty', 0)} of {len(sources)} sites read")
    return subject, body, attention


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--always", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    to, key = os.environ.get("REPORT_EMAIL", ""), os.environ.get("BREVO_API_KEY", "")
    if not (to and key):
        log.info("REPORT_EMAIL / BREVO_API_KEY not set; no report sent")
        return 0
    data = json.loads((ROOT / "data" / "bids.json").read_text())
    meta = data["meta"]
    bids = data.get("bids", [])
    meta.setdefault("total", len(bids))
    meta.setdefault("counties", len({b["county"] for b in bids}))
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
    per, missing = coverage(meta, data.get("bids", []), cfg)
    subject, body, attention = build(meta, previous_sources(), coverage_html(per, missing))
    if not (args.always or attention or now_et().weekday() == 0):
        log.info("nothing needs attention today; report not sent")
        return 0
    r = requests.post("https://api.brevo.com/v3/smtp/email", timeout=30,
                      headers={"api-key": key, "accept": "application/json"},
                      json={"sender": {"email": os.environ.get("FROM_EMAIL", "list@floridabids.org"), "name": "Florida Bids"},
                            "to": [{"email": to}], "subject": subject, "htmlContent": body, "tags": ["report"]})
    log.info("report %s: %s", "sent" if r.ok else "failed", r.status_code if r.ok else r.text[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
