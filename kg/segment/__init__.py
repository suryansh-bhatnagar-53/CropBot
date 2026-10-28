"""Segment a converted book into extraction units, one per leaf section. No LLM.

  uv run python -m kg.segment source:tnau_agriculture_2020

Input: data/docling/<source_id>/document.json (running headers filtered).
Output: data/units/<source_id>/units.jsonl and report.json (gitignored).
The section-scope check fails loudly: outputs are written, the report says
FAILED, and the command exits non-zero.
"""

import hashlib
import re
from collections import defaultdict

from kg.convert.headers import doc_items, norm, running_headings
from kg.registry import ROOT

from .fixes import FixError, apply_fixes
from .tree import Builder, Node

UNITS_DIR = ROOT / "data" / "units"
TOKEN_LIMIT = 20_000          # flag units above this many approx tokens (64k request limit)


def approx_tokens(chars: int) -> int:
    return chars // 4


def _chapter_key(title: str) -> str:
    return norm(re.sub(r"\(.*?\)", "", title)).strip()


def _items(doc, entry, running: set[str], log: dict):
    """Body items in reading order as dicts; running headers dropped."""
    for item, _ in doc.iterate_items():
        label = str(getattr(getattr(item, "label", None), "value", ""))
        prov = getattr(item, "prov", None) or []
        page = prov[0].page_no if prov else None
        base = {"ref": item.self_ref, "label": label, "pdf_page": page,
                "printed_page": entry.printed_page(page) if page else None}
        if label == "table":
            yield {**base, "kind": "table", "text": None,
                   "chars": len(item.export_to_markdown(doc=doc))}
        elif label == "picture":
            yield {**base, "kind": "picture", "text": None, "chars": 0}
        else:
            text = getattr(item, "text", "") or ""
            if label in ("section_header", "title"):
                if norm(text) in running:
                    log["running_headers_dropped"].append({"text": text, "pdf_page": page})
                    continue
                yield {**base, "kind": "heading", "text": text, "chars": len(text)}
            elif text.strip():
                yield {**base, "kind": "text", "text": text, "chars": len(text)}


def replace_pages(items: list[dict], transcriptions: dict, entry, log: dict) -> list[dict]:
    """An approved transcription's items replace every converter item of its page, at the place the page's
    first item had (or before the first later page when the converter found nothing there)."""
    from kg.transcribe import items as transcribed_items
    out, done = [], set()
    for page in sorted(transcriptions):
        dropped = [i for i in items if i["pdf_page"] == page]
        log["transcribed_pages"].append({"pdf_page": page, "file": transcriptions[page].rel(),
                                         "checked_by": transcriptions[page].header.checked_by,
                                         "converter_items_dropped": len(dropped)})
    for it in items:
        page = it["pdf_page"] or 0
        for p in sorted(transcriptions):
            if p not in done and p <= page:
                out += transcribed_items(transcriptions[p], entry)
                done.add(p)
        if page not in transcriptions:
            out.append(it)
    for p in sorted(set(transcriptions) - done):
        out += transcribed_items(transcriptions[p], entry)
    return out


