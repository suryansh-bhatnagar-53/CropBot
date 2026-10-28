"""Verified transcriptions of scanned pages (decided 2026-10-22, pending schema v1.5).

  uv run python -m kg.transcribe check source:<id>     every transcription of the source, and which are used
  uv run python -m kg.transcribe rehash <file>         store the body hash; resets status to proposed

A transcription is a hand-checked copy of one PDF page, transcriptions/<source slug>/p<NNN>.md: a TOML header
between '+++' lines, then the page as printed. Only an approved transcription (status = "approved", checked_by
and checked_at filled, body_sha256 equal to the body) replaces the converter's text for its page in
segmentation; a proposed one changes nothing. An approval belongs to one body: editing the body breaks the hash,
and the page is refused until the body is rehashed (which sets it back to proposed) and approved again.

Body format: '# ' is a heading, '### ' an inline sub-heading, a block of lines starting with '|' is one table
(header line, rule line, rows), and every other block is one text item; blank lines separate blocks and the
lines of a text block are joined with a space. Items get refs tr:p<NNN>#/texts/<n> and tr:p<NNN>#/tables/<n>.
"""

import datetime as dt
import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import PositiveInt, ValidationError

from kg.registry import ROOT
from kg.schema.core import Model, Text

TRANSCRIPTIONS_DIR = ROOT / "transcriptions"
FRONT = "+++"
REF = re.compile(r"^tr:p(\d{3,4})#/(texts|tables)/(\d+)$")


class TranscriptionError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


class Header(Model):
    source_id: Text
    pdf_page: PositiveInt
    pdf_sha256: str
    rendered_dpi: PositiveInt
    transcribed_by: Text
    transcribed_at: Text
    status: Literal["proposed", "approved", "rejected"]
    checked_by: str = ""
    checked_at: str = ""
    body_sha256: str = ""
    notes: list[str] = []


@dataclass
class Transcription:
    path: Path
    header: Header
    body: str
    blocks: list[dict] = field(default_factory=list)

    @property
    def page(self) -> int:
        return self.header.pdf_page

    @property
    def tag(self) -> str:
        return "p%03d" % self.page

    def rel(self) -> str:
        return self.path.relative_to(ROOT).as_posix() if self.path.is_relative_to(ROOT) else str(self.path)


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def split(text: str) -> tuple[str, str]:
    """(header TOML, body) of a transcription file."""
    text = text.replace("\r\n", "\n")
    if not text.startswith(FRONT + "\n"):
        raise TranscriptionError(["the file must start with a '+++' header"])
    end = text.find("\n" + FRONT + "\n", len(FRONT))
    if end < 0:
        raise TranscriptionError(["the '+++' header is not closed"])
    return text[len(FRONT) + 1:end + 1], text[end + len(FRONT) + 2:]


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if not (inner.startswith("|") and inner.endswith("|")):
        raise TranscriptionError(["table line must start and end with '|': %r" % line])
    return [c.strip() for c in inner[1:-1].split("|")]


def parse_body(body: str) -> list[dict]:
    """Blocks in order: {"kind": heading | subheading | text, "text"} or {"kind": "table", "header", "rows"}."""
    blocks, problems = [], []
    for raw in re.split(r"\n\s*\n", body.strip("\n")):
        lines = [x for x in raw.split("\n") if x.strip()]
        if not lines:
            continue
        if all(x.lstrip().startswith("|") for x in lines):
            if len(lines) < 2 or not re.fullmatch(r"\|(\s*:?-{3,}:?\s*\|)+", lines[1].strip()):
                problems.append("table without a '|---|' rule as its second line: %r" % lines[0])
                continue
            header, rows = _cells(lines[0]), [_cells(x) for x in lines[2:]]
            bad = [i for i, r in enumerate(rows) if len(r) != len(header)]
            if bad:
                problems.append("table %r: rows %s do not have %d cells" % (lines[0], bad, len(header)))
                continue
            blocks.append({"kind": "table", "header": header, "rows": rows})
        elif lines[0].startswith("### "):
            if len(lines) > 1:
                problems.append("a sub-heading is one line: %r" % lines[0])
            blocks.append({"kind": "subheading", "text": lines[0][4:].strip()})
        elif lines[0].startswith("# "):
            if len(lines) > 1:
                problems.append("a heading is one line: %r" % lines[0])
            blocks.append({"kind": "heading", "text": lines[0][2:].strip()})
        elif any(x.lstrip().startswith("|") for x in lines):
            problems.append("a block mixes table lines and text: %r" % lines[0])
        else:
            blocks.append({"kind": "text", "text": " ".join(x.strip() for x in lines)})
    if problems:
        raise TranscriptionError(problems)
    return blocks


def read(path: Path) -> Transcription:
    try:
        head, body = split(path.read_text(encoding="utf-8"))
        header = Header.model_validate(tomllib.loads(head))
    except tomllib.TOMLDecodeError as e:
        raise TranscriptionError(["%s: header is not valid TOML: %s" % (path.name, e)])
    except ValidationError as e:
        raise TranscriptionError(["%s: %s: %s" % (path.name, ".".join(map(str, err["loc"])), err["msg"])
                                  for err in e.errors()])
    except TranscriptionError as e:
        raise TranscriptionError(["%s: %s" % (path.name, p) for p in e.problems])
    try:
        blocks = parse_body(body)
    except TranscriptionError as e:
        raise TranscriptionError(["%s: %s" % (path.name, p) for p in e.problems])
    return Transcription(path, header, body, blocks)


