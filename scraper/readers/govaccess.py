"""Granicus govAccess / Drupal "Bids and RFPs" views (e.g. cityoffellsmere.org/rfps).

The Open tab is a views-table with columns such as Title, Posted Date, Closing Date
(column names are read from the header row). Pages follow the Drupal pager's "next" link.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future
from . import make_bid

MAX_PAGES = 10


def _cell(td):
    lab = td.select_one(".tablesaw-cell-label")
    if lab:
        lab.extract()
    return td


def parse(html, src, page_url):
    soup = BeautifulSoup(html, "lxml")
    out = []
    table = soup.select_one("table.views-table") or soup.select_one(".view-content table")
    if not table:
        return out, None
    heads = [th.get_text(" ", strip=True).lower() for th in table.select("thead th")]

    def col(*names):
        return next((i for i, h in enumerate(heads) if any(n in h for n in names)), None)

    t_i, d_i, p_i = col("title", "project", "name"), col("closing", "due", "deadline"), col("posted", "open", "issue")
    n_i = col("number", "bid #", "no.")
    for tr in table.select("tbody tr"):
        tds = [_cell(td) for td in tr.find_all("td")]
        if t_i is None or t_i >= len(tds):
            continue
        a = tds[t_i].find("a")
        title = tds[t_i].get_text(" ", strip=True)
        txt = lambda i: tds[i].get_text(" ", strip=True) if i is not None and i < len(tds) else ""
        number = txt(n_i)
        m = re.match(r"^(?:BID|RFP|RFQ|ITB|IFB|ITN)\s*[-–:]\s*(.+)$", title, re.I)
        type_ = title.split("-")[0].strip().upper() if m else ""
        b = make_bid(src, title=m.group(1) if m else title, number=number, type_=type_,
                     due_raw=txt(d_i), posted_raw=txt(p_i),
                     bid_url=urljoin(page_url, a["href"]) if a and a.get("href") else "")
        if is_future(b.due) is not False:
            out.append(b)
    nxt = soup.select_one("li.pager__item--next a, a[rel=next]")
    return out, urljoin(page_url, nxt["href"]) if nxt and nxt.get("href") else None


def read(src):
    out, url, seen = [], src["url"], set()
    for _ in range(MAX_PAGES):
        if not url or url in seen:
            break
        seen.add(url)
        bids, url = parse(net.get(url).text, src, url)
        out += bids
    return out
