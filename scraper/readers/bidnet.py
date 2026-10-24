"""BidNet Direct: the agency's open-bids page. robots.txt disallows ?page= URLs, so we read page 1 only
(the open list is short for these counties) and log a warning if BidNet shows more pages."""
import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future
from . import make_bid

log = logging.getLogger(__name__)


def read(src):
    soup = BeautifulSoup(net.get(src["url"]).text, "lxml")
    out = []
    for tr in soup.select("tr.mets-table-row"):
        title_a = tr.select_one(".sol-title a")
        if not title_a:
            continue
        close = tr.select_one(".sol-closing-date")
        pub = tr.select_one(".sol-publication-date")
        b = make_bid(src,
                     number=(tr.select_one(".sol-num").get_text(strip=True) if tr.select_one(".sol-num") else ""),
                     title=title_a.get_text(" ", strip=True),
                     due_raw=close.get_text(" ", strip=True).replace("Closing", "").replace("Clock", "") if close else "",
                     posted_raw=pub.get_text(" ", strip=True).replace("Published", "").replace("Calendar", "") if pub else "",
                     bid_url=urljoin("https://www.bidnetdirect.com", title_a["href"]))
        if is_future(b.due) is not False:
            out.append(b)
    if soup.select_one(".mets-pagination a[href*='page=']"):
        log.warning("%s: BidNet shows more than one page; only page 1 is read (robots.txt)", src["id"])
    return out
