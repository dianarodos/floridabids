"""Match bids to a subscriber's business: picked business types (config/business_types.yaml) plus free keywords.

    python -m scraper.interests food "window tint"   # print the open bids that would match
"""
from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "business_types.yaml"
PUBLIC = ROOT / "site" / "data" / "business_types.json"


@lru_cache(maxsize=1)
def types() -> list[dict]:
    return yaml.safe_load(CONFIG.read_text())


def _term_rx(term: str, prefix: bool = False) -> str:
    term = term.strip().lower()
    if term.endswith("*"):
        term, prefix = term[:-1], True
    body = r"\s+".join(re.escape(w) for w in term.split())
    return r"(?<![a-z0-9])" + body + (r"[a-z0-9-]*" if prefix else r"(?:s|es)?(?![a-z0-9])")


@lru_cache(maxsize=512)
def _compile(ids: tuple, keywords: tuple):
    by_id = {t["id"]: t for t in types()}
    parts = [_term_rx(term) for i in ids if i in by_id for term in by_id[i]["terms"]]
    parts += [_term_rx(k, prefix=True) for k in keywords if k.strip()]
    return re.compile("|".join(parts), re.I) if parts else None


def parse_keywords(text: str) -> tuple:
    """'window tint, catering; ice' -> ('window tint', 'catering', 'ice'). Max 15, 2..40 chars each."""
    out = []
    for k in re.split(r"[,;\n]+", text or ""):
        k = " ".join(re.sub(r"[^\w\s/&-]", " ", k).split()).lower()
        if 2 <= len(k) <= 40 and k not in out:
            out.append(k)
    return tuple(out[:15])


def matcher(interests, keywords):
    """Returns f(bid) -> bool, or None when the subscriber picked nothing."""
    ids = tuple(sorted(i for i in (interests or []) if isinstance(i, str)))
    kws = parse_keywords(keywords if isinstance(keywords, str) else ", ".join(keywords or []))
    rx = _compile(ids, kws)
    cats = {c for t in types() if t["id"] in ids for c in t.get("categories", [])}
    if rx is None and not cats:
        return None
    return lambda b: (b.get("category") in cats or
                      bool(rx and rx.search(" ".join(str(b.get(f) or "") for f in ("title", "agency_category")))))


def describe(interests, keywords) -> str:
    labels = {t["id"]: t["label"] for t in types()}
    parts = [labels[i] for i in (interests or []) if i in labels]
    parts += [f'"{k}"' for k in parse_keywords(keywords if isinstance(keywords, str) else ", ".join(keywords or []))]
    return ", ".join(parts)


def export_public():
    """The sign-up form and preferences page only need id + label."""
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.write_text(json.dumps([{"id": t["id"], "label": t["label"]} for t in types()], indent=1))


if __name__ == "__main__":
    bids = json.loads((ROOT / "site" / "data" / "bids.json").read_text())["bids"]
    ids = [a for a in sys.argv[1:] if a in {t["id"] for t in types()}]
    kws = ", ".join(a for a in sys.argv[1:] if a not in ids)
    m = matcher(ids, kws)
    hits = [b for b in bids if m and m(b)]
    print(f"{len(hits)} of {len(bids)} open bids match {describe(ids, kws)}")
    for b in hits[:80]:
        print(f"  {b['county']:<14} {b['title'][:90]}")
