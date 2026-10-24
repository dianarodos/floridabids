"""Columbia County: plain 'Open Bids' table, one page. Keep rows not yet past due."""
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future
from . import make_bid


def read(src):
    html = net.get(src["url"]).text
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table#t") or soup.find("table")
    out = []
    for tr in table.find_all("tr")[1:]:
        cells = {td.get("data-label", "").strip(): td for td in tr.find_all("td")}
        if "Title" not in cells:
            continue
        link = cells.get("View").find("a") if cells.get("View") else None
        b = make_bid(src,
                     number=cells["Bid"].get_text(" ", strip=True),
                     title=cells["Title"].get_text(" ", strip=True),
                     due_raw=cells["Due Date"].get_text(" ", strip=True),
                     bid_url=urljoin(src["url"], link["href"]) if link else "")
        if is_future(b.due) is not False:
            out.append(b)
    return out
