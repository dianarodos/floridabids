"""Pages we only watch, because their layout can't tell us what is open.

Two modes, set in sources.yaml:
- default: the page says "there are no bids..."; when that sentence disappears, fail loudly.
- `latest: <text>`: an archive-style page listing past solicitations newest first; when the
  newest solicitation link is no longer <text>, fail loudly.
A failure shows up in the run's health report so the page can get a proper reader.
"""
import re

from bs4 import BeautifulSoup

from .. import net

EMPTY = re.compile(r"(?:there (?:are|is) (?:currently )?no|(?:does|do) not (?:currently )?have any|no (?:open|active|current))"
                   r"\s+(?:open |active |current )?(?:bids?|rfps?|solicitations?)", re.I)
SOLICITATION = re.compile(r"^\s*(?:RFP|RFQ|RFI|ITB|IFB|ITN|BID)\b", re.I)


def newest(soup) -> str:
    main = soup.select_one("#moduleContent, main") or soup
    for a in main.find_all("a"):
        t = " ".join(a.get_text(" ").split())
        if SOLICITATION.match(t):
            return t
    return ""


def read(src):
    soup = BeautifulSoup(net.get(src["url"]).text, "lxml")
    if src.get("latest"):
        top = newest(soup)
        if top.lower().startswith(src["latest"].lower()):
            return []
        raise RuntimeError(f"newest listing changed to {top!r} - check the page for a new solicitation")
    if EMPTY.search(" ".join(soup.get_text(" ").split())):
        return []
    raise RuntimeError("page no longer says 'no bids' - it now lists something and needs a reader")
