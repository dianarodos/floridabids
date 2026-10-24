"""Infor CloudSuite (FSM) Supplier Portal, "Open Events" list (e.g. City of Fort Lauderdale).

Opening the list page sets session cookies; the rows then come from the same URL with
pageop=load as JSON (dataViewSet.data[].fields). Dates look like 2026111319000000 (UTC,
yyyyMMddHHmmss + 2 digits). Events have no public detail link, so bid_url stays empty.
"""
import logging
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from .. import net
from ..dates import is_future
from ..models import ET
from . import make_bid

log = logging.getLogger(__name__)
PAGE = 200


def _utc(v):
    v = str(v or "")
    if len(v) < 12:
        return ""
    dt = datetime.strptime(v[:12], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).isoformat(timespec="minutes")


def _val(fields, key):
    f = fields.get(key) or {}
    return f.get("value", "") if isinstance(f, dict) else ""


def to_bids(payload, src):
    vs = payload.get("dataViewSet") or {}
    if (vs.get("pagingInfo") or {}).get("hasNext"):
        log.warning("%s: more than %d open events; only the first page was read", src["id"], PAGE)
    out = []
    for row in vs.get("data") or []:
        f = row.get("fields") or {}
        title = _val(f, "Name") or _val(f, "_op_Name_spc_translation_cp_")
        if not title:
            continue
        b = make_bid(src, title=title, number=_val(f, "_op_EventVersionString_spc_translation_cp_"),
                     due_iso=_utc(_val(f, "DerivedCloseDate") or _val(f, "CloseDate")),
                     type_=_val(f, "SourcingEventType"),
                     agency_category=" ".join(x for x in (_val(f, "Category"), _val(f, "SubCategory")) if x),
                     notes=_val(f, "_op_BidBondMessage_spc_translation_cp_") if _val(f, "RequireBidBond") else "")
        b.posted = _utc(_val(f, "OpenDate"))[:10]
        if is_future(b.due) is not False:
            out.append(b)
    return out


def read(src):
    net.get(src["url"])  # session cookies
    u = urlparse(src["url"])
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    q.update({"pageop": "load", "pagesize": PAGE})
    api = urlunparse(u._replace(query=urlencode(q)))
    return to_bids(net.get(api, headers={"Accept": "application/json"}).json(), src)
