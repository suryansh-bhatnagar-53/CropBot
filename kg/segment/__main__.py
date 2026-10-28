import argparse
from pathlib import Path

from kg.convert import output_dir
from kg.registry import RegistryError, read_registry
from kg.transcribe import TranscriptionError

from .fixes import FixError
from .report import print_report, segment, write


def main():
    ap = argparse.ArgumentParser(prog="python -m kg.segment", description="Section units, no LLM")
    ap.add_argument("source_id")
    ap.add_argument("--docling-dir", type=Path, help="default: the full conversion of the source")
    args = ap.parse_args()
    try:
        entries = {e.id: e for e in read_registry()}
    except RegistryError as e:
        raise SystemExit("registry is invalid:\n  " + "\n  ".join(e.problems))
    if args.source_id not in entries:
        raise SystemExit("not in the registry: %s" % args.source_id)
    entry = entries[args.source_id]
    docling_dir = args.docling_dir or output_dir(entry)
    if not (docling_dir / "document.json").exists():
        raise SystemExit("no conversion at %s; run uv run python -m kg.convert %s"
                         % (docling_dir, entry.id))
    try:
        units, report = segment(entry, docling_dir)
    except FixError as e:
        raise SystemExit("approved fixes do not match the conversion; nothing written:\n  "
                         + "\n  ".join(e.problems))
    except TranscriptionError as e:
        raise SystemExit("transcriptions cannot be used; nothing written:\n  " + "\n  ".join(e.problems))
    out = write(entry, units, report)
    print_report(report)
    print("written:", out)
    if report["failed"]:
        raise SystemExit(1)


main()
