"""Turn the many date formats on county sites into one ISO form (Eastern time)."""
from __future__ import annotations

import re
from datetime import datetime, date, time

from dateutil import parser as dparser

from .models import ET, now_et

_TZ_WORDS = re.compile(r"\b(E[SD]T|C[SD]T|Eastern|Central|Local Time|local time)\b\.?", re.I)


def parse_due(text: str | None) -> str:
    """Return ISO string. Date-only values stay date-only (YYYY-MM-DD)."""
    if not text:
        return ""
    s = " ".join(str(text).split())
    if not s or s.lower() in {"n/a", "tbd", "-", "--"}:
        return ""
    central = bool(re.search(r"\bC[SD]T\b|Central", s, re.I))
    s = _TZ_WORDS.sub("", s).replace(" at ", " ").strip(" ,")
    s = re.sub(r"\b([ap])\.\s?m\.?", lambda m: m.group(1) + "m", s, flags=re.I)   # P.M. -> pm
    has_time = bool(re.search(r"\d{1,2}:\d{2}|\b\d{1,2}\s*[ap]\.?m\b", s, re.I))
    try:
        dt = dparser.parse(s, fuzzy=True)
    except (ValueError, OverflowError):
        return ""
    if not has_time:
        return dt.date().isoformat()
    if dt.tzinfo is None:
        if central:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo("America/Chicago")).astimezone(ET)
        else:
            dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET).isoformat(timespec="minutes")


def is_future(iso: str, grace_end_of_day: bool = True) -> bool | None:
    """True if still open. None if unknown. Date-only values count through end of that day."""
    if not iso:
        return None
    now = now_et()
    if len(iso) == 10:
        d = date.fromisoformat(iso)
        cutoff = datetime.combine(d, time(23, 59), tzinfo=ET) if grace_end_of_day else datetime.combine(d, time(0, 0), tzinfo=ET)
        return cutoff >= now
    return datetime.fromisoformat(iso) >= now
