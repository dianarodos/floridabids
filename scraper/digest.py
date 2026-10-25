"""Send the daily / weekly email to confirmed subscribers (run by the daily GitHub job after run.py).

    python -m scraper.digest              # daily list every day, weekly list on Mondays (Eastern)
    python -m scraper.digest --dry-run    # build the emails, print a summary, send nothing
    python -m scraper.digest --to me@x.com --freq weekly   # send one test email to one address

Needs env: BREVO_API_KEY, ADMIN_TOKEN, SITE_URL (default https://floridabids.org),
FROM_EMAIL (default list@floridabids.org).
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

from .models import ET, now_et

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
DAILY_LIMIT = 290            # Brevo free plan allows 300 emails a day; keep a little room for confirmations
log = logging.getLogger("digest")


def _d(iso: str):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso if "T" in iso else iso + "T00:00:00")
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=ET)


def pick(bids, freq, now):
    window = timedelta(days=1 if freq == "daily" else 7)
    since = now - window - timedelta(hours=2)
    new = [b for b in bids if (_d(b.get("posted")) or _d(b.get("first_seen")) or now) >= since]
    soon = [b for b in bids if b.get("due") and now <= (_d(b["due"]) or now) <= now + timedelta(days=7)]
    new.sort(key=lambda b: b.get("due") or "9999")
    soon.sort(key=lambda b: b.get("due") or "9999")
    return new, soon


def _row(b, site):
    due = _d(b.get("due"))
    due_s = due.strftime("%b %-d") if due else "—"
    link = b.get("bid_url") or b.get("source_url") or site
    e = html.escape
    return (f'<tr><td style="padding:8px 10px;border-bottom:1px solid #e3e8e6;vertical-align:top">'
            f'<a href="{e(link)}" style="color:#0d5c50;font-weight:bold;text-decoration:none">{e(b["title"])}</a>'
            f'<div style="color:#5b6b67;font-size:13px">{e(b.get("agency",""))} &middot; {e(b.get("county",""))} County'
            f' &middot; {e(b.get("category",""))}</div></td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #e3e8e6;white-space:nowrap;vertical-align:top;'
            f'font-family:monospace">{due_s}</td></tr>')


def build(bids, meta, freq, site, unsub_url, now):
    new, soon = pick(bids, freq, now)
    label = "today" if freq == "daily" else "this week"
    e = html.escape

    def table(rows, limit):
        if not rows:
            return '<p style="color:#5b6b67">None.</p>'
        body = "".join(_row(b, site) for b in rows[:limit])
        more = (f'<p style="font-size:13px;color:#5b6b67">…and {len(rows) - limit} more on '
                f'<a href="{site}" style="color:#0d5c50">floridabids.org</a> and in the attached Excel file.</p>'
                if len(rows) > limit else "")
        return f'<table style="border-collapse:collapse;width:100%;font-size:14px">{body}</table>{more}'

    subject = (f"Florida bids {label}: {len(new)} new, {meta.get('total', len(bids))} open"
               if new else f"Florida bids {label}: {meta.get('total', len(bids))} open")
    html_body = f"""<div style="font-family:Arial,Helvetica,sans-serif;color:#1b2b28;max-width:680px;line-height:1.45">
<h1 style="font-family:Georgia,serif;font-size:26px;margin:0 0 4px">Florida Bids</h1>
<p style="margin:0 0 16px;color:#5b6b67">{e(now.strftime('%A, %B %-d, %Y'))} &middot; <b>{meta.get('total', len(bids))}</b> open bids
 across <b>{meta.get('counties', '')}</b> counties. The full list is attached as Excel.</p>
