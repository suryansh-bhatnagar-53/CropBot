"""Source registry: read, validate and check registry/*.toml against the files.

  uv run python -m kg.registry      validate every entry and check each file's sha256
"""

import hashlib
import tomllib
from pathlib import Path

from pydantic import ValidationError

from kg.load.seed import CONCEPTS_DIR, read_seed
from kg.schema.concepts import AgroClimaticZone, District

from .model import RegistryEntry, Section

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = ROOT / "registry"


class RegistryError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_registry(directory: Path = REGISTRY_DIR, root: Path = ROOT,
                  concepts: Path | None = None) -> list[RegistryEntry]:
    """Validate every entry; raise RegistryError listing all problems."""
    problems, entries = [], []
    for path in sorted(directory.glob("*.toml")):
        try:
            entry = RegistryEntry.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
        except tomllib.TOMLDecodeError as e:
            problems.append("%s: not valid TOML: %s" % (path.name, e))
            continue
        except ValidationError as e:
            problems += ["%s: %s: %s" % (path.name, ".".join(map(str, err["loc"])) or "entry",
                                         err["msg"]) for err in e.errors()]
            continue
        if path.stem != entry.id.split(":", 1)[1]:
            problems.append("%s: file name must match the id (%s.toml)"
                            % (path.name, entry.id.split(":", 1)[1]))
        entries.append((path.name, entry))

    nodes = {n.id: n for n in read_seed(concepts or CONCEPTS_DIR).nodes}
    ids = [e.id for _, e in entries]
    for name, e in entries:
        if ids.count(e.id) > 1:
            problems.append("%s: duplicate id %s" % (name, e.id))
        if e.supersedes and e.supersedes not in ids:
            problems.append("%s: supersedes %s, which is not registered" % (name, e.supersedes))
        regions = [("state_id", e.state_id)] if e.state_id else []
        regions += [("region_scope", r) for r in e.region_scope]
        regions += [("section_scope %r" % s.heading, r) for s in e.section_scope for r in s.regions]
        for where, rid in regions:
            node = nodes.get(rid)
            if node is None:
                problems.append("%s: %s %s is not a loaded region" % (name, where, rid))
            elif e.state_id and not _within_state(rid, node, e.state_id):
                problems.append("%s: %s %s is outside the book's state %s"
                                % (name, where, rid, e.state_id))
        problems += ["%s: %s" % (name, p) for p in _check_file(e, root)]

    if problems:
        raise RegistryError(problems)
    return [e for _, e in entries]


def review_csv(name: str, entry) -> Path:
    """data/review/<name>_<source slug>.csv: one review file per source, so a run for one book never overwrites
    another's rows (2026-10-23)."""
    return ROOT / "data" / "review" / ("%s_%s.csv" % (name, entry.id.split(":", 1)[1]))


def read_entry(source_id: str, directory: Path = REGISTRY_DIR, root: Path = ROOT) -> RegistryEntry:
    """The entry with this id. Every entry is validated, as in read_registry; entries are sorted by file
    name, so never pick one by position."""
    for e in read_registry(directory, root):
        if e.id == source_id:
            return e
    raise RegistryError(["%s is not registered" % source_id])


def _within_state(rid: str, node, state_id: str) -> bool:
    if rid == state_id:
        return True
    if isinstance(node, (AgroClimaticZone, District)):
        return node.state_id == state_id
    return False


def _check_file(entry: RegistryEntry, root: Path) -> list[str]:
    path = root / entry.file
    if not path.is_file():
        return ["file %s is missing; download it from %s" % (entry.file, entry.url)]
    actual = sha256_file(path)
    if actual != entry.sha256:
        return ["sha256 mismatch for %s: registry %s, file %s" % (entry.file, entry.sha256, actual)]
    return []


def heading_matches(section: Section, items: list[dict]) -> int:
    """How many headings in a converted index match a section's text within its page range.

    A stand-in until segmentation exists; then a section must match exactly one unit.
    """
    lo, hi = section.pdf_pages
    return sum(1 for it in items if it.get("k") == "h" and it.get("t") == section.heading
               and lo <= (it.get("pg") or 0) <= hi)
