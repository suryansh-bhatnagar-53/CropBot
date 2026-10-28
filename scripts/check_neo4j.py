"""Connect to Neo4j with the settings in .env and print the server version.

Usage: uv run python scripts/check_neo4j.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")


def main():
    load_dotenv(ROOT / ".env")
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        sys.exit("missing in .env: " + ", ".join(missing))

    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth) as driver:
        driver.verify_connectivity()
        records, _, _ = driver.execute_query(
            "CALL dbms.components() YIELD name, versions, edition "
            "WHERE name = 'Neo4j Kernel' RETURN name, versions, edition"
        )
    for r in records:
        print("%s %s (%s edition)" % (r["name"], ", ".join(r["versions"]), r["edition"]))


if __name__ == "__main__":
    main()
