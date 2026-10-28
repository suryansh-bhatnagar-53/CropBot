"""MERGE Source nodes and SUPERSEDES edges from the validated registry.

  uv run python -m kg.load.sources
"""

from kg.registry import RegistryError, read_registry

from .constraints import ensure_constraints
from .db import get_driver


def load_sources(driver, entries, database=None) -> None:
    rows = []
    for e in entries:
        source = e.to_source()
        rows.append({"id": source.id, "props": source.model_dump(mode="json", exclude={"id"})})
    driver.execute_query("UNWIND $rows AS row MERGE (s:Source {id: row.id}) SET s += row.props",
                         rows=rows, database_=database)
    edges = [{"new": e.id, "old": e.supersedes} for e in entries if e.supersedes]
    if edges:
        driver.execute_query("UNWIND $rows AS row MATCH (n:Source {id: row.new}) "
                             "MATCH (o:Source {id: row.old}) MERGE (n)-[:SUPERSEDES]->(o)",
                             rows=edges, database_=database)


def main():
    try:
        entries = read_registry()
    except RegistryError as e:
        raise SystemExit("registry is invalid, nothing loaded:\n  " + "\n  ".join(e.problems))
    with get_driver() as driver:
        ensure_constraints(driver)
        load_sources(driver, entries)
        # type() instead of a :SUPERSEDES pattern: no warning while no such edge exists yet
        records, _, _ = driver.execute_query(
            "MATCH (s:Source) OPTIONAL MATCH (s)-[r]->(:Source) WHERE type(r) = 'SUPERSEDES' "
            "RETURN count(DISTINCT s) AS sources, count(r) AS supersedes")
        print("Source nodes: %d, SUPERSEDES edges: %d"
              % (records[0]["sources"], records[0]["supersedes"]))


if __name__ == "__main__":
    main()
