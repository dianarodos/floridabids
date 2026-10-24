"""Miami-Dade County: three public sources.

- Future Solicitations (draft bids posted for feedback): JSON list, all rows, tagged Upcoming.
- Construction Solicitations: JSON list, keep opening date today or later.
- INFORMS public bidding events (PeopleSoft): rendered grid, every row is a currently open event.
"""
from urllib.parse import quote

from .. import browser, net
from ..dates import is_future, parse_due
from . import make_bid

BASE = "https://www.miamidade.gov/apps/isd/StratProc/Home/"


def read_future(src):
    rows = net.get(BASE + "FutureSolicitationsList", headers={"Accept": "application/json"}).json()
    out = []
    for r in rows:
        title = r.get("documentTitle", "")
        number, _, rest = title.partition(":")
        if not rest:
            number, rest = "", title
        removal = parse_due(r.get("removalDate", ""))
        out.append(make_bid(
            src, number=number.strip(), title=rest.strip(), type_="Draft / Future", status="Upcoming",
            posted_raw=r.get("releaseDate", ""), due_iso="",
            bid_url=BASE + f"FutureSolicitationDetails?webPostingCounter={r.get('webPostingCounter')}",
            notes=f"Draft for feedback. Send comments to {r.get('sendFeedBack', '').strip()} "
                  f"({r.get('emailAddress', '').strip()}). Posted until {removal[:10]}."))
    return out


def read_construction(src):
    rows = net.get(BASE + "CurrentSolicitationsList", headers={"Accept": "application/json"}).json()
    out = []
    for r in rows:
        num = r.get("solicitationNumber", "")
        b = make_bid(src, number=num, title=r.get("title", ""), due_raw=r.get("openingDate", ""),
                     posted_raw=r.get("postedDate", ""), agency_category="Construction",
                     bid_url=BASE + "SolicitationDetails?solNumber=" + quote(num, safe=""))
        if is_future(b.due) is not False:
            out.append(b)
    return out


def read_informs(src):
    out = []
    with browser.page(src["url"], wait_for="span[id^='SCP_PUB_AUC_VW_AUC_ID$']") as pg:
        rows = pg.eval_on_selector_all(
            "span[id^='SCP_PUB_AUC_VW_AUC_ID$']",
            """els => els.map(e => { const i = e.id.split('$')[1]; const g = id => (document.getElementById(id) || {innerText: ''}).innerText.trim();
                return { number: e.innerText.trim(), title: g('SCP_PUB_AUC_VW_AUC_NAME$' + i), unit: g('BUS_UNIT_AUC_VW_DESCR$' + i),
                         start: g('SCP_COSP_WK_FL_SCP_STRT_DATE_CHAR$' + i), end: g('SCP_COSP_WK_FL_SCP_END_DATE_CHAR$' + i) }; })""")
    for r in rows:
        unit = r["unit"]
        agency = "Miami-Dade County" if unit in ("", "Strategic Procurement") else f"Miami-Dade County – {unit}"
        b = make_bid(src, agency=agency, number=r["number"], title=r["title"],
                     due_raw=r["end"].replace("EST", "").replace("EDT", ""), posted_raw=r["start"],
                     notes=f"Find event {r['number']} on the INFORMS public bidding page.")
        if is_future(b.due) is not False:
            out.append(b)
    return out
