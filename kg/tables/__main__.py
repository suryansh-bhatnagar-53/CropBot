import argparse

from kg.convert import output_dir
from kg.registry import RegistryError, read_registry
from kg.segment import UNITS_DIR

from . import print_report, run, write


def main():
    ap = argparse.ArgumentParser(prog="python -m kg.tables", description="Stitch, check and pivot tables")
    ap.add_argument("source_id")
    ap.add_argument("--chapters", help="chapter titles, comma-separated (default: the source's approved chapters)")
    args = ap.parse_args()
    try:
        entries = {e.id: e for e in read_registry()}
    except RegistryError as e:
        raise SystemExit("registry is invalid:\n  " + "\n  ".join(e.problems))
    if args.source_id not in entries:
        raise SystemExit("not in the registry: %s" % args.source_id)
    entry = entries[args.source_id]
    units = UNITS_DIR / entry.id.split(":", 1)[1] / "units.jsonl"
    if not units.exists():
        raise SystemExit("no units at %s; run uv run python -m kg.segment %s" % (units, entry.id))
    chapters = (tuple(c.strip() for c in args.chapters.split(",")) if args.chapters
                else tuple(c.path_label() for c in entry.chapters if c.status == "approved"))
    result = run(entry, output_dir(entry), units, chapters)
    print_report(write(entry, result))


main()
