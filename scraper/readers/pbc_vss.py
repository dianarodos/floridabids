"""Palm Beach County Vendor Self-Service (CGI Advantage 4): public 'View Published Solicitations' grid.

Steps: open the tab, choose 'Open' under Show Me, 100 per page, then read rows and click Next until done.
Keep rows whose closing date/time has not passed.
"""
import re

from .. import browser
from ..dates import is_future
from . import make_bid

MAX_PAGES = 10


def _rows(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('[role=row]')].map(r =>
        [...r.querySelectorAll('[role=gridcell],[role=cell]')].map(c => c.innerText.replace(/\\s+/g, ' ').trim()))
        .filter(c => c.length >= 5 && /\\d{1,2}\\/\\d{1,2}\\/\\d{4}/.test(c.join(' ')))""")


def read(src):
    out = {}
    with browser.page(src["url"], wait_for="text=View Published Solicitations") as pg:
        pg.get_by_role("tab", name="View Published Solicitations").click()
        pg.wait_for_selector("[role=row]")
        try:
            pg.get_by_text("Open", exact=True).first.click()
            pg.get_by_role("button", name=re.compile(r"^Search$")).first.click()
            pg.wait_for_timeout(2500)
        except Exception:
            pass   # fall back to the default list; the due-date check below still filters closed items
        try:
            pg.get_by_text("100", exact=True).first.click()
            pg.wait_for_timeout(2500)
        except Exception:
            pass
        for _ in range(MAX_PAGES):
            for cells in _rows(pg):
                # cells: [select, Description, Department/Buyer, Number/Type/Category, Closing/Status, Respond]
                desc = cells[1]
                dept = cells[2]
                numtype = cells[3]
                closing = cells[4]
                number = numtype.split(" ")[0]
                m = re.search(r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M", closing)
                status = closing[m.end():].strip() if m else ""
                b = make_bid(src, number=number, title=desc, due_raw=m.group(0) if m else closing,
                             type_=numtype, status=status or "Open", extra_text=numtype,
                             agency_category=("Construction" if "Construction" in numtype else ""),
                             notes=f"Department: {dept}. Search {number} under View Published Solicitations.")
                if is_future(b.due) is True:
                    out[b.key] = b
            nxt = pg.locator("[aria-label*='Next' i]:not([disabled]):not([aria-disabled='true'])")
            if nxt.count() == 0:
                break
            first = _rows(pg)[:1]
            nxt.first.click()
            pg.wait_for_timeout(2500)
            if _rows(pg)[:1] == first:
                break
    return list(out.values())
