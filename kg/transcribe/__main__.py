import argparse
import sys
from pathlib import Path

from kg.registry import read_entry

from . import TranscriptionError, body_sha256, for_source, read, rehash, source_dir


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m kg.transcribe", description="Verified page transcriptions")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="list a source's transcriptions and which replace the converter's text")
    c.add_argument("source_id")
    r = sub.add_parser("rehash", help="store the body hash; status back to proposed, check fields cleared")
    r.add_argument("file")
    a = p.parse_args(argv)
    if a.cmd == "rehash":
        h = rehash(Path(a.file))
        print("%s: body_sha256 %s, status %s" % (a.file, h.body_sha256[:12], h.status))
        return 0
    entry = read_entry(a.source_id)
    try:
        found = for_source(entry)
    except TranscriptionError as e:
        print("FAILED, nothing is used:\n  " + "\n  ".join(e.problems))
        return 1
    print("%s: %s" % (entry.id, source_dir(entry)))
    for page, t in sorted(found["approved"].items()):
        print("  p.%d approved by %s on %s: replaces the converter's text (%d blocks)" % (
            page, t.header.checked_by, t.header.checked_at, len(t.blocks)))
    for t, status, problems in found["other"]:
        stale = body_sha256(t.body) != t.header.body_sha256
        print("  p.%d %s: not used%s%s" % (t.page, status, "; body_sha256 not current" if stale else "",
                                          "".join("; " + x for x in problems)))
    if not found["approved"] and not found["other"]:
        print("  no transcriptions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
