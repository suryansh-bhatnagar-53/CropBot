import argparse
import json
import sys
from pathlib import Path

from kg.load.db import get_driver

from . import SNAPSHOT_DIR, ExportError, check, load, secrets_in, write


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kg.export", description="The graph as committed files (kg_snapshot/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write kg_snapshot/ from the database")
    w.add_argument("--database", default="neo4j")
    w.add_argument("--dump", action="store_true", help="also stop, dump and restart the database (only when the graph changed)")
    c = sub.add_parser("check", help="compare kg_snapshot/ with the database; no writes")
    c.add_argument("--database", default="neo4j")
    lo = sub.add_parser("load", help="rebuild an empty, non-home database from the JSONL")
    lo.add_argument("--database", required=True)
    lo.add_argument("--into-empty-home", action="store_true",
                    help="allow the home database, only if it has 0 nodes and 0 relationships (Community, AuraDB Free)")
    sub.add_parser("secrets", help="check kg_snapshot/ for .env secrets and key-like strings")
    for p in (w, c, lo):
        p.add_argument("--dir", default=str(SNAPSHOT_DIR), help="the snapshot folder (default kg_snapshot/)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "secrets":
            texts = {p.name: p.read_text(encoding="utf-8") for p in SNAPSHOT_DIR.iterdir() if p.suffix in (".jsonl", ".json")}
            found = secrets_in(texts)
            print("secrets found: %s" % found if found else "no secrets in %s (%s)" % (SNAPSHOT_DIR, ", ".join(sorted(texts))))
            return 1 if found else 0
        with get_driver() as driver:
            if a.cmd == "write":
                m = write(driver, a.database, Path(a.dir), a.dump)
                print(json.dumps({k: m[k] for k in ("snapshot", "counts", "files") if k in m} | {"dump": m.get("dump")},
                                 indent=1))
            elif a.cmd == "check":
                problems = check(driver, a.database, Path(a.dir))
                print("\n".join(problems) if problems else "kg_snapshot/ matches %s" % a.database)
                return 1 if problems else 0
            else:
                print(json.dumps(load(driver, a.database, Path(a.dir), a.into_empty_home), indent=1))
    except ExportError as e:
        print("refused: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
