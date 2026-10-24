"""VendorLink (Brevard, Osceola): ASP.NET search form with status filter and postback paging.

For each status in src['statuses'] (e.g. Active, All bids rejected): pick it in the Status box,
show 100 per page, search, then click through every page number.
The Agency column fills our Agency field (Osceola's portal also carries the School District).
"""
from .. import browser
from ..dates import is_future
from . import make_bid

MAX_PAGES = 15
GRID = "[id$='grvSolicitations']"


def _grab(pg):
    return pg.eval_on_selector_all(
        f"{GRID} > tbody > tr",
        """trs => trs.filter(r => r.querySelector("[id$='lblItemSolicitationDueDate']")).map(r => ({
            agency: r.cells[0].innerText.trim(), number: r.cells[1].innerText.trim(), title: r.cells[2].innerText.trim(),
            status: (r.querySelector('.badge') || r.cells[4]).innerText.trim(),
            posted: (r.querySelector("[id$='lblItemSolicitationBroadcastDate']") || {innerText: ''}).innerText.trim(),
            due: r.querySelector("[id$='lblItemSolicitationDueDate']").innerText.trim()
        }))""")


def read(src):
    agency_names = src.get("agency_names", {})
    out = {}
    for status in src.get("statuses", ["Active"]):
        with browser.page(src["url"], wait_for="select[id$='ddlStatus']") as pg:
            pg.select_option("select[id$='ddlStatus']", label=status)
            pg.check("input[name$='rblSolicitationPageCount'][value='100']")
            with pg.expect_navigation():
                pg.click("input[id$='btnSearch']")
            page_no = 1
            while page_no <= MAX_PAGES:
                if pg.locator(GRID).count() == 0:
                    break     # no results for this status
                first = None
                for r in _grab(pg):
                    first = first or r["number"]
                    if r["status"].lower() != status.lower():
                        continue
                    agency = agency_names.get(r["agency"], r["agency"] or src["agency"])
                    b = make_bid(src, agency=agency, number=r["number"], title=r["title"],
                                 due_raw=r["due"], posted_raw=r["posted"], status=r["status"],
                                 notes=f"Search for {r['number']} on the VendorLink page.")
                    # "All bids rejected" items stay listed even after the old due date (they are often re-bid)
                    if status.lower() != "active" or is_future(b.due) is not False:
                        out[b.key] = b
                nxt = pg.locator(f"{GRID} tr:last-child a", has_text=str(page_no + 1))
                if nxt.count() == 0:
                    more = pg.locator(f"{GRID} tr:last-child a", has_text="...")
                    if more.count() == 0:
                        break
                    nxt = more.last
                with pg.expect_navigation():
                    nxt.first.click()
                page_no += 1
    return list(out.values())
