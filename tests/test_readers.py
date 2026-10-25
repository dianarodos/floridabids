"""Offline tests: feed each reader a copy of what the real site returned (captured 2026-10-24)."""
import json
from types import SimpleNamespace

import pytest

from scraper import net
from scraper.classify import classify, detect_type
from scraper.dates import parse_due, is_future


class Resp:
    def __init__(self, text=None, data=None):
        self.text = text if text is not None else json.dumps(data)
        self._data = data
    def json(self):
        return self._data if self._data is not None else json.loads(self.text)


def patch(monkeypatch, fn):
    monkeypatch.setattr(net, "get", fn)


def src(**kw):
    base = {"id": "t", "county": "Test", "agency": "Test Agency", "url": "https://example.gov/list"}
    base.update(kw)
    return base


def test_dates():
    assert parse_due("10/29/2026") == "2026-10-29"
    assert parse_due("11/18/2026 3:00:00 PM") == "2026-11-18T15:00-05:00"
    assert parse_due("11/09/2026 02:00 PM EST").startswith("2026-11-09T14:00")
    assert parse_due("November 18, 2026") == "2026-11-18"
    assert parse_due("3:00 P.M. (CST) November 26, 2025").startswith("2025-11-26T16:00")
    assert is_future("2099-01-01") and is_future("2000-01-01") is False and is_future("") is None


def test_classify():
    assert classify("SCADA Integration Services Software Support") == "IT & Technology"
    assert classify("CR 540 Intersection Improvements") == "Construction"
    assert classify("Construction Engineering & Inspection (CEI) Services") == "Engineering & Architecture"
    assert classify("Janitorial Cleaning Services") == "Facilities & Maintenance"
    assert classify("Purchase of Float Switches- Annual Contract") == "Goods & Supplies"
    assert classify("External Audit Services") == "Consulting & Professional Services"
    assert classify("Sale of approximately 13 acres") == "Property & Real Estate"
    assert detect_type("RFP-3062-0-2026/KM", "SCADA") == "RFP"
    assert detect_type("SB-2971", "Beach", "Invitation to Bid") == "ITB"
    assert detect_type("", "Pre-Solicitation Notice - Draft CAD") in ("Draft / Future", "Pre-solicitation")


def test_columbia(monkeypatch):
    from scraper.readers import columbia
    html = """<table id="t"><tr><th>Bid</th></tr>
    <tr><td data-label="Bid">S25-01</td><td data-label="Title"> SR247-Quail Heights Stormwater Pond</td>
    <td data-label="Due Date">10/29/2099</td><td data-label="View"><a href="PurchasingBid.aspx?Id=1765">View</a></td></tr>
    <tr><td data-label="Bid">OLD</td><td data-label="Title">Old bid</td><td data-label="Due Date">01/01/2020</td><td data-label="View"></td></tr></table>"""
    patch(monkeypatch, lambda url, **k: Resp(html))
    out = columbia.read(src(url="https://www.columbiacountyfla.com/PurchasingBids.aspx"))
    assert [b.number for b in out] == ["S25-01"]
    assert out[0].bid_url == "https://www.columbiacountyfla.com/PurchasingBid.aspx?Id=1765"
    assert out[0].category == "Construction"


def test_polk(monkeypatch):
    from scraper.readers import polk
    html = """<table><tr><th>Bid #</th></tr>
    <tr class="oneRow"><td class="bid"><a href="https://www.polkfl.gov/bid-form/bid-26-389/">Bid 26-389</a></td>
    <td class="bid-title">COUNTYWIDE DUMPSTER AND TRASH PICKUP SERVICES</td><td class="bid-date">November 18, 2099</td></tr>
    <tr class="oneRow"><td class="bid"><a href="x">CQ 26-128 SM</a></td><td class="bid-title">Wall - NOTICE OF REJECTION OF BIDS</td><td class="bid-date"></td></tr>
    </table>"""
    patch(monkeypatch, lambda url, **k: Resp(html))
    out = polk.read(src())
    assert len(out) == 2 and out[1].status == "Bids rejected"
    assert out[0].category == "Facilities & Maintenance"


def test_putnam_stops_at_closed_page(monkeypatch):
    from scraper.readers import putnam
    pages = {1: [("27-01", "Recycled Concrete Aggregate", "11-09-2099 02:00 PM"), ("26-19", "X", "10-21-2020 02:00 PM")],
             2: [("26-10", "Old", "05-14-2020 02:00 PM")]}
    calls = []
    def fake(url, **k):
        p = int(url.split("page=")[1]); calls.append(p)
        rows = "".join(f'<tr><td class="hidden">1</td><td class="number">{n}</td><td class="title">{t}</td><td class="duedate">{d}</td></tr>' for n, t, d in pages.get(p, []))
        return Resp(f"<table><tr><th>Number</th></tr>{rows}</table>")
    patch(monkeypatch, fake)
    out = putnam.read(src(url="https://apps.putnam-fl.com/bocc/callForBidsViewer/"))
    assert [b.number for b in out] == ["27-01"] and calls == [1, 2]


