"""Charlotte County: the 'Current' catalog loads from a JSON endpoint with paging.

Keep rows that are not cancelled, not awarded, and whose due date/time is still ahead.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from .. import net
from ..dates import is_future
from ..models import ET
from . import make_bid

PAGE_SIZE = 50


def _ms_date(s):
    m = re.search(r"/Date\((-?\d+)\)/", s or "")
    if not m:
        return ""
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).astimezone(ET).isoformat(timespec="minutes")


def _href(html):
    m = re.search(r"href='([^']+)'", html or "")
    return m.group(1) if m else ""


def read(src):
    api = urljoin(src["url"], "/ContractsCatalogs/GetContractData")
    out, page, seen = [], 0, set()
    while page < 40:
        params = {"filterscount": 0, "groupscount": 0, "pagenum": page, "pagesize": PAGE_SIZE,
                  "recordstartindex": page * PAGE_SIZE, "recordendindex": (page + 1) * PAGE_SIZE}
        rows = net.get(api, params=params, headers={"X-Requested-With": "XMLHttpRequest"}).json()
        if not rows:
            break
        ids = {(r.get("FileNo"), r.get("Description")) for r in rows}
        if ids <= seen:          # the endpoint ignored the page number and sent the same rows again
            break
        seen |= ids
        for r in rows:
            if r.get("bcancelled") or r.get("bAwarded"):
                continue
            doc = _href(r.get("NotNo")) or _href(r.get("PackNo")) or _href(r.get("AdNo"))
            b = make_bid(src, number=r.get("FileNo", ""), title=r.get("Description", ""),
                         due_iso=_ms_date(r.get("DueDate")), type_=r.get("Type", ""),
                         bid_url=urljoin(src["url"], doc) if doc else "",
                         notes=f"Contact: {r['ContractSpecialist']}" if r.get("ContractSpecialist") else "")
            if is_future(b.due):
                out.append(b)
        if len(rows) < PAGE_SIZE:
            break
        page += 1
    return out
