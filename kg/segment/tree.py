"""Rebuild the section tree of one book from heading numbers (Docling heading levels are flat).

Rules (approved for step 7):
- Chapters come from the registry's chapter list; a chapter starts on its PDF page.
  The chapter's own heading on that page ("1. RICE (Oryza sativa L.)") is its title,
  never a section number.
- Numbered headings nest by number: 1.8.3.1 under 1.8.3. Schemes (1., I., A), ii), a))
  nest in the order they first appear in their context ("II. NURSERY PRACTICES" >
  "1. NURSERY PREPARATION").
- A child before its parent creates a placeholder; the late parent fills it.
- Body text that starts with a multi-level number whose parent exists is promoted.
- Unnumbered headings are inline sub-headings of the section above, except ALL-CAPS
  ones: a caps heading straight after another heading that shares a word with it is
  its subtitle ("TRANSPLANTED RICE" after "1. TRANSPLANTED PUDDLED LOWLAND RICE");
  otherwise it starts a major section at chapter level. Numbering continues across a major section
  ("3." goes next to "2." even with "RAINFED RICE" in between).
- Only approved heading fixes from the registry are applied.
Every decision that is not a plain parse is recorded in `log` for the report.
"""

import re
from dataclasses import dataclass, field

from .numbering import Number, is_caps, parse, promotable

CLASS = {s: s for s in ("arabic", "roman", "letter", "roman_lower", "letter_lower")}
STOPWORDS = {"of", "and", "the", "in", "for", "to", "a", "an", "with", "on"}


def _shares_word(a: str, b: str) -> bool:
    words = lambda s: {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOPWORDS and len(w) > 2}
    return bool(words(a) & words(b))
# starts like a number but did not parse: "(V) SMALL MILLETS", "7 SUGARCANE", "1 .2 Area"
LOOKS_NUMBERED = re.compile(r"^\s*[(\[]?\s*(\d{1,2}|[IVXivx]{1,5}|[A-Ha-h])\s*[.)\]]|^\s*\d{1,2}\s+[A-Z]")


