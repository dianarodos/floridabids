"""Status email for Diana after each daily run: what was read, what wasn't, and what changed.

Sent every Monday as a full report, and on other days only when something needs attention
(a source started failing, a source that usually has bids came back empty, the inbox step failed).

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

from .models import now_et

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


def build(meta, prev):
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

    rows = "".join(
        f'<tr><td style="padding:4px 8px;border-bottom:1px solid #eee">{e(s["agency"])}</td>'
        f'<td style="padding:4px 8px;border-bottom:1px solid #eee">{e(s["county"])}</td>'
        f'<td style="padding:4px 8px;border-bottom:1px solid #eee;color:{COLOR.get(s["status"], "#333")}">'
        f'{LABEL.get(s["status"], s["status"])}</td>'
        f'<td style="padding:4px 8px;border-bottom:1px solid #eee;text-align:right">{s.get("count", "")}</td></tr>'
        for s in sorted(sources, key=lambda s: (s["status"] == "ok", s["status"], s["county"])))
    summary = " · ".join(f"{n} {LABEL.get(k, k).lower()}" for k, n in by.most_common())
    em = (f'Alert inbox: {email.get("status")}, {email.get("messages", 0)} emails read, '
          f'{email.get("bids", 0)} bids found, {email.get("unparsed", 0)} not understood.')
    body = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#1b2b28;max-width:720px">
<h2 style="font-family:Georgia,serif;margin:0 0 6px">Florida Bids run report</h2>
<p style="margin:0 0 10px;color:#5b6b67">{e(meta.get('updated', ''))} Eastern · <b>{meta.get('total')}</b> open bids in
 <b>{meta.get('counties')}</b> counties · {meta.get('removed_today', 0)} closed bids removed</p>
<p style="margin:0 0 6px"><b>{len(sources)} sites:</b> {e(summary)}</p>
<p style="margin:0 0 6px">{e(em)}</p>
{lst("Started failing today", newly_broken)}
{lst("Had bids yesterday, empty today", went_empty, '<p style="margin:0;color:#5b6b67;font-size:13px">Often fine (bids closed), but worth a look if it lasts.</p>')}
{lst("Working again", fixed)}
<h3 style="font-size:15px;margin:18px 0 6px">Every site</h3>
<table style="border-collapse:collapse;font-size:13px;width:100%"><tr style="text-align:left;color:#5b6b67">
<th style="padding:4px 8px">Agency</th><th style="padding:4px 8px">County</th><th style="padding:4px 8px">Result</th>
<th style="padding:4px 8px;text-align:right">Bids</th></tr>{rows}</table></div>"""
    subject = (f"Florida Bids: {len(newly_broken)} site(s) broke" if newly_broken
               else "Florida Bids: check empty sites" if went_empty
               else "Florida Bids: alert inbox problem" if email.get("status") == "error"
               else f"Florida Bids weekly report: {by.get('ok', 0)} of {len(sources)} sites read")
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
    meta = json.loads((ROOT / "data" / "bids.json").read_text())["meta"]
    subject, body, attention = build(meta, previous_sources())
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
