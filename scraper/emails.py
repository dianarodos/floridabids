"""Read bid alert emails from the alerts Gmail inbox (IMAP + app password).

Each new message is matched to a platform parser. Bids found are upserted into the store.
Messages no parser understands are saved under data/unparsed/ so the parsers can be improved.

Environment: ALERTS_EMAIL, ALERTS_APP_PASSWORD.

NOTE: the OpenGov and Bonfire parsers are first drafts written before any real alert arrived.
They key on the project links in the email, which is the most stable part. Tune them with real samples.
"""
from __future__ import annotations

import email
import imaplib
import json
import logging
import os
import re
from email.header import decode_header, make_header
from pathlib import Path

from bs4 import BeautifulSoup

from .dates import parse_due
from .models import Bid
from .readers import make_bid

log = logging.getLogger(__name__)
DATA = Path(__file__).resolve().parent.parent / "data"
STATE = DATA / "email_state.json"
UNPARSED = DATA / "unparsed"

OPENGOV_LINK = re.compile(r"https?://(?:procurement\.opengov\.com|secure\.procurenow\.com)/portal/([\w-]+)/projects/(\d+)", re.I)
BONFIRE_LINK = re.compile(r"https?://([\w-]+)\.bonfirehub\.com/opportunities/(\d+)", re.I)
DUE_NEAR = re.compile(r"(?:due|deadline|closing|closes|submission)[^:\n]{0,30}[:\-]?\s*([A-Z][a-z]{2,8}\.? \d{1,2},? \d{4}(?:[, ]+(?:at )?\d{1,2}:\d{2}\s*[ap]\.?m\.?)?(?:\s*[ECP][SD]?T)?|\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2}\s*[AP]M)?)", re.I)


def _subject(msg):
    return " ".join(str(make_header(decode_header(msg.get("Subject", "")))).split())


# OpenGov wraps every link in a click-tracking redirect (url856.opengov.com/ls/click?upn=...).
TRACKED = re.compile(r"https?://url\d+\.opengov\.com/[^\s\"'<>]+", re.I)


def _resolve(url: str, hops: int = 4) -> str:
    """Follow a tracking link's redirects (without loading the final page) to learn the real address."""
    import requests
    for _ in range(hops):
        if OPENGOV_LINK.match(url):
            return url
        try:
            r = requests.get(url, allow_redirects=False, timeout=20,
                             headers={"User-Agent": "FloridaBidsBot/1.0 (+https://floridabids.org/about)"})
        except requests.RequestException:
            return ""
        nxt = r.headers.get("Location", "")
        if not nxt:
            return ""
        url = nxt
    return url if OPENGOV_LINK.match(url) else ""


def _untrack(html: str, soup) -> str:
    """Return extra text containing the real OpenGov project links hidden behind tracking redirects."""
    if not html or not TRACKED.search(html):
        return ""
    # the project link is the one whose text is the bid title (the first long link), not logos or footers
    cands = []
    if soup is not None:
        for a in soup.find_all("a", href=TRACKED):
            txt = a.get_text(" ", strip=True)
            if len(txt) > 8 and not re.search(r"unsubscribe|preferences|privacy|view in browser|opengov", txt, re.I):
                cands.append(a["href"])
    out = []
    for href in cands[:3]:
        real = _resolve(href.replace("&amp;", "&"))
        if real:
            out.append(real)
            for a in soup.find_all("a", href=href):
                a["href"] = real          # so the title lookup below finds it
            break
    return "\n".join(out)


def _html_and_text(msg):
    html, text = "", ""
    for part in msg.walk():
        ctype = part.get_content_type()
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        body = payload.decode(charset, errors="replace")
        if ctype == "text/html":
            html += body
        elif ctype == "text/plain":
            text += body
    if html:
        text = BeautifulSoup(html, "lxml").get_text("\n", strip=True) + "\n" + text
    return html, text


def _src(platform: str, slug: str, alerts_cfg: dict) -> dict | None:
    entry = alerts_cfg.get(platform, {}).get(slug.lower())
    if not entry:
        return None
    county, agency = entry
    base = ("https://procurement.opengov.com/portal/" + slug) if platform == "opengov" else f"https://{slug}.bonfirehub.com/portal/?tab=openOpportunities"
    return {"id": f"{platform}-{slug.lower()}", "county": county, "agency": agency, "url": base}