def test_charlotte_paging(monkeypatch):
    from scraper.readers import charlotte
    future_ms = 4102444800000  # 2100-01-01
    row = lambda i, **kw: {"FileNo": f"27-{i:03}", "Description": f"Item {i}", "DueDate": f"/Date({future_ms})/",
                           "ContractSpecialist": "a@b.gov", "NotNo": "<a href='/ContractsCatalogs/ShowDoc/1?tp=D'>1</a>",
                           "bAwarded": False, "bcancelled": None, "Type": "Bid", **kw}
    def fake(url, params=None, **k):
        if params["pagenum"] == 0:
            return Resp(data=[row(i) for i in range(50)])
        return Resp(data=[row(100), row(101, bcancelled=True), row(102, DueDate="/Date(1000)/")])
    patch(monkeypatch, fake)
    out = charlotte.read(src(url="https://purchasingbids.charlottecountyfl.gov/ContractsCatalogs"))
    assert len(out) == 51
    assert out[0].bid_url == "https://purchasingbids.charlottecountyfl.gov/ContractsCatalogs/ShowDoc/1?tp=D"


def test_demandstar(monkeypatch):
    from scraper.readers import demandstar
    data = {"total": 3, "result": [
        {"bidId": 554617, "bidName": "Fire Rescue Exams", "bidIdentifier": "QR-3123-0-2026/SA", "broadCastDate": "10/20/2026",
         "dueDate": "11/12/2099", "status": "Active", "statusType": "AC"},
        {"bidId": 1, "bidName": "Bay doors", "bidIdentifier": "SB-3081", "broadCastDate": "09/28/2026",
         "dueDate": "10/21/2099", "status": "Under Evaluation", "statusType": "UE"},
        {"bidId": 2, "bidName": "Old", "bidIdentifier": "X", "broadCastDate": "", "dueDate": "01/01/2020", "status": "Active", "statusType": "AC"}]}
    patch(monkeypatch, lambda url, **k: Resp(data=data))
    act = demandstar.read(src(agency_guid="g", rule="active"))
    assert [b.number for b in act] == ["QR-3123-0-2026/SA"]
    assert act[0].bid_url.endswith("/bids/554617/details")
    fut = demandstar.read(src(agency_guid="g", rule="future_due"))
    assert {b.number for b in fut} == {"QR-3123-0-2026/SA", "SB-3081"}


def test_planetbids(monkeypatch):
    from scraper.readers import planetbids
    data = {"data": [{"attributes": {"bidId": 147335, "title": "SHIP Demolition and Reconstruction", "invitationNum": "NC26-016-RFP",
                                     "bidDueDate": "2099-11-18 10:00:00.000", "issueDate": "2026-10-22 16:05:29.893",
                                     "stageId": 3, "bidTypeId": 4}}], "meta": {"total": 1}}
    patch(monkeypatch, lambda url, **k: Resp(data=data))
    out = planetbids.read(src(company_id=49083))
    assert out[0].bid_url == "https://vendors.planetbids.com/portal/49083/bo/bo-detail/147335"
    assert out[0].due.startswith("2099-11-18T10:00") and out[0].type == "RFP"


def test_bidnet(monkeypatch):
    from scraper.readers import bidnet
    html = """<table><tr class="mets-table-row odd"><td class="mainCol"><div class="sol-num">27-004-RDV</div>
    <div class="sol-title"><a href="/florida/solicitations/open-bids/Avon-Park/0000440133?purchasingGroupId=1">Avon Park Estates Right-of-Way Clearing</a></div>
    <span class="dates-col"><span class="dates-col-content"><span class="sol-publication-date">Calendar Published 10/16/2026</span>
    <span class="sol-closing-date open">Clock Closing 11/17/2099</span></span></span></td></tr></table>"""
    patch(monkeypatch, lambda url, **k: Resp(html))
    out = bidnet.read(src())
    assert out[0].number == "27-004-RDV" and out[0].due == "2099-11-17" and out[0].posted == "2026-10-16"


