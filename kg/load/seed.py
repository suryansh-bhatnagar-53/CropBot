"""Validate the concept seed files in concepts/ and MERGE them into Neo4j.

  uv run python -m kg.load.seed --check     validate only, no database
  uv run python -m kg.load.seed --counts    print node and relationship counts, no writes
  uv run python -m kg.load.seed             constraints + load + counts

A row containing TODO anywhere is skipped and listed as pending. Nothing is
written unless every other row validates.
"""

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from kg.schema.concepts import CLOSED_LISTS, SEED_FILES

from .constraints import ensure_constraints
from .db import ROOT, counts, get_driver

CONCEPTS_DIR = ROOT / "concepts"


class SeedError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass
class Seed:
    nodes: list          # validated concept and Label models
    pending: list[str]   # "file:line" of rows skipped because they contain TODO


def read_seed(directory: Path = CONCEPTS_DIR) -> Seed:
    problems, nodes, pending = [], [], []
    first_seen: dict[str, str] = {}
    for name, model in SEED_FILES.items():
        path = directory / name
        if not path.exists():
            problems.append("%s: file missing" % name)
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            for line, row in enumerate(csv.DictReader(f), start=2):
                where = "%s:%d" % (name, line)
                if any("TODO" in (v or "") for v in row.values()):
                    pending.append(where)
                    continue
                try:
                    node = model.model_validate({k: v for k, v in row.items() if v})
                except ValidationError as e:
                    problems += ["%s: %s: %s" % (where, ".".join(map(str, err["loc"])) or "row",
                                                 err["msg"]) for err in e.errors()]
                    continue
                if node.id in first_seen:
                    problems.append("%s: duplicate id %s (first in %s)"
                                    % (where, node.id, first_seen[node.id]))
                    continue
                first_seen[node.id] = where
                nodes.append(node)

    label_of = {n.id: n.LABEL for n in nodes}
    for n in nodes:
        for field, target, target_label in n.references():
            found = label_of.get(target)
            ok = found is not None and (found == target_label
                                        or (target_label == "Concept" and found != "Label"))
            if not ok:
                problems.append("%s: %s %s is not a loaded %s"
                                % (first_seen[n.id], field, target, target_label))

    for model, vocab in CLOSED_LISTS.items():
        have = {n.id.split(":", 1)[1] for n in nodes if isinstance(n, model)}
        missing = sorted({m.value for m in vocab} - have)
        if missing:
            problems.append("%s list is incomplete, missing: %s" % (model.LABEL, ", ".join(missing)))

    if problems:
        raise SeedError(problems)
    return Seed(nodes, pending)


def is_primitive(value) -> bool:
    """What Neo4j accepts as a property: a primitive or a flat array of them, never a map."""
    if isinstance(value, list):
        return all(isinstance(v, (str, int, float, bool)) for v in value)
    return value is None or isinstance(value, (str, int, float, bool))


def load(driver, seed: Seed, database=None) -> Counter:
    """MERGE every node on id, then MERGE its edges (with their properties). Safe to run any
    number of times: a second run creates nothing. Returns what this run created."""
    by_label = defaultdict(list)
    edges = defaultdict(list)
    for n in seed.nodes:
        props = n.props()
        bad = {k: v for k, v in props.items() if not is_primitive(v)}
        if bad:
            raise SeedError(["%s: property %s is not a Neo4j primitive: %r" % (n.id, k, v) for k, v in bad.items()])
        by_label[n.LABEL].append({"id": n.id, "props": props})
        for rel, target_label, target, rel_props in n.edges():
            edges[(n.LABEL, rel, target_label)].append({"src": n.id, "dst": target, "props": rel_props})
    created = Counter()

    def run(query, rows):
        summary = driver.execute_query(query, rows=rows, database_=database).summary.counters
        created["nodes"] += summary.nodes_created
        created["relationships"] += summary.relationships_created

    for label, rows in by_label.items():
        labels = label if label == "Label" else "Concept:" + label
        run("UNWIND $rows AS row MERGE (n:%s {id: row.id}) SET n += row.props" % labels, rows)
    for (src, rel, dst), rows in edges.items():
        scheme = ", r.scheme = b.scheme" if rel == "IN_ZONE" else ""
        run("UNWIND $rows AS row MATCH (a:%s {id: row.src}) MATCH (b:%s {id: row.dst}) "
            "MERGE (a)-[r:%s]->(b) SET r += row.props%s" % (src, dst, rel, scheme), rows)
    return created


def print_counts(driver) -> None:
    nodes, rels = counts(driver)
    print("Nodes by label:" if nodes else "Nodes by label: (none)")
    for label, n in nodes.items():
        print("  %-20s %5d" % (label, n))
    print("Relationships by type:" if rels else "Relationships by type: (none)")
    for rel, n in rels.items():
        print("  %-20s %5d" % (rel, n))


def main():
    ap = argparse.ArgumentParser(description="Validate and load concepts/ into Neo4j")
    ap.add_argument("--check", action="store_true", help="validate only, no database")
    ap.add_argument("--counts", action="store_true", help="print counts only, no writes")
    args = ap.parse_args()

    if args.counts:
        with get_driver() as driver:
            print_counts(driver)
        return
    try:
        seed = read_seed()
    except SeedError as e:
        raise SystemExit("seed files are invalid:\n  " + "\n  ".join(e.problems))
    print("valid: %d nodes; pending (TODO, not loaded): %d rows" % (len(seed.nodes), len(seed.pending)))
    per_file = defaultdict(list)
    for where in seed.pending:
        name, line = where.split(":")
        per_file[name].append(line)
    for name, lines in per_file.items():
        print("  pending %s lines %s" % (name, ", ".join(lines)))
    if args.check:
        return
    with get_driver() as driver:
        print("id uniqueness constraints:", ensure_constraints(driver))
        created = load(driver, seed)
        print("this run created: %d nodes, %d relationships" % (created["nodes"], created["relationships"]))
        print_counts(driver)


if __name__ == "__main__":
    main()
