"""CivicPlus "Bid Postings" pages (…/bids.aspx), used by many Florida cities.

The list page shows Open bids by default; each listing has a title link
(bids.aspx?bidID=N), an optional "Bid No." line and "Status:" / "Closes:" values.
Detail pages are often disallowed by robots.txt, so we read only the list page.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future
from . import make_bid

BID_LINK = re.compile(r"bids\.aspx\?bidid=\d+", re.I)
OPEN = {"open", "active"}


def _value(text: str, label: str) -> str:
    m = re.search(label + r"\s*:?\s*(.+?)(?=\s*(?:Status|Closes|Bid No\.?)\s*:|$)", text, re.I)
    return m.group(1).strip() if m else ""


def parse(html: str, src: dict) -> list:
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=BID_LINK):
        href = urljoin(src["url"], a["href"])
        title = a.get_text(" ", strip=True)
        if not title or href in seen or title.lower().startswith("read on"):
            continue
        # climb to the listing block that also holds the Status / Closes values
        box = a
        for _ in range(6):
            box = box.parent
            if box is None or "Closes" in box.get_text(" "):
                break
        if box is None:
            continue
        text = " ".join(box.get_text(" ").split())
        status = _value(text, "Status") or "Open"
        if status.split()[0].lower() not in OPEN:
            continue
        closes = _value(text, "Closes")
        number = ""
        label = box.find(string=re.compile(r"^\s*Bid No\.?\s*:?\s*$", re.I))
        if label is not None:
            holder = label.parent
            number = holder.next_sibling.get_text(" ", strip=True) if hasattr(holder.next_sibling, "get_text") \
                else str(holder.next_sibling or "").strip()
        if not number:
            m = re.match(r"^(\d{2,4}-\d{1,4}[A-Z]?)\b", title)
            number = m.group(1) if m else ""
        due_raw = closes if re.search(r"\d", closes) else ""
        b = make_bid(src, title=title, number=number, due_raw=due_raw, status="Open", bid_url=href,
                     notes="" if due_raw else (f"Closes: {closes}" if closes else ""))
        if is_future(b.due) is not False:
            seen.add(href)
            out.append(b)
    return out


def read(src):
    return parse(net.get(src["url"]).text, src)
