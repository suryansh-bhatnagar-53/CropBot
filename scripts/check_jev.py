"""Send the reference Jev request from docs/jev_example.md and print the raw reply.

The URL and JSON body are read from the curl command in docs/jev_example.md and
the body is sent byte for byte, so the request cannot drift from the doc. The
key comes from BEATAPI_API_KEY in .env and is never printed.

--save writes the reply only if it is HTTP 2xx, valid JSON, and contains
neither the key nor anything that looks like one; otherwise nothing is written
and the script exits with an error.

Usage: uv run python scripts/check_jev.py [--save PATH]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs" / "jev_example.md"
KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S")


def save_problems(status, text, key):
    """Return the reasons a reply must not be saved; empty means it is safe."""
    problems = []
    if not 200 <= status < 300:
        problems.append("HTTP %d is not a success" % status)
    try:
        json.loads(text)
    except ValueError:
        problems.append("body is not valid JSON")
    if key and key in text:
        problems.append("body contains the BEATAPI_API_KEY value")
    if KEY_LIKE.search(text):
        problems.append("body contains a key-like string (sk-... or Bearer ...)")
    return problems


def read_example():
    text = EXAMPLE.read_text(encoding="utf-8")
    url = re.search(r"curl\s+(https://\S+)", text)
    body = re.search(r"-d\s+'(.*?)'", text, re.DOTALL)
    if not url or not body:
        sys.exit("could not find the curl URL and -d body in %s" % EXAMPLE)
    return url.group(1), body.group(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", type=Path, help="also write the raw response body to this file")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.environ.get("BEATAPI_API_KEY")
    if not key:
        sys.exit("missing in .env: BEATAPI_API_KEY")

    url, body = read_example()
    resp = requests.post(
        url,
        data=body.encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        timeout=60,
    )
    print("HTTP", resp.status_code)
    print(resp.text.replace(key, "[REDACTED]"))
    if args.save:
        problems = save_problems(resp.status_code, resp.text, key)
        if problems:
            sys.exit("not saved to %s: %s" % (args.save, "; ".join(problems)))
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes(resp.content)
        print("saved to", args.save)


if __name__ == "__main__":
    main()
