import argparse
import json
import logging

from kg.registry import RegistryError, read_registry

from . import convert
from .report import build_report, print_report


def main():
    ap = argparse.ArgumentParser(prog="python -m kg.convert", description="Docling conversion")
    ap.add_argument("source_id", help="registry id, e.g. source:tnau_agriculture_2020")
    ap.add_argument("--pages", help="trial page range, e.g. 13-76 (writes to trial_p13-76/)")
    ap.add_argument("--force", action="store_true", help="convert even if the cache matches")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for noisy in ("docling", "docling_core", "easyocr", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        entries = {e.id: e for e in read_registry()}
    except RegistryError as e:
        raise SystemExit("registry is invalid:\n  " + "\n  ".join(e.problems))
    if args.source_id not in entries:
        raise SystemExit("not in the registry: %s (have: %s)" % (args.source_id, ", ".join(entries)))
    pages = tuple(int(p) for p in args.pages.split("-")) if args.pages else None

    out, meta, cached = convert(entries[args.source_id], pages, force=args.force)
    print("%s: %s" % ("cache hit, not re-run" if cached else "converted", out))
    report = build_report(out, entries[args.source_id], meta)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print_report(report)


main()