def test_miamidade_json(monkeypatch):
    from scraper.readers import miamidade
    def fake(url, **k):
        if url.endswith("FutureSolicitationsList"):
            return Resp(data=[{"webPostingCounter": 8984, "releaseDate": "10/20/2026 12:00:00 AM", "removalDate": "11/10/2026 12:00:00 AM",
                               "documentTitle": "E26PM01: Water Remediation Pool", "sendFeedBack": " Julie Whiteside", "emailAddress": " j@m.gov"}])
        return Resp(data=[{"solicitationNumber": "RPQ No PDC-W25012", "solicitationType": "Bids & Contracts",
                           "title": "MDSO Headquarters Building Roofing and Waterproofing", "openingDate": "10/29/2099", "postedDate": "09/21/2026"}])
    patch(monkeypatch, fake)
    fut = miamidade.read_future(src())
    assert fut[0].number == "E26PM01" and fut[0].status == "Upcoming" and fut[0].type == "Draft / Future"
    con = miamidade.read_construction(src())
    assert "solNumber=RPQ%20No%20PDC-W25012" in con[0].bid_url and con[0].category == "Construction"


def test_store_cycle(tmp_path, monkeypatch):
    from scraper import store
    from scraper.models import Bid
    monkeypatch.setattr(store, "BIDS_FILE", tmp_path / "bids.json")
    bids = {}
    a = Bid("s1", "C", "A", "Roof", number="1", due="2099-01-01")
    store.replace_source(bids, "s1", [a])
    e = Bid("e1", "C", "A", "Email bid", number="9", due="2000-01-01", origin="email")
    store.upsert(bids, e)
    assert store.prune(bids) == 1 and list(bids) == ["s1::1"]
    store.save(bids, {"x": 1})
    assert list(store.load()) == ["s1::1"]


def test_email_parser_opengov():
    from email.message import EmailMessage
    import yaml
    from scraper.emails import parse_message
    cfg = yaml.safe_load(open("config/sources.yaml"))["alerts"]
    m = EmailMessage()
    m["Subject"] = "New Opportunity: RFP 27-105 Countywide Janitorial Services"
    m.set_content("x")
    m.add_alternative("""<p>Volusia County has released a new opportunity.</p>
      <a href="https://procurement.opengov.com/portal/volusia/projects/229911">RFP 27-105 Countywide Janitorial Services</a>
      <p>Proposal Deadline: November 20, 2099 at 3:00 PM EST</p>""", subtype="html")
    bids = parse_message(m, cfg)
    assert len(bids) == 1
    b = bids[0]
    assert (b.county, b.agency, b.origin) == ("Volusia", "Volusia County", "email")
    assert b.bid_url.endswith("/volusia/projects/229911") and b.due.startswith("2099-11-20T15:00")
    assert b.category == "Facilities & Maintenance"


CIVIC = """<div class="listItemsRow bid"><div class="bidTitle"><span><a href="bids.aspx?bidID=163">2026-16 Lift Station No. 1 Replacement</a></span><br>
<span><strong>Bid No.</strong> 2026-16</span><br><span>Replace lift station one.</span> <a href="bids.aspx?bidID=163">Read on</a></div>
<div class="bidStatus"><div><span>Status:</span><br><span>Closes:</span></div><div><span>Open</span><br><span>Upon Contract</span></div></div></div>
<div class="listItemsRow bid"><div class="bidTitle"><span><a href="bids.aspx?bidID=1">Shoreline (Re-Bid)</a></span><br><span><strong>Bid No.</strong> ITB 20-07</span><br><span>Release Date: Tuesday, July 14, 2020</span></div>
<div class="bidStatus"><div><span>Status:</span><br><span>Closes:</span></div><div><span>Open</span><br><span>Upon Contract</span></div></div></div>
<div class="listItemsRow bid"><div class="bidTitle"><span><a href="bids.aspx?bidID=170">Old Bid</a></span></div>
<div class="bidStatus"><div><span>Status:</span> <span>Closed</span></div><div><span>Closes:</span> <span>1/2/2025</span></div></div></div>
<div class="listItemsRow bid"><div class="bidTitle"><span><a href="bids.aspx?bidID=171">2026-20 Paving</a></span></div>
<div class="bidStatus"><div><span>Status:</span> <span>Open</span></div><div><span>Closes:</span> <span>12/1/2099 2:00 PM</span></div></div></div>"""


def test_civicplus():
    from scraper.readers import civicplus
    src = {"id": "x", "county": "Broward", "agency": "City", "url": "https://example.gov/bids.aspx"}
    bids = civicplus.parse(CIVIC, src)
    assert [b.number for b in bids] == ["2026-16", "2026-20"]
    assert bids[0].bid_url == "https://example.gov/bids.aspx?bidID=163"
    assert bids[0].due == "" and "Upon Contract" in bids[0].notes
    assert bids[1].due.startswith("2099-12-01T14:00")


