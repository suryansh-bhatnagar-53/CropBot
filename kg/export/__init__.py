"""The graph as committed files (kg_snapshot/, 2026-10-24): a deterministic text export, a manifest and,
when the graph changed, a Neo4j dump.

  uv run python -m kg.export write [--database neo4j] [--dump]   # kg_snapshot/ from the database
  uv run python -m kg.export check [--database neo4j]            # kg_snapshot/ against the database, no writes
  uv run python -m kg.export load --database cropbot-test        # rebuild an EMPTY, non-home database from the JSONL
  uv run python -m kg.export load --database neo4j --into-empty-home   # Community / AuraDB Free: the empty home database
  uv run python -m kg.export secrets                             # kg_snapshot/ holds no .env secret

- nodes.jsonl: one node per line, {"id", "labels" (sorted), "props" (sorted keys)}, sorted by id.
- relationships.jsonl: {"type", "start", "end", "props"}, sorted by (type, start, end); no two relationships share
  a type and both ends, so these name one relationship.
- Values are primitives or flat lists, except Neo4j DateTime (created_at), written as {"$datetime": ISO}.
  Anything else is refused, never guessed. An unchanged graph re-exports byte for byte.
- manifest.json: the snapshot hash (kg.load.facts.snapshot), counts by label, type and fact status, the
  export time, the source commit, the Neo4j version and every file's sha256 and size.
- --dump: the database is stopped (STOP DATABASE ... WAIT), dumped with neo4j-admin from NEO4J_HOME using
  NEO4J_JAVA_HOME, and started again even if the dump fails. Commit the dump only when the graph changed.
- Nothing is written if a secret (.env PASSWORD/KEY/TOKEN/SECRET value, or a key-like string) is found.
"""

import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from neo4j.time import DateTime

from kg.load.constraints import NODE_LABELS, ensure_constraints
from kg.load.db import ROOT
from kg.load.facts import snapshot

SNAPSHOT_DIR = ROOT / "kg_snapshot"
NODES, RELS, MANIFEST, DUMP = "nodes.jsonl", "relationships.jsonl", "manifest.json", "neo4j.dump"
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")         # a label or relationship type that may enter Cypher
SECRET_NAMES = re.compile(r"PASSWORD|KEY|TOKEN|SECRET", re.I)
KEY_LIKE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}|\bBearer\s+[A-Za-z0-9._-]{16,}|"
                      r"(?i:\b(?:api[_-]?key|password|passwd|secret|token)\s*[:=]\s*[\"']?[^\s\"',}]{6,})")


class ExportError(Exception):
    pass


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def encode(value, where: str):
    if isinstance(value, DateTime):
        return {"$datetime": value.iso_format()}
    if isinstance(value, list):
        return [encode(v, where) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ExportError("%s: a %s value is not exported (only primitives, flat lists and DateTime)"
                      % (where, type(value).__name__))


def decode(value):
    if isinstance(value, dict) and set(value) == {"$datetime"}:
        return DateTime.from_iso_format(value["$datetime"])
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def read_graph(driver, database=None) -> tuple[list[dict], list[dict]]:
    rows, _, _ = driver.execute_query("MATCH (n) RETURN labels(n) AS labels, properties(n) AS props",
                                      database_=database)
    nodes = []
    for r in rows:
        props = dict(r["props"])
        if "id" not in props:
            raise ExportError("a node with labels %s has no id" % r["labels"])
        nid = props.pop("id")
        nodes.append({"id": nid, "labels": sorted(r["labels"]),
                      "props": {k: encode(v, "%s.%s" % (nid, k)) for k, v in props.items()}})
    rows, _, _ = driver.execute_query("MATCH (a)-[r]->(b) RETURN type(r) AS type, a.id AS start, b.id AS end, "
                                      "properties(r) AS props", database_=database)
    rels = [{"type": r["type"], "start": r["start"], "end": r["end"],
             "props": {k: encode(v, "%s %s->%s.%s" % (r["type"], r["start"], r["end"], k))
                       for k, v in r["props"].items()}} for r in rows]
    nodes.sort(key=lambda n: n["id"])
    rels.sort(key=lambda r: (r["type"], r["start"], r["end"]))
    ids = Counter(n["id"] for n in nodes)
    keys = Counter((r["type"], r["start"], r["end"]) for r in rels)
    problems = ["duplicate node id %s" % i for i, c in ids.items() if c > 1]
    problems += ["%d relationships %s %s->%s" % (c, *k) for k, c in keys.items() if c > 1]
    if problems:
        raise ExportError("; ".join(problems))
    return nodes, rels


def jsonl(items: list[dict]) -> bytes:
    return "".join(dumps(x) + "\n" for x in items).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def secrets_in(texts: dict[str, str]) -> list[str]:
    """Where a .env secret value or a key-like string occurs: "<file>: <variable name>" or "<file>: key-like
    string at offset N". Values are compared in memory and never printed."""
    env = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}
    secrets = {k: v for k, v in env.items() if v and SECRET_NAMES.search(k) and len(v) >= 4}
    found = []
    for name, text in texts.items():
        found += ["%s: the value of %s" % (name, k) for k, v in secrets.items() if v in text]
        found += ["%s: key-like string at offset %d" % (name, m.start()) for m in KEY_LIKE.finditer(text)]
    return found


