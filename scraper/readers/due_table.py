"""Hand-kept solicitation tables on city web pages (e.g. Hallandale Beach /417/Solicitation-Notifications).

Picks the first table whose header row mentions a due/closing date, maps columns by header
words, and keeps rows whose last due date is still ahead and whose status isn't a result
(awarded, cancelled, no responses...). The header may be a <th> or a plain first <td> row.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future, parse_due
from . import make_bid

DATE = re.compile(r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+\d{1,2},?\s+\d{4}"
                  r"(?:\s+(?:NO LATER THAN|BY|AT|@)?\s*\d{1,2}:\d{2}\s*[AP]\.?\s?M\.?)?"
                  r"|\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2}\s*[AP]\.?M\.?)?", re.I)
DONE = re.compile(r"award|cancel|no respon|rejected|closed|reso\b|withdrawn", re.I)
NUMBER = re.compile(r"^((?:BID|RFP|RFQ|ITB|IFB|ITN|RFI|RLI)\s*(?:NO\.?\s*)?[\w-]*\d[\w-]*)\s*(.*)$", re.I)


def parse(html, src, page_url):
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        heads = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        if not any(("due" in h or "closing" in h) for h in heads):
            continue

        def col(*words):
            return next((i for i, h in enumerate(heads) if any(w in h for w in words)), None)

        d_i = col("due", "closing")
        t_i = col("name", "title", "description", "project")
        p_i = col("released", "posted", "issue")
        s_i = col("status", "resolution", "award")
        doc_i = col("document")
        out = []
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if t_i is None or max(t_i, d_i) >= len(cells):
                continue
            txt = lambda i: " ".join(cells[i].get_text(" ").split()) if i is not None and i < len(cells) else ""
            if s_i is not None and DONE.search(txt(s_i)):
                continue
            dates = DATE.findall(txt(d_i))
            due_raw = re.sub(r"(?i)no later than|\bby\b|@", " ", dates[-1]) if dates else ""
            name = txt(t_i)
            m = NUMBER.match(name)
            number, title = (m.group(1), m.group(2) or name) if m else ("", name)
            link = None
            for i in (doc_i, t_i):
                if i is not None and i < len(cells) and cells[i].find("a", href=True):
                    link = cells[i].find("a", href=True)["href"]
                    break
            b = make_bid(src, title=title, number=number, due_iso=parse_due(due_raw),
                         posted_raw=(DATE.findall(txt(p_i)) or [""])[0],
                         bid_url=urljoin(page_url, link) if link else "")
            if b.due and is_future(b.due):
                out.append(b)
        return out
    return []


def read(src):
    return parse(net.get(src["url"]).text, src, src["url"])
