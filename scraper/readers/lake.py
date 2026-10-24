"""Lake County: ASP.NET grid with ~1,000 historical rows and postback paging.

Keep Status == Open and due date not passed. Page forward until two pages in a row have no Open rows.
"""
from urllib.parse import urljoin

from .. import browser
from ..dates import is_future
from . import make_bid

MAX_PAGES = 12


def _rows(pg):
    return pg.eval_on_selector_all(
        "#gvBids tr",
        """trs => trs.filter(r => !r.classList.contains('gv_head') && !r.classList.contains('gv_pager')
                              && r.querySelectorAll('td').length >= 4).map(r => ({
            number: r.cells[0].innerText.trim(), title: r.cells[1].innerText.trim(),
            status: r.cells[2].innerText.trim(), due: r.cells[3].innerText.trim(),
            href: r.querySelector('a[href*="bid_details"]')?.getAttribute('href') || ''
        }))""")


def read(src):
    out, seen = {}, set()
    with browser.page(src["url"], wait_for="#gvBids") as pg:
        empty_streak, page_no = 0, 1
        while page_no <= MAX_PAGES:
            rows = _rows(pg)
            open_here = 0
            for r in rows:
                if r["number"] in seen:
                    continue
                seen.add(r["number"])
                if r["status"].lower() != "open":
                    continue
                b = make_bid(src, number=r["number"], title=r["title"], due_raw=r["due"],
                             bid_url=urljoin(src["url"], r["href"]) if r["href"] else "")
                if is_future(b.due) is not False:
                    out[b.key] = b
                    open_here += 1
            empty_streak = 0 if open_here else empty_streak + 1
            if empty_streak >= 2:
                break
            nxt = pg.locator("#gvBids tr.gv_pager a", has_text=str(page_no + 1))
            if nxt.count() == 0:
                break
            first_before = rows[0]["number"] if rows else ""
            nxt.first.click()
            pg.wait_for_function(
                "n => { const r = document.querySelector('#gvBids tr:nth-child(2) td'); return r && r.innerText.trim() !== n; }",
                arg=first_before)
            page_no += 1
    return list(out.values())
