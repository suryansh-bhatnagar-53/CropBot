"""Heading numbers: "1.8.3.1.Seed rate", "II. PARTICULARS", "A) Pest management", "ii) Main field".

Schemes (each nests separately, in the order it first appears in its context):
  arabic        1. / 1.1 / 1.8.3.1. / "3 . Sowing"  (single-level numbers need the dot:
                "12 Points" is not numbered)
  roman         I. / II. / IV)
  letter        A) / B. / "B.Disease"
  roman_lower   ii) / (iii) / i.
  letter_lower  a) / b. / (c)
Only the split between number and title is done here; nothing is corrected.
"""

import re
from dataclasses import dataclass

ARABIC = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){1,4})\.?\s*(?=\S)|^\s*(\d{1,2})\s?\.\s*(?=\S)")
ROMAN = re.compile(r"^\s*([IVX]{1,5})\s*[.)]\s*(?=\S)")
LETTER = re.compile(r"^\s*([A-H])\s*[.)](?:\s+|(?=[A-Z][a-z]))(?=\S)")
ROMAN_LOWER = re.compile(r"^\s*(?:\(([ivx]{1,5})\)|([ivx]{1,5})[.)])\s*(?=\S)")
LETTER_LOWER = re.compile(r"^\s*(?:\(([a-h])\)|([a-h])[.)])\s+(?=\S)")
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10}


def roman_value(s: str) -> int:
    total = 0
    for a, b in zip(s.upper(), s.upper()[1:] + " "):
        v = ROMAN_VALUES[a]
        total += -v if b != " " and ROMAN_VALUES.get(b, 0) > v else v
    return total


@dataclass(frozen=True)
class Number:
    scheme: str             # arabic | roman | letter | roman_lower
    parts: tuple[int, ...]  # arabic: (1, 8, 3, 1); others: (value,)
    raw: str

    @property
    def depth(self) -> int:
        return len(self.parts)

    def parent_parts(self) -> tuple[int, ...] | None:
        return self.parts[:-1] if self.scheme == "arabic" and len(self.parts) > 1 else None

    def label(self) -> str:
        return ".".join(map(str, self.parts)) if self.scheme == "arabic" else self.raw.strip()


def parse(text: str) -> tuple[Number | None, str]:
    """(number, title). Title keeps the source wording; only the number is cut off."""
    m = ARABIC.match(text)
    if m:
        raw = m.group(1) or m.group(2)
        return Number("arabic", tuple(int(p) for p in raw.split(".")), raw), text[m.end():].strip()
    m = ROMAN.match(text)
    if m:
        return Number("roman", (roman_value(m.group(1)),), m.group(1)), text[m.end():].strip()
    m = LETTER.match(text)
    if m:
        return Number("letter", (ord(m.group(1)) - ord("A") + 1,), m.group(1)), text[m.end():].strip()
    m = ROMAN_LOWER.match(text)
    if m:
        raw = m.group(1) or m.group(2)
        return Number("roman_lower", (roman_value(raw),), raw), text[m.end():].strip()
    m = LETTER_LOWER.match(text)
    if m:
        raw = m.group(1) or m.group(2)
        return Number("letter_lower", (ord(raw) - ord("a") + 1,), raw), text[m.end():].strip()
    return None, text.strip()


PROMOTABLE = re.compile(r"^\s*\d{1,2}(?:\.\d{1,2}){1,4}\.?\s*[A-Z]")


def promotable(text: str) -> bool:
    """A body-text item that looks like a lost multi-level heading: "4.11.Disease management: ..."."""
    return bool(PROMOTABLE.match(text or "")) and len(text) <= 120


def is_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 5 and sum(c.isupper() for c in letters) / len(letters) >= 0.8