def build_tree(doc, entry, transcriptions: dict | None = None) -> tuple[list[tuple], dict]:
    """[(chapter model, chapter Node)], log. `transcriptions`: approved ones by PDF page (kg.transcribe)."""
    log = defaultdict(list)
    running = running_headings(doc_items(doc))
    chapters = sorted(entry.chapters, key=lambda c: c.pdf_page)
    fixes = [f for f in entry.heading_fix if f.status == "approved"]
    built, builder, idx = [], None, -1
    seen_heading = False
    items = apply_fixes(list(_items(doc, entry, running, log)), entry, log)
    if transcriptions:
        items = replace_pages(items, transcriptions, entry, log)
    for it in items:
        page = it["pdf_page"] or 0
        while idx + 1 < len(chapters) and page >= chapters[idx + 1].pdf_page:
            idx += 1
            ch = chapters[idx]
            node = Node("chapter", ch.path_label(), pdf_page=ch.pdf_page)
            builder = Builder(node, fixes, log)
            built.append((ch, node))
            seen_heading = False
        if builder is None:
            log["front_matter_items"].append(it["ref"])
            continue
        ch, node = built[-1]
        key = _chapter_key(ch.title)
        if (not seen_heading and it["kind"] == "heading" and page == ch.pdf_page
                and key and key in norm(it["text"])):
            node.heading_ref, seen_heading = it["ref"], True
            node.subtitles.append(it["text"])
            if node.items:
                log["before_chapter_heading"].append({
                    "chapter": ch.path_label(), "pdf_page": page,
                    "refs": [i["ref"] for i in node.items if i["kind"] != "subheading"]})
            builder.last_was_heading = True
            continue
        if it["kind"] == "heading" and it.get("inline"):      # a transcription's '### ' sub-heading
            builder.inline(it["text"], it["ref"], page, label="transcription")
            builder.current.items[-1]["transcription"] = it["transcription"]
            builder.last_was_heading = True
        elif it["kind"] == "heading":
            builder.heading(it["text"], it["ref"], page)
        else:
            builder.body(it)
    for ch, node in built:
        if node.heading_ref is None:
            log["chapter_heading_not_found"].append({"chapter": ch.path_label(), "pdf_page": ch.pdf_page})
    return built, log


def _path(node: Node) -> list[str]:
    parts = []
    while node is not None:
        parts.append(node.title() if node.kind != "chapter" else node.heading)
        node = node.parent
    return parts[::-1]


def _unit(entry, ch, node: Node, kind: str, seen: dict) -> dict:
    path = " > ".join(_path(node))
    digest = hashlib.sha1(("%s|%s" % (path, kind)).encode()).hexdigest()[:12]
    uid = "unit:%s:%s" % (entry.id.split(":", 1)[1], digest)
    seen[uid] = seen.get(uid, 0) + 1
    if seen[uid] > 1:
        uid += "-%d" % seen[uid]
    items = node.items
    pages = [i["pdf_page"] for i in items if i["pdf_page"]] or ([node.pdf_page] if node.pdf_page else [])
    text_chars = sum(i.get("chars", 0) for i in items)
    return {
        "id": uid, "source_id": entry.id, "kind": kind,
        "chapter": {"number": ch.number, "title": ch.path_label(), "status": ch.status},
        "section_path": path, "heading_ref": node.heading_ref,
        "items": [{k: i[k] for k in ("ref", "label", "kind", "text", "pdf_page", "printed_page",
                                     "subheading", "transcription") if k in i} for i in items],
        "table_refs": [i["ref"] for i in items if i["kind"] == "table"],
        "picture_refs": [i["ref"] for i in items if i["kind"] == "picture"],
        "pdf_pages": [min(pages), max(pages)] if pages else None,
        "approx_tokens": approx_tokens(text_chars),
        "text_items": sum(1 for i in items if i["kind"] == "text"),
        "_node": node,
    }


def make_units(entry, built) -> list[dict]:
    units, seen = [], {}
    for ch, root in built:
        for node in root.walk():
            if not node.children:
                units.append(_unit(entry, ch, node, "leaf", seen))
            elif any(i["kind"] != "subheading" for i in node.items):
                units.append(_unit(entry, ch, node, "intro", seen))
    return units


def _subtree_pages(node: Node) -> list[int]:
    pages = []
    for n in node.walk():
        pages += [i["pdf_page"] for i in n.items if i["pdf_page"]]
        if n.pdf_page:
            pages.append(n.pdf_page)
    return [min(pages), max(pages)] if pages else []


def check_scopes(entry, built, units) -> list[dict]:
    """Each section scope and default-scope section must match exactly one section node. A chapter's own
    heading counts too (schema v1.5: "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY" scopes its grades)."""
    nodes = [n for _, root in built for n in root.walk()]
    checks = []
    targets = [("default_scope", r.rule, r.status, r.section, r) for r in entry.default_scope if r.section]
    targets += [("section_scope", s.heading, s.status, s, s) for s in entry.section_scope]
    for kind, name, status, sec, obj in targets:
        lo, hi = sec.pdf_pages
        hits = [n for n in nodes if n.heading == sec.heading and n.pdf_page and lo <= n.pdf_page <= hi]
        checks.append({"kind": kind, "name": name, "heading": sec.heading, "pdf_pages": [lo, hi],
                       "status": status, "matches": len(hits), "ok": len(hits) == 1,
                       "section_pdf_pages": _subtree_pages(hits[0]) if len(hits) == 1 else None,
                       "_node": hits[0] if len(hits) == 1 else None, "_obj": obj})
    return checks