@dataclass
class Node:
    kind: str                       # chapter | major | numbered | placeholder | subsection
    heading: str                    # heading text as written (after approved fixes)
    number: Number | None = None
    parent: "Node | None" = None
    level: int = -1                 # depth inside its context; contexts are -1
    heading_ref: str | None = None
    pdf_page: int | None = None
    subtitles: list[str] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    # context state (chapter and major nodes only)
    stack: list["Node"] = field(default_factory=list)
    class_level: dict = field(default_factory=dict)
    by_number: dict = field(default_factory=dict)
    subheading: str | None = None   # current inline sub-heading for new items

    def add(self, child: "Node") -> "Node":
        child.parent = self
        self.children.append(child)
        return child

    def title(self) -> str:
        return self.heading + "".join(" / " + s for s in self.subtitles)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class Builder:
    def __init__(self, chapter: Node, fixes: list, log: dict):
        self.chapter = chapter
        self.fixes = fixes            # approved HeadingFix models
        self.log = log
        self.contexts = [chapter]     # chapter, then major sections in order
        self.ctx = chapter
        self.current: Node = chapter  # where body items go
        self.last_was_heading = False

    # --- placement ------------------------------------------------------------------

    def _place(self, node: Node, ctx: Node, parent: Node | None, level: int) -> Node:
        (parent or ctx).add(node)
        node.level = level
        ctx.stack = ctx.stack[:level] + [node]
        if node.number:
            ctx.by_number[(CLASS[node.number.scheme], node.number.parts)] = node
        return node

    def _class_slot(self, ctx: Node, cls: str) -> tuple[Node | None, int]:
        if cls in ctx.class_level:
            level = min(ctx.class_level[cls], len(ctx.stack))
        else:
            level = len(ctx.stack)
            if ctx.stack and ctx.stack[-1].kind == "subsection":
                level -= 1          # a heading-fix sub-section ("Nursery") is a sibling, not a parent
            ctx.class_level[cls] = level
        return (ctx.stack[level - 1] if level > 0 else None), level

    def _continuing_context(self, number: Number) -> Node:
        """Numbering continues across a major section: find the context holding n-1."""
        n = number.parts[0]
        if self.ctx.by_number or n <= 1:
            return self.ctx
        for ctx in reversed(self.contexts[:-1]):
            if ("arabic", (n - 1,)) in ctx.by_number:
                self.log["caps_decisions"].append({
                    "heading": self.ctx.heading, "pdf_page": self.ctx.pdf_page,
                    "decision": "numbering continues across it",
                    "detail": "%s placed next to %d. in %r" % (number.label(), n - 1, ctx.heading)})
                return ctx
        return self.ctx

    def _ensure(self, ctx: Node, parts: tuple[int, ...], page: int | None) -> Node:
        """The arabic node with these parts, creating placeholders for missing ancestors."""
        key = ("arabic", parts)
        if key in ctx.by_number:
            return ctx.by_number[key]
        number = Number("arabic", parts, ".".join(map(str, parts)))
        node = Node("placeholder", "%s (heading not found)" % number.label(), number, pdf_page=page)
        if len(parts) > 1:
            parent = self._ensure(ctx, parts[:-1], page)
            self._place(node, ctx, parent, parent.level + 1)
        else:
            parent, level = self._class_slot(ctx, "arabic")
            self._place(node, ctx, parent, level)
        self.log["placeholders"].append({"number": number.label(), "pdf_page": page,
                                         "chapter": self.chapter.heading})
        return node

    def numbered(self, number: Number, text: str, ref: str, page: int, promoted=False) -> Node:
        ctx = self._continuing_context(number) if number.scheme == "arabic" else self.ctx
        if ctx is not self.ctx:
            self.ctx = ctx
        key = (CLASS[number.scheme], number.parts)
        existing = ctx.by_number.get(key)
        if existing and existing.kind == "placeholder":
            existing.kind, existing.heading, existing.heading_ref = "numbered", text, ref
            self.log["late_parents"].append({"number": number.label(), "heading": text, "pdf_page": page})
            node = existing
            ctx.stack = ctx.stack[:node.level] + [node]
        else:
            if existing:
                self.log["duplicate_numbers"].append({"number": number.label(), "heading": text,
                                                      "pdf_page": page, "earlier": existing.heading})
            node = Node("numbered", text, number, heading_ref=ref, pdf_page=page)
            if number.parent_parts():
                parent = self._ensure(ctx, number.parent_parts(), page)
                self._place(node, ctx, parent, parent.level + 1)
            else:
                parent, level = self._class_slot(ctx, CLASS[number.scheme])
                self._place(node, ctx, parent, level)
        if promoted:
            self.log["promotions"].append({"number": number.label(), "text": text, "pdf_page": page,
                                           "ref": ref})
        self.current = node
        return node

    # --- events -------------------------------------------------------------------------

    def heading(self, text: str, ref: str, page: int):
        fix = next((f for f in self.fixes if f.kind == "split" and f.match == text
                    and f.pdf_page == page), None)
        if fix:
            self.log["heading_fixes_applied"].append({"kind": "split", "match": fix.match, "pdf_page": page})
            text = fix.heading
        number, _ = parse(text)
        if not number and LOOKS_NUMBERED.match(text):
            self.log["unparsed_headings"].append({"heading": text, "pdf_page": page, "ref": ref})
        if number:
            node = self.numbered(number, text, ref, page)
        elif (is_caps(text) and self.last_was_heading and self.current is not self.chapter
              and _shares_word(text, self.current.heading)):
            self.current.subtitles.append(text)
            self.log["caps_decisions"].append({"heading": text, "pdf_page": page, "decision": "subtitle",
                                               "detail": "of %r" % self.current.heading})
            node = self.current
        elif is_caps(text):
            node = self.chapter.add(Node("major", text, heading_ref=ref, pdf_page=page))
            self.contexts.append(node)
            self.ctx = self.current = node
            self.log["caps_decisions"].append({"heading": text, "pdf_page": page, "decision": "major section",
                                               "detail": "in chapter %r" % self.chapter.heading})
        else:
            self.inline(text, ref, page, label="section_header")
            node = self.current
        if fix and fix.inline_subheading:
            self.inline(fix.inline_subheading, ref, page, label="heading_fix")
        if fix and fix.subsection:
            if parse(fix.subsection)[0]:      # numbered ("I. SEASON AND VARIETIES"): normal placement
                self.last_was_heading = True
                self.heading(fix.subsection, ref, page)
                return
            sub = Node("subsection", fix.subsection, heading_ref=ref, pdf_page=page)
            self._place(sub, self.ctx, node, node.level + 1)
            self.current = sub
        self.last_was_heading = True

    def inline(self, text: str, ref: str, page: int, label: str):
        self.current.subheading = text
        self.current.items.append({"ref": ref, "label": label, "kind": "subheading", "text": text,
                                   "pdf_page": page, "subheading": text})

    def body(self, item: dict):
        if item["kind"] == "text" and promotable(item["text"]):
            number, _ = parse(item["text"])
            ctx = self.ctx
            if number and number.parent_parts() and ("arabic", number.parent_parts()) in ctx.by_number:
                self.numbered(number, item["text"], item["ref"], item["pdf_page"], promoted=True)
                self.last_was_heading = True
                return
        item["subheading"] = self.current.subheading
        self.current.items.append(item)
        self.last_was_heading = False
