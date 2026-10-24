"""Light rule-based classifier: one category and one solicitation type per bid.

Edit the keyword lists in config/categories.yaml rather than here.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "categories.yaml"

TYPE_PATTERNS = [
    ("Draft / Future", r"\b(draft|future solicitation|upcoming solicitation)\b"),
    ("Pre-solicitation", r"\bpre-?solicitation\b"),
    ("Sole source", r"\b(sole|single)[\s-]source\b"),
    ("RFI", r"\b(RFI|request for information)\b"),
    ("ITN", r"\b(ITN|invitation to negotiate)\b"),
    ("RFQ (qualifications)", r"\b(RFQu|RSQ|request for (statement of )?qualifications|CCNA)\b"),
    ("RFP", r"\b(RFP|request for proposals?)\b"),
    ("ITB", r"\b(ITB|IFB|IFBC|invitation (to|for) bids?|request for bids?|RFB)\b"),
    ("Quote", r"\b(RFQ|ITQ|quote|quotation)\b"),
    ("Property sale / lease", r"\b(sale of|lease of|surplus property|purchase county)\b.*\b(property|land|acres?|parcel)\b"),
    ("Notice", r"\b(public notice|notice of)\b"),
]


@lru_cache(maxsize=1)
def _rules():
    data = yaml.safe_load(CONFIG.read_text())
    out = []
    for cat in data["categories"]:
        words = [w.lower() for w in cat["keywords"]]
        # short words (AI, IT, GIS) must match whole words; longer ones match word starts (pav -> paving)
        parts = [re.escape(w) + (r"\b" if len(w) < 4 else "") for w in words]
        pat = re.compile(r"\b(" + "|".join(parts) + r")", re.I)
        out.append((cat["name"], pat, cat.get("weight", 1.0)))
    return out, data.get("agency_category_map", {}), data.get("fallback", "Other")


def classify(title: str, agency_category: str = "", extra_text: str = "") -> str:
    rules, cat_map, fallback = _rules()
    if agency_category:
        for key, cat in cat_map.items():
            if key.lower() in agency_category.lower():
                return cat
    text = f"{title} {extra_text}"
    best, best_score = fallback, 0.0
    for name, pat, weight in rules:
        hits = pat.findall(text)
        if not hits:
            continue
        # title hits count double
        score = weight * (len(hits) + len(pat.findall(title)))
        if score > best_score:
            best, best_score = name, score
    return best


def detect_type(number: str, title: str, given: str = "") -> str:
    blob = f"{given} {number} {title}"
    for name, pat in TYPE_PATTERNS:
        if re.search(pat, blob, re.I):
            return name
    return given.strip() or ""
