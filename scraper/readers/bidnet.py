"""BidNet Direct: the agency's open-bids page. robots.txt disallows ?page= URLs, so we read page 1 only
(the open list is short for these counties) and log a warning if BidNet shows more pages."""
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import net
from ..dates import is_future
from . import make_bid

log = logging.getLogger(__name__)

FL_COUNTIES = ("Alachua Baker Bay Bradford Brevard Broward Calhoun Charlotte Citrus Clay Collier Columbia DeSoto "
               "Dixie Duval Escambia Flagler Franklin Gadsden Gilchrist Glades Gulf Hamilton Hardee Hendry Hernando "
               "Highlands Hillsborough Holmes Indian_River Jackson Jefferson Lafayette Lake Lee Leon Levy Liberty "
               "Madison Manatee Marion Martin Miami-Dade Monroe Nassau Okaloosa Okeechobee Orange Osceola Palm_Beach "
               "Pasco Pinellas Polk Putnam St._Johns St._Lucie Santa_Rosa Sarasota Seminole Sumter Suwannee Taylor "
               "Union Volusia Wakulla Walton Washington").split()
FL_COUNTIES = [c.replace("_", " ") for c in FL_COUNTIES]
_COUNTY_RE = re.compile(r"\b(" + "|".join(re.escape(c).replace(r"\.", r"\.?") for c in
                                          sorted(FL_COUNTIES, key=len, reverse=True)) + r")\s+County\b", re.I)


def county_in_title(title):
    """'RFP-2026-010 Child Care Providers Palm Beach County' -> 'Palm Beach' (for statewide agencies)."""
    m = _COUNTY_RE.search(title.replace("Dade County", "Miami-Dade County").replace("Miami-Miami", "Miami"))
    if not m:
        return ""
    found = m.group(1).replace(".", "").lower()
    return next(c for c in FL_COUNTIES if c.replace(".", "").lower() == found)


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
        if src.get("county_from_title"):
            b.county = county_in_title(b.title) or b.county
        if is_future(b.due) is not False:
            out.append(b)
    if soup.select_one(".mets-pagination a[href*='page=']"):
        log.warning("%s: BidNet shows more than one page; only page 1 is read (robots.txt)", src["id"])
    return out
