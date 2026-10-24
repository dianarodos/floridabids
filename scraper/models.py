"""The one record type every reader produces."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(ET)


@dataclass
class Bid:
    source_id: str              # key from sources.yaml, e.g. "brevard-vendorlink"
    county: str
    agency: str
    title: str
    number: str = ""            # solicitation number as the agency writes it
    type: str = ""              # ITB, RFP, RFQ, RFI, ITN, Quote, Pre-solicitation, Draft ...
    status: str = "Open"        # as shown by the agency (Open, Active, All bids rejected, Upcoming ...)
    category: str = ""          # filled by classify.py unless the agency gives one
    agency_category: str = ""   # the agency's own category label, if any
    posted: str = ""            # ISO date
    due: str = ""               # ISO datetime (America/New_York) or date
    bid_url: str = ""           # page for this bid, when the platform has one
    source_url: str = ""        # the exact page we read it from
    notes: str = ""
    origin: str = "direct"      # direct | email | backfill
    first_seen: str = ""
    last_seen: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        ident = self.number.strip().lower() or hashlib.sha1(self.title.strip().lower().encode()).hexdigest()[:12]
        return f"{self.source_id}::{ident}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Bid":
        d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**d)
