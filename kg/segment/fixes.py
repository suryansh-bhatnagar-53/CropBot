"""Approved registry fixes, checked and applied to the item stream before the tree is built.

Every approved fix must find its text exactly once on its pdf_page, or segmentation
stops with FixError listing every problem; nothing is guessed.
  heading_fix  split    checked here, applied by the Builder (heading text + page)
  heading_fix  restore  a heading or body item becomes the heading as printed
  reading_order_fix     items first..last move to just after `after`
"""


class FixError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def _hits(items: list[dict], text: str, page: int, kinds: tuple[str, ...]) -> list[int]:
    return [i for i, it in enumerate(items)
            if it["pdf_page"] == page and it["kind"] in kinds and it.get("text") == text]


def apply_fixes(items: list[dict], entry, log: dict) -> list[dict]:
    heading_fixes = [f for f in entry.heading_fix if f.status == "approved"]
    order_fixes = [f for f in entry.reading_order_fix if f.status == "approved"]
    problems = []

    def expect_once(text, page, kinds, what):
        hits = _hits(items, text, page, kinds)
        if len(hits) != 1:
            problems.append("%s: %r found %d times on PDF p. %d (expected exactly once)"
                            % (what, text, len(hits), page))
        return hits

    for f in heading_fixes:
        kinds = ("heading",) if f.kind == "split" else ("heading", "text")
        expect_once(f.match, f.pdf_page, kinds, "heading_fix %s" % f.kind)
    for f in order_fixes:
        hits = [expect_once(t, f.pdf_page, ("heading", "text"), "reading_order_fix %s" % name)
                for name, t in (("first", f.first), ("last", f.last), ("after", f.after))]
        if all(len(h) == 1 for h in hits):
            first, last, after = (h[0] for h in hits)
            if first > last:
                problems.append("reading_order_fix: %r comes after %r on PDF p. %d"
                                % (f.first, f.last, f.pdf_page))
            elif first <= after <= last:
                problems.append("reading_order_fix: %r lies inside the block it should follow"
                                % f.after)
    if problems:
        raise FixError(problems)

    items = list(items)
    for f in (f for f in heading_fixes if f.kind == "restore"):
        [i] = _hits(items, f.match, f.pdf_page, ("heading", "text"))
        items[i] = {**items[i], "kind": "heading", "text": f.heading,
                    "chars": len(f.heading), "restored_from": items[i]["label"]}
        log["heading_fixes_applied"].append({"kind": "restore", "match": f.match,
                                             "heading": f.heading, "pdf_page": f.pdf_page})
    for f in order_fixes:
        [first] = _hits(items, f.first, f.pdf_page, ("heading", "text"))
        [last] = _hits(items, f.last, f.pdf_page, ("heading", "text"))
        block = items[first:last + 1]
        rest = items[:first] + items[last + 1:]
        [after] = _hits(rest, f.after, f.pdf_page, ("heading", "text"))
        items = rest[:after + 1] + block + rest[after + 1:]
        log["reading_order_fixes_applied"].append({"pdf_page": f.pdf_page, "moved": len(block),
                                                   "first": f.first, "last": f.last, "after": f.after})
    return items
