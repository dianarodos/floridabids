"""Pages that currently say there are no bids. We can't know their layout yet, so we only watch:
while the "nothing open" sentence is there, return nothing; once it disappears, fail loudly so
the run's health report shows the page needs a proper reader (or a due_table/civicplus one).
"""
import re

from bs4 import BeautifulSoup

from .. import net

EMPTY = re.compile(r"there (?:are|is) (?:currently )?no (?:open |active |current )?(?:bids|rfps|solicitations)", re.I)


def read(src):
    text = BeautifulSoup(net.get(src["url"]).text, "lxml").get_text(" ")
    if EMPTY.search(" ".join(text.split())):
        return []
    raise RuntimeError("page no longer says 'no bids' - it now lists something and needs a reader")