<h2 style="font-size:18px;margin:18px 0 6px">New {label} ({len(new)})</h2>
{table(new, 60)}
<h2 style="font-size:18px;margin:22px 0 6px">Closing in the next 7 days ({len(soon)})</h2>
{table(soon, 30)}
<p style="margin-top:22px"><a href="{site}" style="display:inline-block;background:#0d5c50;color:#fff;padding:10px 16px;
border-radius:6px;text-decoration:none;font-weight:bold">See every open bid</a></p>
<p style="font-size:12px;color:#5b6b67;margin-top:24px">Always confirm details and deadlines on the agency's page before
 you respond. You get this {'every morning' if freq == 'daily' else 'every Monday'} because you signed up at floridabids.org.
 No ads, ever. <a href="{e(unsub_url)}" style="color:#5b6b67">Unsubscribe</a> with one click.</p></div>"""
    text = (f"Florida Bids - {meta.get('total', len(bids))} open bids. New {label}: {len(new)}.\n\n"
            + "\n".join(f"- {b['title']} ({b.get('agency','')}, due {(b.get('due') or '')[:10]}) "
                        f"{b.get('bid_url') or b.get('source_url') or ''}" for b in new[:60])
            + f"\n\nAll open bids: {site}\nUnsubscribe: {unsub_url}\n")
    return subject, html_body, text


def send(api_key, sender, to, subject, html_body, text, unsub_url, attachment):
    payload = {
        "sender": sender, "to": [{"email": to}], "subject": subject,
        "htmlContent": html_body, "textContent": text, "tags": ["digest"],
        "headers": {"List-Unsubscribe": f"<{unsub_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
    }
    if attachment:
        payload["attachment"] = [attachment]
    r = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, timeout=30,
                      headers={"api-key": api_key, "accept": "application/json"})
    if r.status_code >= 300:
        raise RuntimeError(f"Brevo {r.status_code}: {r.text[:300]}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--to", help="send one test email to this address")
    ap.add_argument("--freq", choices=["daily", "weekly"])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    site = os.environ.get("SITE_URL", "https://floridabids.org").rstrip("/")
    api_key, admin = os.environ.get("BREVO_API_KEY", ""), os.environ.get("ADMIN_TOKEN", "")
    sender = {"email": os.environ.get("FROM_EMAIL", "list@floridabids.org"), "name": "Florida Bids"}
    if not args.dry_run and not (api_key and admin):
        log.info("BREVO_API_KEY / ADMIN_TOKEN not set; not sending emails")
        return 0

    data = json.loads((DATA / "bids.json").read_text())
    bids, meta = data["bids"], data["meta"]
    xlsx = DATA / "florida-open-bids.xlsx"
    attachment = ({"name": f"florida-open-bids-{now_et():%Y-%m-%d}.xlsx",
                   "content": base64.b64encode(xlsx.read_bytes()).decode()} if xlsx.exists() else None)
    now = now_et()

    freqs = [args.freq] if args.freq else (["daily", "weekly"] if now.weekday() == 0 else ["daily"])
    if args.to:
        freqs = freqs[:1]
        recipients = {freqs[0]: [{"email": args.to, "token": "test"}]}
    else:
        recipients = {}
        for f in freqs:
            r = requests.get(f"{site}/api/admin/subscribers", params={"freq": f}, timeout=30,
                             headers={"Authorization": f"Bearer {admin}"})
            r.raise_for_status()
            recipients[f] = r.json()["subscribers"]

    sent = failed = 0
    for f in freqs:
        for sub in recipients.get(f, []):
            if sent >= DAILY_LIMIT:
                log.warning("daily sending limit reached; %s subscribers not emailed today",
                            sum(len(v) for v in recipients.values()) - sent - failed)
                return 0
            unsub = f"{site}/api/unsubscribe?t={sub['token']}"
            subject, html_body, text = build(bids, meta, f, site, unsub, now)
            if args.dry_run:
                log.info("[dry run] %s -> %s: %s", f, sub["email"], subject)
                sent += 1
                continue
            try:
                send(api_key, sender, sub["email"], subject, html_body, text, unsub, attachment)
                sent += 1
            except Exception as e:      # one bad address must not stop the rest
                failed += 1
                log.error("could not email %s: %s", sub["email"], e)
    log.info("digest: %d sent, %d failed (%s)", sent, failed, ", ".join(freqs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