def test_bidsandtenders():
    from scraper.readers import bidsandtenders
    src = {"id": "t", "county": "Broward", "agency": "City of Tamarac", "url": "https://tamarac.bidsandtenders.net/"}
    rows = [{"Id": "651557dc", "Title": "27-04B - EV CHARGING STATION INFRASTRUCTURE", "Scope": "Public",
             "Status": "Open", "DateClosing": "/Date(4102444800000)/", "DateAvailableDisplay": "Fri Oct 23, 2026 1:00:00 PM"},
            {"Id": "x", "Title": "Old", "Scope": "Public", "Status": "Closed", "DateClosing": "/Date(4102444800000)/"}]
    bids = bidsandtenders.to_bids(rows, src)
    assert len(bids) == 1 and bids[0].number == "27-04B"
    assert bids[0].bid_url == "https://tamarac.bidsandtenders.net/Module/Tenders/en/Tender/Detail/651557dc"


def test_infor_fsm():
    from scraper.readers import infor_fsm
    src = {"id": "f", "county": "Broward", "agency": "City of Fort Lauderdale", "url": "https://x/list"}
    payload = {"dataViewSet": {"pagingInfo": {"hasNext": False}, "data": [{"fields": {
        "Name": {"value": "Install, Repair, Replace Chain Link Fence"},
        "_op_EventVersionString_spc_translation_cp_": {"value": "684-0"},
        "DerivedCloseDate": {"value": "2099113019000000"}, "OpenDate": {"value": "2026102318000000"},
        "SourcingEventType": {"value": "IFB"}, "RequireBidBond": {"value": False}}}]}}
    b = infor_fsm.to_bids(payload, src)[0]
    assert b.number == "684-0" and b.due == "2099-11-30T14:00-05:00" and b.posted == "2026-10-23"


GOVACCESS = """<div class="view-content"><table class="tablesaw views-table cols-3"><thead><tr><th>Title</th><th>Posted Date</th><th>Closing Date</th></tr></thead><tbody>
<tr><td><strong class="tablesaw-cell-label">Title</strong> <span><a href="/administration/bids-rfp/bid-fence">BID- BROOKSIDE CEMETERY PERIMETER FENCE INSTALLATION</a></span></td>
<td><strong class="tablesaw-cell-label">Posted Date</strong> <span><time>Mon 10/12/2026</time></span></td>
<td><strong class="tablesaw-cell-label">Closing Date</strong> <span>Tue 11/17/2099 </span></td></tr></tbody></table></div>"""


def test_govaccess():
    from scraper.readers import govaccess
    src = {"id": "g", "county": "Indian River", "agency": "City of Fellsmere", "url": "https://www.cityoffellsmere.org/rfps"}
    bids, nxt = govaccess.parse(GOVACCESS, src, src["url"])
    assert nxt is None and len(bids) == 1
    b = bids[0]
    assert b.title == "BROOKSIDE CEMETERY PERIMETER FENCE INSTALLATION" and b.due == "2099-11-17"
    assert b.bid_url == "https://www.cityoffellsmere.org/administration/bids-rfp/bid-fence" and b.posted == "2026-10-12"


DUE_TABLE = """<table><tr><td>SOLICITATION DOCUMENTS</td><td>SOLICITATION NUMBER &amp; NAME</td><td>RELEASED</td><td>DUE DATE</td><td>STATUS/ RESOLUTION</td></tr>
<tr><td><a href="/DocumentCenter/View/1">BID 99-01 NEW PARK</a></td><td>BID 99-01<br>NEW PARK RESTROOMS</td><td>SEPTEMBER 16, 2098</td>
<td>JUNE 2, 2099 NO LATER THAN 11:00 A.M. JUNE 16, 2099 NO LATER THAN 11:00 A.M.</td><td></td></tr>
<tr><td></td><td>RFP 25-26-10 STATE LOBBYIST SERVICES</td><td>APRIL 16, 2026</td><td>MAY 21, 2099 NO LATER THAN 11:00 A.M.</td><td>AWARDED RESO 2026-110</td></tr></table>"""


def test_due_table():
    from scraper.readers import due_table
    src = {"id": "h", "county": "Broward", "agency": "City", "url": "https://x.gov/417/S"}
    bids = due_table.parse(DUE_TABLE, src, src["url"])
    assert len(bids) == 1
    b = bids[0]
    assert b.number == "BID 99-01" and b.title == "NEW PARK RESTROOMS"
    assert b.due.startswith("2099-06-16T11:00") and b.bid_url == "https://x.gov/DocumentCenter/View/1"


def test_dedupe_prefers_email_over_backfill_without_leaving_copies():
    import run
    from scraper.models import Bid
    base = dict(county="Hillsborough", agency="Hillsborough County BOCC", title="Tire Disposal Services")
    a = Bid(source_id="backfill-x", number="ITB-26-00424", origin="backfill", **base)
    b = Bid(source_id="bonfire-x", number="#251584", origin="email", **base)
    out = run.dedupe([a, b])
    assert len(out) == 1 and out[0].origin == "email"
