"""Convert a registered PDF with Docling into data/docling/<source_id>/ (gitignored).

  uv run python -m kg.convert source:tnau_agriculture_2020 [--pages 13-76] [--force]

Output: document.json (lossless DoclingDocument, pictures as PNGs in images/),
document.md (readable copy with page markers), meta.json (versions, settings,
sha256, cache key, timing, OCR pages). A run is skipped when meta.json has the
same cache key: sha256 + Docling versions + settings. --pages writes to a
trial_p<a>-<b>/ subfolder so it never replaces the full conversion.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from kg.registry import ROOT, sha256_file

from . import converter
from .headers import doc_items, norm, running_headings

OUT = ROOT / "data" / "docling"
FILES = ("document.json", "document.md", "meta.json", "report.json")
log = logging.getLogger("kg.convert")


def output_dir(entry, pages: tuple[int, int] | None = None) -> Path:
    base = OUT / entry.id.split(":", 1)[1]
    return base / ("trial_p%d-%d" % pages) if pages else base


def cache_key(sha256: str, versions: dict, settings: dict) -> str:
    blob = json.dumps({"sha256": sha256, "versions": versions, "settings": settings}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def page_marker(pdf_page: int, printed: str | None) -> str:
    return "<!-- PDF p. %d | printed p. %s -->" % (pdf_page, printed or "none")


def markdown(doc, entry) -> str:
    """Readable copy: one block per page, running headers removed."""
    running = running_headings(doc_items(doc))
    parts = []
    for page in sorted(doc.pages):
        text = doc.export_to_markdown(page_no=page)
        lines = [l for l in text.splitlines()
                 if not (re.match(r"^#{1,6} ", l) and norm(l.lstrip("#")) in running)]
        parts.append(page_marker(page, entry.printed_page(page)) + "\n\n" + "\n".join(lines).strip())
    return "\n\n".join(parts) + "\n"


def ocr_pages(pages) -> dict:
    """From ConversionResult.pages: where OCR produced text, where all text came from OCR,
    and where there was no text at all (blank or image-only and nothing recognised).
    Page.page_no is the 1-based PDF page in docling 2.140."""
    with_ocr, only_ocr, no_text = [], [], []
    for page in pages:
        cells = getattr(getattr(page, "parsed_page", None), "textline_cells", None) or []
        n_ocr = sum(1 for c in cells if c.from_ocr)
        if not cells:
            no_text.append(page.page_no)
        elif n_ocr == len(cells):
            only_ocr.append(page.page_no)
        if n_ocr:
            with_ocr.append(page.page_no)
    return {"pages_with_ocr_text": with_ocr, "pages_without_text_layer": only_ocr,
            "pages_without_any_text": no_text}


def convert(entry, pages: tuple[int, int] | None = None, force: bool = False) -> tuple[Path, dict, bool]:
    """Returns (output folder, meta, True if the cached conversion was reused)."""
    from docling_core.types.doc import ImageRefMode

    pdf = ROOT / entry.file
    if sha256_file(pdf) != entry.sha256:
        raise SystemExit("sha256 mismatch for %s; run uv run python -m kg.registry" % entry.file)
    cfg = converter.settings(entry, pages)
    versions = converter.versions()
    key = cache_key(entry.sha256, versions, cfg)
    out = output_dir(entry, pages)
    meta_path = out / "meta.json"
    if not force and meta_path.exists() and (out / "document.json").exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("cache_key") == key:
            return out, meta, True

    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:                     # only this run's files; trial folders stay
        (out / name).unlink(missing_ok=True)
    log.info("converting %s %s", entry.id, "pages %d-%d" % pages if pages else "(all pages)")
    result, dev, load_s, convert_s = converter.run(pdf, cfg)
    doc = result.document
    doc.save_as_json(out / "document.json", artifacts_dir=out / "images",
                     image_mode=ImageRefMode.REFERENCED)
    (out / "document.md").write_text(markdown(doc, entry), encoding="utf-8")
    meta = {
        "source_id": entry.id, "file": entry.file, "sha256": entry.sha256,
        "versions": versions, "settings": cfg, "cache_key": key,
        "converted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device": dev, "status": str(getattr(result.status, "value", result.status)),
        "pages": len(doc.pages), "tables": len(doc.tables), "pictures": len(doc.pictures),
        "seconds_model_load": round(load_s, 1), "seconds_convert": round(convert_s, 1),
        "ocr": ocr_pages(result.pages),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")   # written last: no meta, no cache
    return out, meta, False
