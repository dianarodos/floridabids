"""Platform readers. Each reader takes one source dict from sources.yaml and returns a list of Bid.

Register a reader by adding it to READERS below. Readers must page through every page of results.
"""
from __future__ import annotations

from ..classify import classify, detect_type
from ..dates import parse_due
from ..models import Bid


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
        county=src["county"],
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
