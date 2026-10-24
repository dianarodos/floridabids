"""Bids&Tenders portals (<city>.bidsandtenders.net).

The home page carries the portal's NodeId and an anti-forgery token; the list loads from
POST /Module/Tenders/en/Tender/Search/<NodeId>?status=Open&limit=..&start=.. returning
{"success", "data": [...], "total"}. Each item links to /Module/Tenders/en/Tender/Detail/<Id>.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from .. import net
from ..dates import is_future
from ..models import ET
from . import make_bid

PAGE = 100


def _ms_date(s):
    m = re.search(r"/Date\((-?\d+)\)/", s or "")
    if not m:
        return ""
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).astimezone(ET).isoformat(timespec="minutes")


def to_bids(rows, src):
    out = []
    for d in rows:
        if (d.get("Status") or "").lower() != "open" or (d.get("Scope") or "Public").lower() != "public":
            continue
        title = d.get("Title") or ""
        m = re.match(r"^([A-Z]{0,4}\d[\w-]*\d[A-Z]?)\s+-\s+(.+)$", title)
        number, name = (m.group(1), m.group(2)) if m else ("", title)
        b = make_bid(src, title=name, number=number, due_iso=_ms_date(d.get("DateClosing")),
                     posted_raw=d.get("DateAvailableDisplay", ""),
                     bid_url=urljoin(src["url"], f"/Module/Tenders/en/Tender/Detail/{d.get('Id')}"),
                     extra_text=re.sub(r"<[^>]+>", " ", d.get("Description") or "")[:600])
        if is_future(b.due) is not False:
            out.append(b)
    return out


def read(src):
    home = net.get(src["url"]).text
    node = re.search(r'id="NodeId"\s+value="([0-9a-f-]{36})"', home)
    tok = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', home)
    if not node or not tok:
        raise RuntimeError("Bids&Tenders page layout changed: NodeId or token not found")
    api = urljoin(src["url"], f"/Module/Tenders/en/Tender/Search/{node.group(1)}")
    out, start = [], 0
    while True:
        params = {"status": "Open", "limit": PAGE, "start": start, "dir": "ASC", "from": "", "to": "",
                  "sort": "DateClosing ASC,Id"}
        j = net.post(api, params=params, data={"__RequestVerificationToken": tok.group(1)},
                     headers={"X-Requested-With": "XMLHttpRequest", "Referer": src["url"]}).json()
        rows = j.get("data") or []
        out += to_bids(rows, src)
        start += PAGE
        if not rows or start >= int(j.get("total") or 0):
            break
    return out
