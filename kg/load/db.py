"""Neo4j connection from .env (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)."""

import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")


def get_driver() -> Driver:
    load_dotenv(ROOT / ".env")
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        raise SystemExit("missing in .env: " + ", ".join(missing))
    return GraphDatabase.driver(os.environ["NEO4J_URI"],
                                auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))


def counts(driver: Driver) -> tuple[dict[str, int], dict[str, int]]:
    """Node counts by label and relationship counts by type."""
    nodes, _, _ = driver.execute_query(
        "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n ORDER BY label")
    rels, _, _ = driver.execute_query(
        "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type")
    return {r["label"]: r["n"] for r in nodes}, {r["type"]: r["n"] for r in rels}
