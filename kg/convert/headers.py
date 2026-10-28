"""Running-header filter, ported from extraction/extract.py (walk_to_index).

Docling labels most page headers itself (page_header); this catches short
headings that repeat on a large share of pages. It is applied to the Markdown
copy and, later, to segmentation; the JSON stays lossless.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

RUNNING_SHARE = 0.30       # a heading on >= 30% of pages ...
RUNNING_MIN_PAGES = 8      # ... and on at least 8 pages is a running header
MAX_LEN = 45               # only short headings


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", " ", s).strip()


def running_headings(items: Iterable[tuple[str, str, int | None]]) -> set[str]:
    """items: (label, text, page). Returns normalised heading texts that are running headers.

    Section headings a book repeats per crop ("CROP PROTECTION") appear on a few
    percent of pages and are kept.
    """
    pages, by_text = set(), defaultdict(set)
    for label, text, page in items:
        if page is not None:
            pages.add(page)
        if label in ("section_header", "title") and text and len(text) <= MAX_LEN:
            by_text[norm(text)].add(page)
    limit = max(RUNNING_MIN_PAGES, int(RUNNING_SHARE * len(pages)))
    return {t for t, p in by_text.items() if len(p) >= limit}


def doc_items(doc) -> list[tuple[str, str, int | None]]:
    """(label, text, page) for every item of a DoclingDocument."""
    out = []
    for item, _ in doc.iterate_items():
        label = getattr(getattr(item, "label", None), "value", "")
        prov = getattr(item, "prov", None) or []
        out.append((str(label), getattr(item, "text", "") or "", prov[0].page_no if prov else None))
    return out
