"""JAXPORT active-solicitations table (GravityView). Sorted by status so 'Active' rows come first.

Keep Active. The table has no due date, so each active bid's detail page is opened to find
'BID DUE' / 'PROPOSALS DUE' text; if that date has passed, the bid is dropped (JAXPORT is slow to
change status after opening).
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future, parse_due
from . import make_bid

DUE_RE = re.compile(r"(?:BIDS?|PROPOSALS?|RESPONSES?|SUBMITTALS?|QUOTES?|STATEMENTS? OF QUALIFICATIONS?)\s+(?:ARE\s+)?DUE\b[^A-Za-z0-9]*"
                    r"(?:before|by|on|no later than)?\s*([^.]{6,90}?\d{4})", re.I)
MAX_PAGES = 3


def _due_from_detail(url):
    try:
        text = BeautifulSoup(net.get(url).text, "lxml").get_text(" ", strip=True)
    except Exception:
        return ""
    m = DUE_RE.search(text)
    return parse_due(m.group(1)) if m else ""


def read(src):
    out = []
    for page in range(1, MAX_PAGES + 1):
        url = src["url"] if page == 1 else f"{src['url']}&pagenum={page}"
        soup = BeautifulSoup(net.get(url).text, "lxml")
        rows = soup.select("table.gv-table-view tbody tr")
        active_here = 0
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            status = tds[4].get_text(strip=True)
            if status.lower() != "active":
                continue
            active_here += 1
            link = tr.find("a", href=True)
            detail = urljoin(src["url"], link["href"]) if link else ""
            due = _due_from_detail(detail) if detail else ""
            b = make_bid(src, number=tds[0].get_text(" ", strip=True), title=tds[1].get_text(" ", strip=True),
                         type_=tds[2].get_text(" ", strip=True), agency_category=tds[3].get_text(" ", strip=True),
                         status=status, due_iso=due, bid_url=detail)
            if is_future(b.due) is not False:
                out.append(b)
        if active_here == 0 or len(rows) < 100:
            break   # sorted by status: once a page has no Active rows, later pages won't either
    return out
