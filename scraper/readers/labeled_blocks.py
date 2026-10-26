"""Pages that list every solicitation as a block of labeled lines (e.g. Baker County purchasing.php):

    2025-16
    Contact: Troy Tarbox
    Due: 02/19/2026 11:00 am          <- "Closed on:" / "Awarded to" for finished ones
    CR 229 N Widening and Resurfacing
    Commodity: ...
    Documents: ...
    Opening On: 02/19/2026 11:00 am

We read the page text line by line: every "Due:" line starts an open bid; the title is the next
plain line, the number the nearest plain line above it. Rows past due are dropped.
"""
import logging
import re

from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future
from . import make_bid

log = logging.getLogger(__name__)
DUE = re.compile(r"^\s*Due\s*:\s*(.+)$", re.I)
CLOSED = re.compile(r"^\s*(Closed on|Awarded to|Opened on)\b", re.I)
LABEL = re.compile(r"^\s*[A-Za-z ]{2,25}:")      # "Contact:", "Commodity:", "Documents:" ...


def parse(text, src):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out, n_due, n_closed = [], 0, 0
    for i, line in enumerate(lines):
        if CLOSED.match(line):
            n_closed += 1
            continue
        m = DUE.match(line)
        if not m:
            continue
        n_due += 1
        title = next((l for l in lines[i + 1:i + 4] if not LABEL.match(l)), "")
        number = next((l for l in reversed(lines[max(0, i - 3):i]) if not LABEL.match(l)), "")
        if len(number) > 40:            # not a bid number, just text above
            number = ""
        b = make_bid(src, title=title or number, number=number, due_raw=m.group(1), bid_url=src["url"])
        if is_future(b.due) is not False:
            out.append(b)
    log.info("%s: %d 'Due' blocks, %d closed/awarded blocks on the page", src["id"], n_due, n_closed)
    if n_due == 0 and n_closed == 0:
        raise RuntimeError("no labeled bid blocks found; the page layout may have changed")
    return out


def read(src):
    soup = BeautifulSoup(net.get(src["url"]).text, "lxml")
    for t in soup(["script", "style", "nav", "header", "footer"]):
        t.decompose()
    return parse(soup.get_text("\n"), src)
