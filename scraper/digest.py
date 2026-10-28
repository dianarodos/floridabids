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

from .interests import describe, matcher
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


def pick(bids, freq, now, since=None):
    """New = first appeared on floridabids.org since the last email of this kind (fallback: 1 or 7 days)."""
    if since is None:
        since = now - timedelta(days=1 if freq == "daily" else 7)
    new = [b for b in bids if _d(b.get("first_seen")) and _d(b["first_seen"]) > since]
    soon = [b for b in bids if b.get("due") and now <= (_d(b["due"]) or now) <= now + timedelta(days=7)]
    new.sort(key=lambda b: (b.get("county") or "", b.get("due") or "9999"))
    return new, soon


STATE = ROOT / "data" / "digest_state.json"


def _mask(email: str) -> str:
    """The run log is public in the repo: never write a subscriber's address into it."""
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=1))


def _row(b, site, is_new=False):
    due = _d(b.get("due"))
    due_s = due.strftime("%b %-d") if due else "See posting"
    link = b.get("bid_url") or b.get("source_url") or site
    e = html.escape
    return (f'<tr><td style="padding:8px 10px;border-bottom:1px solid #e3e8e6;vertical-align:top">'
            + ('<span style="background:#d9621c;color:#fff;font-size:11px;font-weight:bold;padding:1px 6px;'
               'border-radius:4px;margin-right:6px">NEW</span>' if is_new else "")
            + f'<a href="{e(link)}" style="color:#0d5c50;font-weight:bold;text-decoration:none">{e(b["title"])}</a>'
            f'<div style="color:#5b6b67;font-size:13px">{e(b.get("agency",""))} &middot; {e(b.get("county",""))} County'
            f' &middot; {e(b.get("category",""))}</div></td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #e3e8e6;white-space:nowrap;vertical-align:top;'
            f'font-family:monospace">{due_s}</td></tr>')


