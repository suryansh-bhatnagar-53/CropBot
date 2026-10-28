"""Schema v1.6 calendar words: a printed window bound ("2 nd fortnight May", "June end", "Mid March") read from
a fixed table, never by the model. The table (docs/schema_v1.6.md, "Changes from v1.5" 2):

  1st fortnight = days 1-15;  2nd fortnight = 16 to month end;  1st week = 1-7;
  last week and "end" = 25 to month end;  "mid" = 15.

A word opening a window gives the first day of its range, one closing it the last day; a period printed alone
("1 st Fortnight May") gives both. Both word orders are read ("April 2 nd fortnight", "2 nd fortnight May").
Anything else (a bare month, "2 nd week", "On set of monsoon") is unread: the caller holds the fact.
"""

import re
from typing import NamedTuple

MONTHS = {name: i for i, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"), start=1)}
MONTHS |= {name[:3]: i for name, i in list(MONTHS.items())} | {"sept": 9}
# February is read as 28 days: a printed window word never names the 29th
MONTH_END = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

# (pattern over the normalised words, rule text, first day, last day or None = month end); {m} is the month
WORDS = [
    (r"1st fortnight {m}|{m} 1st fortnight", "1st fortnight = days 1-15", 1, 15),
    (r"2nd fortnight {m}|{m} 2nd fortnight", "2nd fortnight = 16 to month end", 16, None),
    (r"1st week {m}|{m} 1st week", "1st week = days 1-7", 1, 7),
    (r"last week {m}|{m} last week", "last week = 25 to month end", 25, None),
    (r"{m} end|end {m}", "end = 25 to month end", 25, None),
    (r"mid {m}", "mid = 15", 15, 15),
]


MONTH_TEXT = ("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December")


def date_text(month: int, day: int) -> str:
    """"16 May"."""
    return "%d %s" % (day, MONTH_TEXT[month])


class Reading(NamedTuple):
    month: int
    first: int
    last: int
    rule: str


def words(text: str) -> str:
    """Lower case, ordinals joined ("2 nd" -> "2nd"), "of"/"the" and punctuation dropped."""
    t = re.sub(r"\b(\d)\s+(st|nd|rd|th)\b", r"\1\2", text.casefold())
    t = re.sub(r"[^0-9a-z]+", " ", t)
    return " ".join(w for w in t.split() if w not in ("of", "the"))


def read(text: str) -> Reading | None:
    """The month and day range one printed bound names, or None when the table has no such word."""
    w = words(text)
    for pattern, rule, first, last in WORDS:
        for name, month in MONTHS.items():
            if re.fullmatch(pattern.format(m=name), w):
                return Reading(month, first, last if last is not None else MONTH_END[month], rule)
    return None


def window(start_raw: str, end_raw: str | None) -> tuple[dict, list[dict]] | str:
    """The stored dates and one logged reading per bound, or a reason the words can't be read."""
    start = read(start_raw)
    end = read(end_raw) if end_raw else start
    if start is None:
        return "calendar words %r are not in the word table (schema v1.6)" % start_raw
    if end is None:
        return "calendar words %r are not in the word table (schema v1.6)" % end_raw
    dates = {"start_month": start.month, "start_day": start.first, "end_month": end.month, "end_day": end.last}
    readings = [{"bound": "start", "raw": start_raw, "rule": start.rule, "month": start.month, "day": start.first}]
    readings.append({"bound": "end", "raw": end_raw or start_raw, "rule": end.rule, "month": end.month, "day": end.last})
    return dates, readings
