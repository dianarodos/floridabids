"""City of Jacksonville: Oracle Fusion 'Solicitation Abstracts' (public). The table lazy-loads ~21 rows at a
time as you scroll, and may drop rows that scroll out of view, so rows are collected after each scroll.

Keep Status == Active with a close date not yet passed.
"""
from .. import browser
from ..dates import is_future
from . import make_bid

MAX_SCROLLS = 40
NUM_RE = r"^\d{4,6}-\d{2}"


def _visible_rows(pg):
    return pg.evaluate(
        """re => [...document.querySelectorAll('tr')].filter(r => r.cells.length >= 7 && new RegExp(re).test(r.cells[0].innerText.trim()))
             .map(r => ({ number: r.cells[0].innerText.trim(), title: r.cells[1].innerText.trim(), type: r.cells[2].innerText.trim(),
                          status: r.cells[3].innerText.trim(), posted: r.cells[4].innerText.trim(), close: r.cells[6].innerText.trim() }))""",
        NUM_RE)


def read(src):
    seen = {}
    with browser.page(src["url"], wait_for="tr td span") as pg:
        pg.wait_for_function("re => [...document.querySelectorAll('tr')].some(r => new RegExp(re).test((r.cells[0]||{}).innerText||''))",
                             arg=NUM_RE)
        stale = 0
        for _ in range(MAX_SCROLLS):
            before = len(seen)
            for r in _visible_rows(pg):
                seen.setdefault(r["number"], r)
            stale = stale + 1 if len(seen) == before else 0
            if stale >= 3:
                break
            pg.evaluate("""() => { const db = [...document.querySelectorAll('[id$="::db"]')].sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
                                   if (db) db.scrollTop = db.scrollHeight; else window.scrollTo(0, document.body.scrollHeight); }""")
            pg.wait_for_timeout(1500)
    out = []
    for r in seen.values():
        if r["status"].lower() != "active":
            continue
        b = make_bid(src, number=r["number"], title=r["title"], type_=r["type"], status=r["status"],
                     due_raw=r["close"], posted_raw=r["posted"],
                     notes=f"Search for {r['number']} on the City's Solicitation Abstracts page.")
        if is_future(b.due) is not False:
            out.append(b)
    return out