def build(bids, meta, freq, site, unsub_url, now, since=None, sub=None):
    new, soon = pick(bids, freq, now, since)
    label = "this morning" if freq == "daily" else "this week"
    e = html.escape
    sub = sub or {}
    prefs_url = f"{site}/preferences.html?t={sub['token']}" if sub.get("token") else site
    match = matcher(sub.get("interests"), sub.get("keywords"))
    new_keys = {id(b) for b in new}         # same dict objects as in bids
    mine = [b for b in bids if match(b)] if match else []
    mine.sort(key=lambda b: (id(b) not in new_keys, b.get("due") or "9999"))   # new ones first, then closing soonest
    mine_new = sum(1 for b in mine if id(b) in new_keys)

    def table(rows, limit, flag=False):
        if not rows:
            return '<p style="color:#5b6b67">None.</p>'
        body = "".join(_row(b, site, flag and id(b) in new_keys) for b in rows[:limit])
        more = (f'<p style="font-size:13px;color:#5b6b67">…and {len(rows) - limit} more on '
                f'<a href="{site}" style="color:#0d5c50">floridabids.org</a> and in the attached Excel file.</p>'
                if len(rows) > limit else "")
        return f'<table style="border-collapse:collapse;width:100%;font-size:14px">{body}</table>{more}'

    if match:
        subject = (f"Florida bids {label}: {len(mine)} open for your business ({mine_new} new), {len(new)} new in Florida")
    else:
        subject = (f"Florida bids {label}: {len(new)} new, {meta.get('total', len(bids))} open"
                   if new else f"Florida bids {label}: {meta.get('total', len(bids))} open")
    total = meta.get("total", len(bids))
    button = (f'<a href="{site}" style="display:inline-block;background:#0d5c50;color:#ffffff;padding:11px 18px;'
              f'border-radius:6px;text-decoration:none;font-weight:bold">See every open bid &rarr;</a>')

    def tile(n, label_):
        return (f'<td style="padding:12px 14px;background:#eef4f2;border-radius:8px;width:33%;text-align:left">'
                f'<div style="font-family:Georgia,serif;font-size:26px;font-weight:bold;color:#0d5c50">{n}</div>'
                f'<div style="font-size:12px;color:#5b6b67;text-transform:uppercase;letter-spacing:.04em">{label_}</div></td>')

    def bars(title, counts, limit=8):
        if not counts:
            return ""
        top = counts.most_common(limit)
        peak = top[0][1]
        rows = "".join(
            f'<tr><td style="padding:3px 8px 3px 0;font-size:13px;white-space:nowrap;width:1%">{e(k)}</td>'
            f'<td style="padding:3px 0;width:100%"><table role="presentation" cellpadding="0" cellspacing="0" '
            f'style="width:{max(4, round(v / peak * 100))}%"><tr><td style="background:#0d5c50;height:12px;'
            f'border-radius:3px;font-size:0;line-height:0">&nbsp;</td></tr></table></td>'
            f'<td style="padding:3px 0 3px 8px;font-size:13px;font-weight:bold;text-align:right;width:1%">{v}</td></tr>'
            for k, v in top)
        rest = sum(counts.values()) - sum(v for _, v in top)
        plural = {"county": "counties", "category": "categories"}.get(title.split()[-1].lower(), "")
        more = f'<div style="font-size:12px;color:#5b6b67">+{rest} more in other {plural}</div>' if rest else ""
        return (f'<td style="vertical-align:top;padding:0 10px 0 0;width:50%">'
                f'<div style="font-size:13px;font-weight:bold;margin:0 0 6px">{title}</div>'
                f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">{rows}</table>{more}</td>')

    from collections import Counter
    by_county = Counter(f'{b.get("county") or "Other"}' for b in new)
    by_cat = Counter(b.get("category") or "Other" for b in new)
    stats = (f'<table role="presentation" cellpadding="0" cellspacing="6" style="width:100%;margin:4px 0 14px"><tr>'
             + (f'{tile(len(mine), "open for your business")}{tile(len(new), "new " + label)}{tile(total, "open in Florida")}'
                if match else
                f'{tile(len(new), "new " + label)}{tile(len(soon), "closing in 7 days")}{tile(total, "open in Florida")}')
             + '</tr></table>')
    charts = (f'<h2 style="font-size:17px;margin:18px 0 8px">Where the new bids are</h2>'
              f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%"><tr>'
              f'{bars("By county", by_county)}{bars("By category", by_cat)}</tr></table>') if new else ""
    pbtn = (f'<a href="{e(prefs_url)}" style="display:inline-block;border:1px solid #0d5c50;color:#0d5c50;padding:7px 14px;'
            f'border-radius:6px;text-decoration:none;font-size:13px;font-weight:bold">%s</a>')
    if match:
        yours = (f'<h2 style="font-size:17px;margin:20px 0 4px">Open bids for your business ({len(mine)})</h2>'
                 f'<p style="font-size:13px;color:#5b6b67;margin:0 0 8px">Matching: {e(describe(sub.get("interests"), sub.get("keywords")))}. '
                 f'Every open bid that matches, new ones first and marked NEW. {pbtn % "Change my business keywords"}</p>'
                 + table(mine, 50, flag=True))
    else:
        yours = (f'<div style="background:#fff4ec;border:1px solid #f0c9a8;border-radius:8px;padding:12px 14px;margin:16px 0 0">'
                 f'<b>Get the bids for your business on top.</b> Tell us what you do (food, automotive, roofing, IT…) or type '
                 f'your own keywords, and every matching open bid will lead this email.<div style="margin-top:8px">'
                 f'{pbtn % "Pick my business keywords"}</div></div>')
    html_body = f"""<div style="font-family:Arial,Helvetica,sans-serif;color:#1b2b28;max-width:680px;line-height:1.45">
<table role="presentation" style="width:100%"><tr>
<td><h1 style="font-family:Georgia,serif;font-size:26px;margin:0">Florida Bids</h1>
<div style="color:#5b6b67;font-size:14px">{e(now.strftime('%A, %B %-d, %Y'))}</div></td>
<td style="text-align:right;vertical-align:middle">{button}</td></tr></table>
{stats}
{yours}
{charts}
<h2 style="font-size:17px;margin:20px 0 6px">All new bids {label} ({len(new)})</h2>
{table(new, 60 if match else 80) if new else '<p style="color:#5b6b67">No new bids since the last email. Every open bid is on the site and in the attached Excel file.</p>'}
<p style="margin:20px 0 0">{button}</p>
<p style="font-size:13px;color:#5b6b67;margin:8px 0 0">The full list of {total} open bids is attached as an Excel file.</p>
<p style="font-size:12px;color:#5b6b67;margin-top:24px">Always confirm details and deadlines on the agency's page before
 you respond. You get this {'every morning' if freq == 'daily' else 'every Monday'} because you signed up at floridabids.org.
 No ads, ever.</p>
<p style="margin:10px 0 0">{pbtn % "Change my business keywords"} <a href="{e(unsub_url)}" style="display:inline-block;border:1px solid #9aa8a4;color:#5b6b67;
padding:7px 14px;border-radius:6px;text-decoration:none;font-size:13px">Unsubscribe</a></p></div>"""
    text = ((f"Open bids for your business ({len(mine)}):\n" + "\n".join(
                f"- {'NEW ' if id(b) in new_keys else ''}{b['title']} ({b.get('agency','')}, due {(b.get('due') or '')[:10]}) "
                f"{b.get('bid_url') or b.get('source_url') or ''}" for b in mine[:40]) + "\n\n" if match else "")
            + f"Florida Bids - {meta.get('total', len(bids))} open bids. All new {label}: {len(new)}.\n\n"
            + "\n".join(f"- {b['title']} ({b.get('agency','')}, due {(b.get('due') or '')[:10]}) "
                        f"{b.get('bid_url') or b.get('source_url') or ''}" for b in new[:60])
            + f"\n\nAll open bids: {site}\nChange your business keywords: {prefs_url}\nUnsubscribe: {unsub_url}\n")
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
    ap.add_argument("--to-sha256", help="send one test email to the subscriber whose address hashes to this "
                                        "(keeps the address out of the public run log); uses their saved keywords")
    ap.add_argument("--freq", choices=["daily", "weekly"])
    ap.add_argument("--interests", help="test email: business type ids, comma-separated (e.g. food,automotive)")
    ap.add_argument("--keywords", help="test email: free keywords (e.g. 'window tint, catering')")
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
    if args.to_sha256:
        import hashlib
        api = os.environ.get("API_URL", site).rstrip("/")
        r = requests.get(f"{api}/api/admin/subscribers", timeout=30,
                         headers={"Authorization": f"Bearer {admin}", "User-Agent": "FloridaBids-digest/1.0"})
        r.raise_for_status()
        sub = next((x for x in r.json()["subscribers"]
                    if hashlib.sha256(x["email"].strip().lower().encode()).hexdigest() == args.to_sha256.strip().lower()), None)
        if not sub:
            log.error("no active subscriber matches that hash")
            return 1
        args.to = sub["email"]
        freqs = [sub.get("freq") or "daily"]
        recipients = {freqs[0]: [sub]}
        log.info("test email to %s (keywords: %s)", _mask(sub["email"]), describe(sub.get("interests"), sub.get("keywords")) or "none")
    elif args.to:
        freqs = freqs[:1]
        recipients = {freqs[0]: [{"email": args.to, "token": "test", "interests": args.interests.split(",") if args.interests else [],
                                  "keywords": args.keywords or ""}]}
    else:
        recipients = {}
        for f in freqs:
            # go through the workers.dev address: Cloudflare's bot protection on floridabids.org blocks
            # requests from GitHub's servers, while workers.dev reaches the same Worker directly
            api = os.environ.get("API_URL", site).rstrip("/")
            r = requests.get(f"{api}/api/admin/subscribers", params={"freq": f}, timeout=30,
                             headers={"Authorization": f"Bearer {admin}", "User-Agent": "FloridaBids-digest/1.0"})
            r.raise_for_status()
            recipients[f] = r.json()["subscribers"]

    state = load_state()
    sent = failed = 0
    for f in freqs:
        since = _d(state.get(f, ""))
        new_count = len(pick(bids, f, now, since)[0])
        if f == "daily" and new_count == 0 and not args.to:
            log.info("no new bids since the last daily email; daily email skipped")
            continue
        for sub in recipients.get(f, []):
            if sent >= DAILY_LIMIT:
                log.warning("daily sending limit reached; %s subscribers not emailed today",
                            sum(len(v) for v in recipients.values()) - sent - failed)
                return 0
            unsub = f"{site}/api/unsubscribe?t={sub['token']}"
            subject, html_body, text = build(bids, meta, f, site, unsub, now, since, sub)
            if args.dry_run:
                log.info("[dry run] %s -> %s: %s", f, _mask(sub["email"]), subject)
                sent += 1
                continue
            try:
                send(api_key, sender, sub["email"], subject, html_body, text, unsub, attachment)
                sent += 1
            except Exception as e:      # one bad address must not stop the rest
                failed += 1
                log.error("could not email %s: %s", _mask(sub["email"]), str(e).replace(sub["email"], _mask(sub["email"])))
        if not args.dry_run and not args.to:
            state[f] = now.isoformat(timespec="minutes")   # next email lists what's new after this one
    if not args.dry_run and not args.to:
        save_state(state)
    log.info("digest: %d sent, %d failed (%s)", sent, failed, ", ".join(freqs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