def git_commit() -> dict:
    def run(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}


def facts_by_status(driver, database=None) -> dict:
    rows, _, _ = driver.execute_query(
        "MATCH (r:Recommendation)-[:EVIDENCED_BY]->(:SourceSpan)-[:IN_SOURCE]->(s:Source) WITH DISTINCT s, r "
        "RETURN s.id AS source, r.status AS status, count(*) AS n ORDER BY source, status", database_=database)
    out = defaultdict(dict)
    for r in rows:
        out[r["source"]][r["status"]] = r["n"]
    return dict(out)


def counts(nodes: list[dict], rels: list[dict]) -> dict:
    return {"nodes": len(nodes), "relationships": len(rels),
            "labels": dict(sorted(Counter(l for n in nodes for l in n["labels"]).items())),
            "types": dict(sorted(Counter(r["type"] for r in rels).items()))}


# --- the dump ---------------------------------------------------------------------------------------------

def _admin(*args) -> subprocess.CompletedProcess:
    home, java = os.environ.get("NEO4J_HOME"), os.environ.get("NEO4J_JAVA_HOME")
    if not home or not java:
        raise ExportError("--dump needs NEO4J_HOME and NEO4J_JAVA_HOME in .env (see .env.example)")
    tool = Path(home) / "bin" / ("neo4j-admin.bat" if os.name == "nt" else "neo4j-admin")
    return subprocess.run([str(tool), *args], capture_output=True, text=True,
                          env={**os.environ, "JAVA_HOME": java})


def dump(driver, database: str, out: Path) -> dict:
    """Stop the database, dump it to out/neo4j.dump, read its store format, start it again (always)."""
    driver.execute_query("STOP DATABASE `%s` WAIT" % database, database_="system")
    try:
        target = out / ("%s.dump" % database)
        if target.exists():
            target.unlink()                  # the previous dump of this folder; the new one replaces it
        done = _admin("database", "dump", database, "--to-path=%s" % out)
        if done.returncode != 0:
            raise ExportError("neo4j-admin dump failed (exit %d): %s" % (done.returncode, done.stderr[-800:]))
        info = _admin("database", "info", database)
        fmt = re.search(r"Store format version:\s*(\S+)", info.stdout)
    finally:
        driver.execute_query("START DATABASE `%s` WAIT" % database, database_="system")
    data = target.read_bytes()
    return {"file": target.name, "sha256": sha256(data), "bytes": len(data),
            "store_format": fmt.group(1) if fmt else None}


# --- write, check, load -----------------------------------------------------------------------------------

def write(driver, database: str = "neo4j", out: Path = SNAPSHOT_DIR, with_dump: bool = False) -> dict:
    nodes, rels = read_graph(driver, database)
    files = {NODES: jsonl(nodes), RELS: jsonl(rels)}
    found = secrets_in({k: v.decode("utf-8") for k, v in files.items()})
    if found:
        raise ExportError("secrets found, nothing written: %s" % "; ".join(found))
    snap = snapshot(driver, database)
    version, _, _ = driver.execute_query("CALL dbms.components() YIELD name, versions, edition "
                                         "RETURN name, versions[0] AS version, edition", database_="system")
    manifest = {"database": database, "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": git_commit(), "snapshot": snap, "counts": counts(nodes, rels),
                "facts_by_source_and_status": facts_by_status(driver, database),
                "neo4j": [r.data() for r in version][0],
                "files": {k: {"sha256": sha256(v), "bytes": len(v)} for k, v in files.items()}}
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    if with_dump:
        manifest["dump"] = dump(driver, database, out)
        after = snapshot(driver, database)
        if after != snap:
            raise ExportError("the snapshot changed during the dump: %s -> %s" % (snap["sha256"], after["sha256"]))
    elif (out / MANIFEST).exists():                  # keep the record of the dump that is in the folder
        old = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
        if old.get("dump"):
            manifest["dump"] = old["dump"]
    text = json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    found = secrets_in({MANIFEST: text})
    if found:
        raise ExportError("secrets found in the manifest, not written: %s" % "; ".join(found))
    (out / MANIFEST).write_text(text, encoding="utf-8", newline="\n")
    return manifest


