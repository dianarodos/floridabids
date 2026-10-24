"""DemandStar (Euna OpenBids): the agency page loads its list from a public JSON endpoint.

src['agency_guid'] is the id at the end of the agency page URL.
src['rule'] is 'active' (status Active) or 'future_due' (due date not passed).
"""
from .. import net
from ..dates import is_future
from . import make_bid

API = "https://api.demandstar.com/contents/agency/search"
BID_URL = "https://www.demandstar.com/app/limited/bids/{bid_id}/details"


def read(src):
    data = net.get(API, params={"id": src["agency_guid"]},
                   headers={"Accept": "application/json", "Referer": src["url"]}).json()
    rows = data.get("result", []) if isinstance(data, dict) else data
    rule = src.get("rule", "active")
    out = []
    for r in rows:
        status = r.get("status", "")
        b = make_bid(src, number=r.get("bidIdentifier", ""), title=r.get("bidName", ""),
                     due_raw=r.get("dueDate", ""), posted_raw=r.get("broadCastDate", ""), status=status,
                     bid_url=BID_URL.format(bid_id=r.get("bidId")))
        if rule == "active":
            keep = r.get("statusType") == "AC" and is_future(b.due) is not False
        else:
            keep = is_future(b.due) is True and status.lower() not in {"awarded", "cancelled", "canceled"}
        if keep:
            out.append(b)
    return out
