"""PlanetBids vendor portal: public JSON search used by the portal page. Stage 3 = 'Bidding' (open)."""
from .. import net
from . import make_bid

API = "https://api-external.prod.planetbids.com/papi/bids"
BIDDING_STAGE = 3
PER_PAGE = 30
BID_TYPES = {1: "ITB", 2: "RFI", 4: "RFP", 8: "RFQ", 16: "RFQ (qualifications)", 32: "IPWB"}


def read(src):
    cid = src["company_id"]
    out, page = [], 1
    while True:
        params = {"bid_type_id": 0, "cid": cid, "dept_id": 0, "due_date_from": "", "due_date_to": "", "keyword": "",
                  "page": page, "per_page": PER_PAGE, "sort_by": "", "sort_order": -1, "stage_id": BIDDING_STAGE}
        data = net.get(API, params=params, headers={"Accept": "application/json",
                                                    "Origin": "https://vendors.planetbids.com",
                                                    "Referer": src["url"]}).json()
        rows = data.get("data", [])
        for row in rows:
            a = row.get("attributes", {})
            if a.get("stageId") != BIDDING_STAGE:
                continue
            out.append(make_bid(
                src, number=a.get("invitationNum", ""), title=a.get("title", ""),
                due_raw=a.get("bidDueDate", ""), posted_raw=a.get("issueDate", ""), status="Bidding",
                type_=BID_TYPES.get(a.get("bidTypeId"), ""),
                bid_url=f"https://vendors.planetbids.com/portal/{cid}/bo/bo-detail/{a.get('bidId')}"))
        total = (data.get("meta") or {}).get("total") or (data.get("meta") or {}).get("totalCount") or 0
        if len(rows) < PER_PAGE or (total and page * PER_PAGE >= total):
            break
        page += 1
    return out