def problems(t: Transcription, entry, today: dt.date | None = None) -> list[str]:
    """What stops this transcription from being used. A proposed or rejected one is only reported."""
    h, out = t.header, []
    if h.source_id != entry.id:
        out.append("source_id %s is not %s" % (h.source_id, entry.id))
    if h.pdf_sha256 != entry.sha256:
        out.append("pdf_sha256 does not match the registered file (%s)" % entry.sha256[:12])
    if t.path.name != "p%03d.md" % h.pdf_page:
        out.append("file name must be p%03d.md for pdf_page %d" % (h.pdf_page, h.pdf_page))
    if h.status == "approved":
        if body_sha256(t.body) != h.body_sha256:
            out.append("the body changed after body_sha256 was stored: rehash it and approve it again")
        if not h.checked_by.strip():
            out.append("approved without checked_by")
        try:
            day = dt.date.fromisoformat(h.checked_at)
            if day > (today or dt.date.today()):
                out.append("checked_at %s is in the future" % h.checked_at)
        except ValueError:
            out.append("approved without a valid checked_at (yyyy-mm-dd): %r" % h.checked_at)
    return out


def source_dir(entry) -> Path:
    return TRANSCRIPTIONS_DIR / entry.id.split(":", 1)[1]


def for_source(entry, directory: Path | None = None, today: dt.date | None = None) -> dict:
    """{"approved": {page: Transcription}, "other": [(Transcription, status, problems)]}. Raises
    TranscriptionError, using nothing, when a file can't be read or an approved one fails its checks."""
    d = directory or source_dir(entry)
    approved, other, errors = {}, [], []
    for path in sorted(d.glob("p*.md")) if d.exists() else []:
        try:
            t = read(path)
        except TranscriptionError as e:
            errors += e.problems
            continue
        p = problems(t, entry, today)
        if t.header.status == "approved":
            if p:
                errors += ["%s: %s" % (path.name, x) for x in p]
            elif t.page in approved:
                errors.append("%s: page %d has two approved transcriptions" % (path.name, t.page))
            else:
                approved[t.page] = t
        else:
            other.append((t, t.header.status, p))
    if errors:
        raise TranscriptionError(errors)
    return {"approved": approved, "other": other}


def ref(t: Transcription, kind: str, n: int) -> str:
    return "tr:%s#/%s/%d" % (t.tag, kind, n)


def table_markdown(block: dict) -> str:
    lines = ["| %s |" % " | ".join(block["header"]), "|%s" % "---|" * len(block["header"])]
    return "\n".join(lines + ["| %s |" % " | ".join(r) for r in block["rows"]])


def items(t: Transcription, entry) -> list[dict]:
    """Segmentation items for the page, in printed order (kg.segment replaces the converter's items)."""
    out, n_text, n_table = [], 0, 0
    base = {"pdf_page": t.page, "printed_page": entry.printed_page(t.page), "transcription": t.rel()}
    for b in t.blocks:
        if b["kind"] == "table":
            out.append({**base, "ref": ref(t, "tables", n_table), "label": "table", "kind": "table", "text": None,
                        "chars": len(table_markdown(b))})
            n_table += 1
            continue
        item = {**base, "ref": ref(t, "texts", n_text), "text": b["text"], "chars": len(b["text"])}
        n_text += 1
        if b["kind"] == "text":
            out.append({**item, "label": "text", "kind": "text"})
        else:
            out.append({**item, "label": "section_header", "kind": "heading", "inline": b["kind"] == "subheading"})
    return out


def parts(t: Transcription) -> dict:
    """kg.tables Parts for the page's tables: the header line is the header row; no bbox, no page check."""
    from kg.tables.stitch import Part, ws
    out = {}
    tables = [b for b in t.blocks if b["kind"] == "table"]
    for n, b in enumerate(tables):
        grid = [(b["header"], True)] + [(r, False) for r in b["rows"]]
        cells = [{"row": i, "col": j, "row_span": 1, "col_span": 1, "text": ws(text), "header": head, "bbox": None}
                 for i, (row, head) in enumerate(grid) for j, text in enumerate(row)]
        rows = [[c for c in cells if c["row"] == i] for i in range(len(grid))]
        r = ref(t, "tables", n)
        out[r] = Part(r, t.page, len(grid), len(b["header"]), cells, rows, None)
    return out


def rehash(path: Path) -> Header:
    """Store the body's hash; status back to proposed and the check fields cleared (a new body needs a new
    check). The header is rewritten field by field; the body is not touched."""
    head, body = split(path.read_text(encoding="utf-8"))
    tomllib.loads(head)
    new = body_sha256(body)
    lines = []
    for line in head.split("\n"):
        key = line.split("=", 1)[0].strip() if "=" in line and not line.startswith(" ") else None
        if key == "body_sha256":
            line = 'body_sha256 = "%s"' % new
        elif key == "status":
            line = 'status = "proposed"'
        elif key in ("checked_by", "checked_at"):
            line = '%s = ""' % key
        lines.append(line)
    text = FRONT + "\n" + "\n".join(lines) + FRONT + "\n" + body
    path.write_text(text, encoding="utf-8", newline="\n")
    return read(path).header
