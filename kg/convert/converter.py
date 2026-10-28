"""Docling set-up, ported from extraction/extract.py (get_converter, torch_device, OOM fallback).

OCR settings come from the registry entry's [extraction] table:
  ocr = "auto"  -> OcrMode.DEFAULT: OCR only layout regions with no PDF text cells
  ocr = "force" -> OcrMode.FULL_PAGE: OCR every page (legacy-font text layers)
"""

import logging
import os
import time
from importlib.metadata import version

log = logging.getLogger("kg.convert")

PACKAGES = ("docling", "docling-core", "docling-parse", "docling-ibm-models", "easyocr")


def versions() -> dict[str, str]:
    return {p: version(p) for p in PACKAGES}


def device(force_cpu: bool = False) -> str:
    if force_cpu:
        return "cpu"
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def settings(entry, pages: tuple[int, int] | None = None) -> dict:
    """Everything that changes the output; part of the cache key."""
    ex = entry.extraction
    page_range = pages or ex.page_range
    return {
        "ocr_engine": "easyocr",
        "ocr": ex.ocr,
        "ocr_lang": list(ex.ocr_lang),
        "page_range": list(page_range) if page_range else None,
        "table_mode": "accurate",
        "picture_images": True,
    }


def build(cfg: dict, dev: str):
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (EasyOcrOptions, OcrMode, PdfPipelineOptions,
                                                    TableFormerMode)
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.ocr_options = EasyOcrOptions(
        lang=cfg["ocr_lang"], use_gpu=(dev == "cuda"),
        mode=OcrMode.FULL_PAGE if cfg["ocr"] == "force" else OcrMode.DEFAULT)
    opts.do_table_structure = True
    opts.table_structure_options.mode = TableFormerMode.ACCURATE
    opts.generate_picture_images = True
    opts.generate_parsed_pages = True      # keeps text cells, so we can tell which pages were OCR'd
    opts.accelerator_options = AcceleratorOptions(num_threads=min(8, os.cpu_count() or 1), device=dev)
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    return conv, InputFormat.PDF


def run(pdf_path, cfg: dict, force_cpu: bool = False):
    """Convert; returns (ConversionResult, device, seconds to load models, seconds to convert)."""
    dev = device(force_cpu)
    conv, fmt = build(cfg, dev)
    t0 = time.perf_counter()
    conv.initialize_pipeline(fmt)          # load models first, so conversion time is measured alone
    t1 = time.perf_counter()
    kwargs = {"page_range": tuple(cfg["page_range"])} if cfg["page_range"] else {}
    try:
        result = conv.convert(str(pdf_path), **kwargs)
    except Exception as e:
        if dev == "cuda" and ("CUDA" in str(e) or "out of memory" in str(e).lower()):
            log.warning("CUDA out of memory; retrying on CPU (slower)")
            return run(pdf_path, cfg, force_cpu=True)
        raise
    return result, dev, t1 - t0, time.perf_counter() - t1
