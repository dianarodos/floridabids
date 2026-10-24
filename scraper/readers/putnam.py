"""Putnam County 'Call for Bids Viewer': newest first, 10 per page. Keep due date in the future."""
from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future
from . import make_bid

MAX_PAGES = 4


def read(src):
    base = src["url"].rstrip("/") + "/"
    out = []
    for page in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(net.get(f"{base}main.php?request=VIEWBIDS&page={page}").text, "lxml")
        rows = [tr for tr in soup.find_all("tr") if tr.select_one("td.number")]
        if not rows:
            break
        future_here = 0
        for tr in rows:
            b = make_bid(src,
                         number=tr.select_one("td.number").get_text(strip=True),
                         title=tr.select_one("td.title").get_text(" ", strip=True),
                         due_raw=tr.select_one("td.duedate").get_text(" ", strip=True),
                         bid_url=src["url"],
                         notes="Open the viewer and click the bid to see its documents.")
            if is_future(b.due):
                out.append(b)
                future_here += 1
        if future_here == 0:
            break   # newest-first list: a page with nothing open means older pages are closed too
    return out
