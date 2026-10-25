"""Polk County: procurement page table (Bid #, Title, Open Date). Keep open date today or later.

Rows that are notices of rejected bids are kept and labeled 'Bids rejected'.
"""
import re

from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future
from . import make_bid


def read(src):
    soup = BeautifulSoup(net.get(src["url"]).text, "lxml")
    out = []
    # rows alternate classes (oneRow / twoRow), so take every row that has a title cell
    for tr in soup.select("tr"):
        num_td, title_td, date_td = tr.select_one("td.bid"), tr.select_one("td.bid-title"), tr.select_one("td.bid-date")
        if not (num_td and title_td):
            continue
        title = title_td.get_text(" ", strip=True)
        rejected = bool(re.search(r"rejection of (all )?bids", title, re.I))
        a = num_td.find("a")
        b = make_bid(src,
                     number=num_td.get_text(" ", strip=True),
                     title=title,
                     due_raw=date_td.get_text(" ", strip=True) if date_td else "",
                     status="Bids rejected" if rejected else "Open",
                     bid_url=a["href"] if a else "")
        if rejected or is_future(b.due) is not False:
            out.append(b)
    return out