def resolve_scopes(entry, units, checks) -> None:
    """Regions, purposes and default-scope rules per unit; only approved rules count. A section
    scope with no regions (purposes only) leaves the regions as they are."""
    by_node = {}
    for c in checks:
        if c["ok"] and c["status"] == "approved":
            by_node.setdefault(id(c["_node"]), []).append(c)
    for u in units:
        regions = [{"id": r, "origin": "source"} for r in entry.region_scope]
        purposes, grades = [], []
        rules = [r.label() for r in entry.default_scope if r.status == "approved" and r.section is None]
        chain, n = [], u["_node"]
        while n is not None:
            chain.append(n)
            n = n.parent
        for n in reversed(chain):                       # outermost first; deepest section scope wins
            for c in by_node.get(id(n), []):
                if c["kind"] == "section_scope":
                    if c["_obj"].regions:
                        regions = [{"id": r, "origin": "section"} for r in c["_obj"].regions]
                    if c["_obj"].purposes:
                        purposes = [{"id": p, "origin": "section"} for p in c["_obj"].purposes]
                    if c["_obj"].grades:           # schema v1.5: the heading is the evidence
                        grades = [{"id": g.value, "origin": "section", "evidence": c["heading"]}
                                  for g in c["_obj"].grades]
                else:
                    rules.append(c["_obj"].label())
        u["regions"], u["purposes"], u["default_scope"] = regions, purposes, rules
        if grades:
            u["grades"] = grades


def numbering_gaps(built) -> list[dict]:
    gaps = []
    for ch, root in built:
        for node in root.walk():
            nums = sorted(c.number.parts[-1] for c in node.children
                          if c.number and c.number.scheme == "arabic")
            missing = [n for n in range(1, nums[-1]) if n not in nums] if nums else []
            if missing:
                prefix = ".".join(map(str, node.number.parts)) + "." if (
                    node.number and node.number.scheme == "arabic") else ""
                gaps.append({"chapter": ch.path_label(), "under": node.title(),
                             "missing": ["%s%d" % (prefix, n) for n in missing]})
    return gaps


def split_gaps(entry, gaps) -> tuple[list[dict], list[dict], list[dict]]:
    """(open, acknowledged, stale). A gap is acknowledged only by an entry with the same chapter,
    section and missing numbers; an entry that matches no gap is stale and reported."""
    acks = {(a.chapter, a.under, tuple(a.missing)): a for a in entry.acknowledged_gap}
    open_, acknowledged, used = [], [], set()
    for g in gaps:
        key = (g["chapter"], g["under"], tuple(g["missing"]))
        if key in acks:
            used.add(key)
            acknowledged.append({**g, "pdf_page": acks[key].pdf_page, "note": acks[key].note})
        else:
            open_.append(g)
    stale = [a.model_dump() for k, a in acks.items() if k not in used]
    return open_, acknowledged, stale


LOST_HEADING = re.compile(r"^(Insect|Disease|Nematode|Weed|Pest) management\s*:?\s*See\b", re.I)


def heading_like_list_items(units) -> list[dict]:
    out = []
    for u in units:
        for i in u["items"]:
            t = (i.get("text") or "").strip()
            if i["label"] != "list_item" or not t:
                continue
            # a bare label like "Harvesting" between bullets, or "Insect management: See ..."
            short = (len(t.split()) <= 2 and t[0].isupper() and not t.endswith(".")
                     and not re.search(r"\d", t))
            if short or LOST_HEADING.match(t):
                out.append({"text": t, "pdf_page": i["pdf_page"], "ref": i["ref"],
                            "unit": u["section_path"]})
    return out