def read_snapshot(src: Path = SNAPSHOT_DIR) -> tuple[list[dict], list[dict], dict]:
    manifest = json.loads((src / MANIFEST).read_text(encoding="utf-8"))
    data = {k: (src / k).read_bytes() for k in (NODES, RELS)}
    for k, v in data.items():
        if sha256(v) != manifest["files"][k]["sha256"]:
            raise ExportError("%s does not match its sha256 in the manifest" % k)
    nodes = [json.loads(line) for line in data[NODES].decode("utf-8").splitlines()]
    rels = [json.loads(line) for line in data[RELS].decode("utf-8").splitlines()]
    return nodes, rels, manifest


def check(driver, database: str = "neo4j", src: Path = SNAPSHOT_DIR) -> list[str]:
    """Differences between kg_snapshot/ and the database: the snapshot hash, then counts."""
    nodes, rels, manifest = read_snapshot(src)
    problems = []
    snap = snapshot(driver, database)
    if snap != manifest["snapshot"]:
        problems.append("snapshot %s (%d nodes, %d relationships) in the database, %s in the manifest" % (
            snap["sha256"][:12], snap["nodes"], snap["relationships"], manifest["snapshot"]["sha256"][:12]))
    have_nodes, have_rels = read_graph(driver, database)
    if counts(have_nodes, have_rels) != counts(nodes, rels):
        problems.append("counts differ: %s vs %s" % (counts(have_nodes, have_rels), counts(nodes, rels)))
    if have_nodes != nodes or have_rels != rels:
        problems.append("the JSONL differs from the database's export")
    return problems


def home_databases(driver) -> set[str]:
    homes, _, _ = driver.execute_query("SHOW DATABASES YIELD name, home WHERE home RETURN name", database_="system")
    return {r["name"] for r in homes}


def load(driver, database: str, src: Path = SNAPSHOT_DIR, into_empty_home: bool = False) -> dict:
    """Rebuild an empty database from the JSONL alone: constraints, nodes by label set, relationships by type,
    in one transaction. Refuses the system database and any database that is not empty. The home database is
    refused too unless `into_empty_home` is passed explicitly (2026-10-24: Community and AuraDB Free have only
    the home database), and even then only when it has 0 nodes and 0 relationships."""
    if not database or database == "system":
        raise ExportError("refusing %r: name the database to load" % database)
    home = database in home_databases(driver)
    if home and not into_empty_home:
        raise ExportError("refusing %r: it is the home database; load into another empty database, or pass "
                          "--into-empty-home if this server has only the home database and it is empty" % database)
    nodes_now = driver.execute_query("MATCH (n) RETURN count(n) AS n", database_=database)[0][0]["n"]
    rels_now = driver.execute_query("MATCH ()-[r]->() RETURN count(r) AS n", database_=database)[0][0]["n"]
    if nodes_now or rels_now:
        raise ExportError("refusing %r: it is not empty (%d nodes, %d relationships)%s" % (
            database, nodes_now, rels_now, "; --into-empty-home loads only a completely empty home database"
            if home else ""))
    nodes, rels, manifest = read_snapshot(src)
    allowed = set(NODE_LABELS)
    bad = sorted({l for n in nodes for l in n["labels"] if l not in allowed or not NAME.match(l)})
    bad += sorted({r["type"] for r in rels if not NAME.match(r["type"])})
    if bad:
        raise ExportError("labels or types not allowed: %s" % bad)
    ensure_constraints(driver, database)
    key_label = {n["id"]: next((l for l in n["labels"] if l != "Concept"), n["labels"][0]) for n in nodes}
    by_labels, by_type = defaultdict(list), defaultdict(list)
    for n in nodes:
        by_labels[tuple(n["labels"])].append({"id": n["id"], "props": {k: decode(v) for k, v in n["props"].items()}})
    for r in rels:
        by_type[(r["type"], key_label[r["start"]], key_label[r["end"]])].append(
            {"start": r["start"], "end": r["end"], "props": {k: decode(v) for k, v in r["props"].items()}})
    created = Counter()

    def work(tx):
        for labels, rows in by_labels.items():
            s = tx.run("UNWIND $rows AS row CREATE (n:%s) SET n = row.props, n.id = row.id"
                       % ":".join("`%s`" % l for l in labels), rows=rows).consume()
            created["nodes"] += s.counters.nodes_created
        for (t, a, b), rows in by_type.items():
            s = tx.run("UNWIND $rows AS row MATCH (a:`%s` {id: row.start}) MATCH (b:`%s` {id: row.end}) "
                       "CREATE (a)-[r:`%s`]->(b) SET r = row.props" % (a, b, t), rows=rows).consume()
            created["relationships"] += s.counters.relationships_created
        if created["nodes"] != len(nodes) or created["relationships"] != len(rels):
            raise ExportError("created %d nodes and %d relationships, the files have %d and %d" % (
                created["nodes"], created["relationships"], len(nodes), len(rels)))

    with driver.session(database=database) as session:
        session.execute_write(work)
    return {"database": database, "home": home, "created": dict(created), "manifest_snapshot": manifest["snapshot"],
            "snapshot": snapshot(driver, database)}