def _link_title(soup, href):
    if soup is None:
        return ""
    a = soup.find("a", href=lambda h: h and href in h)
    t = a.get_text(" ", strip=True) if a else ""
    return "" if re.fullmatch(r"(view|view (opportunity|project|details)|click here|here|learn more)", t, re.I) else t


def parse_message(msg, alerts_cfg) -> list[Bid]:
    subject = _subject(msg)
    html, text = _html_and_text(msg)
    soup = BeautifulSoup(html, "lxml") if html else None
    blob = html + "\n" + text + "\n" + _untrack(html, soup)
    bids: list[Bid] = []
    due_m = DUE_NEAR.search(text)
    due = parse_due(due_m.group(1)) if due_m else ""

    for platform, rx, url_fmt in (("opengov", OPENGOV_LINK, "https://procurement.opengov.com/portal/{0}/projects/{1}"),
                                  ("bonfire", BONFIRE_LINK, "https://{0}.bonfirehub.com/opportunities/{1}")):
        seen = set()
        for slug, pid in rx.findall(blob):
            if (slug, pid) in seen:
                continue
            seen.add((slug, pid))
            src = _src(platform, slug, alerts_cfg)
            if not src:
                log.warning("alert for unknown %s portal '%s' (add it to sources.yaml)", platform, slug)
                continue
            url = url_fmt.format(slug, pid)
            m_sub = re.match(r"^New Opportunity Issued by .+?:\s*(.+)$", subject, re.I)
            title = (m_sub.group(1) if m_sub else "") or _link_title(soup, f"/{pid}") or re.sub(r"^(new|updated?)\s+(opportunity|project|solicitation)\s*[:\-]\s*", "", subject, flags=re.I)
            num_m = re.search(r"\b([A-Z]{2,6}[-\s]?\d{2,4}[-/]?\d{0,5}[A-Z]?)\b", title + " " + subject)
            b = make_bid(src, title=title, number=num_m.group(1) if num_m else f"#{pid}", due_iso=due, bid_url=url,
                         notes="From the agency's email alert.")
            b.origin = "email"
            b.extra = {"project_id": pid, "subject": subject}
            if re.search(r"\b(cancel(l)?ed|cancellation)\b", subject, re.I):
                b.status = "Cancelled"
            elif re.search(r"\baddend", subject, re.I):
                b.notes = "Addendum issued. " + b.notes
            bids.append(b)
    return bids


def fetch_and_parse(alerts_cfg: dict, max_messages: int = 500) -> tuple[list[Bid], dict]:
    user, pw = os.environ.get("ALERTS_EMAIL"), os.environ.get("ALERTS_APP_PASSWORD")
    if not (user and pw):
        log.info("ALERTS_EMAIL / ALERTS_APP_PASSWORD not set; skipping email alerts")
        return [], {"status": "skipped"}
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    last_uid = int(state.get("last_uid", 0))
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(user, pw)
    imap.select('"[Gmail]/All Mail"', readonly=True)
    typ, data = imap.uid("search", None, f"UID {last_uid + 1}:*")
    uids = [int(u) for u in data[0].split() if int(u) > last_uid][:max_messages]
    found, unparsed = [], 0
    UNPARSED.mkdir(parents=True, exist_ok=True)
    for uid in uids:
        typ, msgdata = imap.uid("fetch", str(uid), "(RFC822)")
        raw = msgdata[0][1]
        msg = email.message_from_bytes(raw)
        bids = parse_message(msg, alerts_cfg)
        if bids:
            found.extend(bids)
        elif not re.search(r"opengov|bonfire|procurenow", (msg.get("From") or ""), re.I):
            pass                         # not an alert (account emails, Brevo notices, etc.)
        else:
            unparsed += 1
            (UNPARSED / f"{uid}.eml").write_bytes(raw)
            # enough to diagnose in the (public) run log: sender domain, subject, and which sites it links to
            html, text = _html_and_text(msg)
            hosts = sorted(set(re.findall(r"https?://([\w.-]+)/", html + text)))[:8]
            sender = (msg.get("From") or "").split("@")[-1].strip("> ")
            log.info("unparsed alert from %s: %r links to %s", sender, _subject(msg)[:120], hosts)
        last_uid = max(last_uid, uid)
    imap.logout()
    STATE.write_text(json.dumps({"last_uid": last_uid}))
    return found, {"status": "ok", "messages": len(uids), "bids": len(found), "unparsed": unparsed}
