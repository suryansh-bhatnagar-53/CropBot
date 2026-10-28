"""Printed numbers, including Indian digit grouping ("1,00,000" = 100000). Prompt v2 asks the model
to parse numbers this way and keep the printed text in `raw`; step 11 uses this to check that
every parsed value appears in its raw text."""

import re

# 1,00,000 / 10,00,000 (Indian: last group of 3, then groups of 2) or 100,000 (groups of 3)
GROUPED = re.compile(r"^\d{1,3}(,\d{3})+$|^\d{1,2}(,\d{2})*,\d{3}$")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def parse_number(text: str) -> float:
    """One printed number: "1,00,000" -> 100000, "1,000" -> 1000, "1.50" -> 1.5."""
    s = text.strip()
    whole, _, frac = s.partition(".")
    if "," in whole and not GROUPED.match(whole):
        raise ValueError("%r is not a grouped number" % text)
    if not whole.replace(",", "").isdigit() or (frac and not frac.isdigit()):
        raise ValueError("%r is not a number" % text)
    return float(whole.replace(",", "") + ("." + frac if frac else ""))


def printed_numbers(text: str) -> list[float]:
    """Every number printed in a phrase, in order."""
    out = []
    for m in NUMBER.finditer(text):
        token = m.group().rstrip(",")
        try:
            out.append(parse_number(token))
        except ValueError:
            out += [float(t) for t in token.split(",") if t]       # "120:40,40"-style lists
    return out
