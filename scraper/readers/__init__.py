"""Platform readers. Each reader takes one source dict from sources.yaml and returns a list of Bid.

Register a reader by adding it to READERS below. Readers must page through every page of results.
"""
from __future__ import annotations

from ..classify import classify, detect_type
from ..dates import parse_due
from ..models import Bid

import re as _re

FL_COUNTIES = ("Alachua Baker Bay Bradford Brevard Broward Calhoun Charlotte Citrus Clay Collier Columbia DeSoto "
               "Dixie Duval Escambia Flagler Franklin Gadsden Gilchrist Glades Gulf Hamilton Hardee Hendry Hernando "
               "Highlands Hillsborough Holmes Jackson Jefferson Lafayette Lake Lee Leon Levy Liberty Madison Manatee "
               "Marion Martin Monroe Nassau Okaloosa Okeechobee Orange Osceola Pasco Pinellas Polk Putnam Sarasota "
               "Seminole Sumter Suwannee Taylor Union Volusia Wakulla Walton Washington").split() + [
               "Indian River", "Miami-Dade", "Palm Beach", "Santa Rosa", "St. Johns", "St. Lucie"]
_COUNTY_RE = _re.compile(r"\b(" + "|".join(_re.escape(c).replace(r"\.", r"\.?").replace(r"\-", "[- ]?")
                                         for c in sorted(FL_COUNTIES, key=len, reverse=True)) + r")\s+County\b", _re.I)


def county_in_text(text: str) -> str:
    """'Child Care Providers Palm Beach County' -> 'Palm Beach' (canonical spelling), else ''."""
    m = _COUNTY_RE.search(text or "")
    if not m:
        return ""
    key = _re.sub(r"[^a-z]", "", m.group(1).lower())
    return next(c for c in FL_COUNTIES if _re.sub(r"[^a-z]", "", c.lower()) == key)


def make_bid(src: dict, *, title: str, number: str = "", due_raw: str = "", due_iso: str = "",
             status: str = "Open", type_: str = "", agency: str | None = None, posted_raw: str = "",
             bid_url: str = "", agency_category: str = "", notes: str = "", extra_text: str = "") -> Bid:
    title = " ".join((title or "").split())
    number = " ".join((number or "").split())
    due = due_iso or parse_due(due_raw)
    posted = parse_due(posted_raw)[:10] if posted_raw else ""
    btype = detect_type(number, title, type_)
    return Bid(
        source_id=src["id"],
        county=(src.get("county_from_title") and county_in_text(title)) or src["county"],
        agency=agency or src["agency"],
        title=title,
        number=number,
        type=btype,
        status=status.strip() or "Open",
        category=classify(title, agency_category, extra_text),
        agency_category=agency_category,
        posted=posted,
        due=due,
        bid_url=bid_url,
        source_url=src["url"],
        notes=notes,
    )


def get_reader(name: str):
    from . import (watch, bidnet, bidsandtenders, charlotte, due_table, govaccess, infor_fsm, civicplus, columbia, demandstar, jaxport, lake, miamidade, oracle_jax,
                   pbc_vss, planetbids, polk, putnam, vendorlink)
    readers = {
        "vendorlink": vendorlink.read,
        "demandstar": demandstar.read,
        "bidnet": bidnet.read,
        "planetbids": planetbids.read,
        "charlotte": charlotte.read,
        "columbia": columbia.read,
        "watch": watch.read,
        "due_table": due_table.read,
        "govaccess": govaccess.read,
        "infor_fsm": infor_fsm.read,
        "bidsandtenders": bidsandtenders.read,
        "civicplus": civicplus.read,
        "lake": lake.read,
        "polk": polk.read,
        "putnam": putnam.read,
        "jaxport": jaxport.read,
        "oracle_jax": oracle_jax.read,
        "pbc_vss": pbc_vss.read,
        "miamidade_future": miamidade.read_future,
        "miamidade_construction": miamidade.read_construction,
        "miamidade_informs": miamidade.read_informs,
    }
    return readers[name]
