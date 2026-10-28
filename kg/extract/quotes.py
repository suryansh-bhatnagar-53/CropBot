"""The step 9 quote check: a fact's quote must be found exactly in the text the model was
given, after normalising both sides the same way. Nothing is corrected."""

import re
import unicodedata

# hyphen, non-breaking hyphen, figure dash, en dash, em dash, horizontal bar, minus, small/fullwidth hyphen-minus
DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹘﹣－"), "-")


def normalise(text: str) -> str:
    """NFKC (ligatures, and e.g. "m²" -> "m2"), soft hyphens removed, dashes -> "-",
    whitespace collapsed."""
    text = unicodedata.normalize("NFKC", text).replace("­", "").translate(DASHES)
    return re.sub(r"\s+", " ", text).strip()


class QuoteIndex:
    """The unit's text as segments (one per item, sub-heading or table row), joined by a
    space, so a quote may run across consecutive segments."""

    def __init__(self, segments: list[dict]):
        self.segments, parts, self.starts, pos = segments, [], [], 0
        for seg in segments:
            text = normalise(seg["text"])
            self.starts.append((pos, pos + len(text)))
            parts.append(text)
            pos += len(text) + 1
        self.text = " ".join(parts)

    def find(self, quote: str) -> dict:
        q = normalise(quote)
        hits = [m.start() for m in re.finditer(re.escape(q), self.text)] if q else []
        segs = []
        for h in hits:
            segs.append([i for i, (a, b) in enumerate(self.starts) if a < h + len(q) and h < b])
        first = [self.segments[i] for i in segs[0]] if segs else []
        # a segment may lie on several pages (a table row merged across a page break)
        pages = {p for s in first for p in (s.get("pdf_pages") or [s.get("pdf_page")]) if p}
        printed = {p for s in first for p in (s.get("printed_pages") or [s.get("printed_page")]) if p}
        return {"ok": bool(hits), "occurrences": len(hits),
                "refs": [s["ref"] for s in first],
                "pdf_pages": sorted(pages), "printed_pages": sorted(printed)}
