import argparse
import json
import sys

from kg.load.db import get_driver

from . import TEMPLATES, FarmContext, answer


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kg.query", description="Step 14: answer a farm question")
    ap.add_argument("template", choices=sorted(TEMPLATES))
    ap.add_argument("--context", required=True, help="a JSON farm context, or a fixture file with a 'context' key")
    ap.add_argument("--database", help="the Neo4j database to read (default: the server's home database)")
    a = ap.parse_args(argv)
    with open(a.context, encoding="utf-8") as f:
        data = json.load(f)
    ctx = FarmContext.model_validate(data.get("context", data))
    with get_driver() as driver:
        print(json.dumps(answer(driver, a.template, ctx, a.database), indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
