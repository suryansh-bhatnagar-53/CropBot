"""Printed units and bases -> canonical ones (schema Conventions), in code only.

Every rule returns its name so each conversion can be logged; a printed form with no rule
returns None and the fact is held, never guessed.
  1 acre = 0.404686 ha; 1 cent = 1/100 acre = 40.4686 m2; 1 quintal = 100 kg.
  per_cent_nursery: value per one cent of nursery; area_cents = the area the source stated.
Schema v1.3: strength units, sample sizes and repeat words are read here too, never by the model.
Schema v1.4: the word table ("a week", "in equal volume"), duration units and formulation codes.
"""

import re
from typing import NamedTuple

from kg.schema.vocab import (COUNT_WORDS, FORMULATION_OPERATION, INTERVAL_WORDS, PERIOD_WORDS, RATIO_WORDS,
                             Basis, ConcUnit, DurationUnit, RepeatUnit, SamplingObject, Unit)

HA_PER_ACRE = 0.404686
CENTS_PER_HA = 100 / HA_PER_ACRE            # 247.105...
ACRES_PER_HA = 1 / HA_PER_ACRE              # 2.47105...


class UnitRule(NamedTuple):
    unit: Unit
    factor: float
    rule: str


class BasisRule(NamedTuple):
    basis: Basis
    factor: float               # multiply the amount by this
    area_cents: float | None
    rule: str
    inference: bool             # the printed text alone does not fix the basis


UNITS = {
    "kg": (Unit.KG, 1), "kgs": (Unit.KG, 1), "g": (Unit.G, 1), "gm": (Unit.G, 1),
    "t": (Unit.T, 1), "tonne": (Unit.T, 1), "tonnes": (Unit.T, 1), "ton": (Unit.T, 1),
    "l": (Unit.L, 1), "lit": (Unit.L, 1), "litre": (Unit.L, 1), "liter": (Unit.L, 1), "lt": (Unit.L, 1),
    "ml": (Unit.ML, 1), "%": (Unit.PCT, 1), "pct": (Unit.PCT, 1), "per cent": (Unit.PCT, 1),
    "count": (Unit.COUNT, 1), "nos.": (Unit.COUNT, 1), "nos": (Unit.COUNT, 1), "no.": (Unit.COUNT, 1),
    "q": (Unit.KG, 100), "quintal": (Unit.KG, 100), "quintals": (Unit.KG, 100),
    "cm": (Unit.CM, 1), "m": (Unit.M, 1), "days": (Unit.DAYS, 1), "months": (Unit.MONTHS, 1),
}


def canon_unit(printed: str | None) -> UnitRule | None:
    if printed is None:
        return None
    key = printed.strip().lower()
    if key not in UNITS:
        return None
    unit, factor = UNITS[key]
    rule = "%s -> %s" % (printed, unit.value) + (" (x%g)" % factor if factor != 1 else "")
    return UnitRule(unit, factor, rule)


def _clean(text: str) -> str:
    t = text.lower().replace("(", " ").replace(")", " ").replace("@", " ")
    return re.sub(r"\s+", " ", t).strip()


def canon_basis(printed: str | None, nursery: bool = False, seed_treatment: bool = False) -> BasisRule | None:
    """`nursery`: the fact sits in a nursery section; `seed_treatment`: a treatment of seed."""
    if printed is None:
        return None
    t = _clean(printed)
    if t in ("per_ha", "/ha", "/ ha", "per ha", "per hectare", "/hectare", "ha-1", "ha -1"):
        return BasisRule(Basis.PER_HA, 1, None, "%s -> per_ha" % printed, False)
    if t in ("kernel/ha",):
        return BasisRule(Basis.PER_HA, 1, None, "%s -> per_ha (amount of kernel per ha)" % printed, False)
    if t in ("for one hectare", "one hectare of seeds", "for 1 ha"):
        return BasisRule(Basis.PER_HA, 1, None, "%s -> per_ha (the amount for one hectare)" % printed, True)
    if t in ("/acre", "/ acre", "per acre"):
        return BasisRule(Basis.PER_HA, ACRES_PER_HA, None, "%s -> per_ha (x%.5f)" % (printed, ACRES_PER_HA), False)
    m = re.fullmatch(r"(?:to|per|for)?\s*(\d+(?:\.\d+)?)\s*cents?\s*(?:of\s*)?nursery", t)
    if m:
        area = float(m.group(1))
        return BasisRule(Basis.PER_CENT_NURSERY, 1 / area, area,
                         "%s -> per_cent_nursery (/%g, area_cents %g)" % (printed, area, area), False)
    if t in ("/cent", "/ cent", "per cent", "per cent of nursery"):
        if nursery:
            return BasisRule(Basis.PER_CENT_NURSERY, 1, 1, "%s in a nursery section -> per_cent_nursery "
                                                            "(area_cents 1)" % printed, False)
        return BasisRule(Basis.PER_HA, CENTS_PER_HA, None, "%s -> per_ha (x%.3f)" % (printed, CENTS_PER_HA), False)
    m = re.fullmatch(r"per\s*(\d+(?:\.\d+)?)?\s*m\s*2|/\s*m\s*2|per\s*m2", t)
    if m:
        area = float(m.group(1)) if m.lastindex and m.group(1) else 1.0
        return BasisRule(Basis.PER_M2, 1 / area, None, "%s -> per_m2%s" % (printed, " (/%g)" % area if area != 1 else ""),
                         False)
    if re.fullmatch(r"/\s*kg\s*of\s*seeds?|per\s*kg\s*(?:of\s*)?seeds?", t):
        return BasisRule(Basis.PER_KG_SEED, 1, None, "%s -> per_kg_seed" % printed, False)
    if seed_treatment and re.fullmatch(r"/\s*kg", t):
        return BasisRule(Basis.PER_KG_SEED, 1, None, "%s in a seed treatment -> per_kg_seed" % printed, True)
    m = re.fullmatch(r"/\s*l(?:it)?\s*of\s*water(?:.*)?|per\s*l(?:itre)?\s*of\s*water", t)
    if m:
        return BasisRule(Basis.PER_L_WATER, 1, None, "%s -> per_l_water" % printed, False)
    m = re.fullmatch(r"in\s*(\d+(?:\.\d+)?)\s*l(?:it)?\s*of\s*water", t)
    if m:
        vol = float(m.group(1))
        return BasisRule(Basis.PER_L_WATER, 1 / vol, None, "%s -> per_l_water (/%g)" % (printed, vol), False)
    m = re.fullmatch(r"/\s*(tiller|hill|plant)", t)
    if m:
        return BasisRule(Basis("per_" + m.group(1)), 1, None, "%s -> per_%s" % (printed, m.group(1)), False)
    if t in ("per hill", "per tiller", "per plant"):
        return BasisRule(Basis(t.replace(" ", "_")), 1, None, "%s -> %s" % (printed, t.replace(" ", "_")), False)
    return None


CONC_UNITS = {"%": ConcUnit.PCT, "per cent": ConcUnit.PCT, "pct": ConcUnit.PCT, "w/w": ConcUnit.PCT,
              "% w/w": ConcUnit.PCT, "n": ConcUnit.NORMAL, "µm": ConcUnit.MICROMOLAR, "μm": ConcUnit.MICROMOLAR,
              "um": ConcUnit.MICROMOLAR, "micromolar": ConcUnit.MICROMOLAR}


def canon_conc_unit(printed: str | None) -> ConcUnit | None:
    """Schema v1.3 strength units. A damaged glyph ("�M") has no rule: the fact is held, never guessed."""
    return CONC_UNITS.get((printed or "").strip().lower())


SAMPLE_OBJECTS = ((r"net\s*sweeps?", SamplingObject.NET_SWEEP), (r"ear\s*heads?", SamplingObject.EARHEAD),
                  (r"pass(?:es)?", SamplingObject.PASS))


def sample(printed: str | None) -> tuple[int, SamplingObject] | None:
    """"/25 net sweeps" -> (25, net_sweep); "/100 ear heads" -> (100, earhead); "in 12 passes" -> (12, pass)."""
    t = _clean(printed or "")
    for rx, obj in SAMPLE_OBJECTS:
        m = re.fullmatch(r"(?:/|per|in)\s*(\d+)\s*%s" % rx, t)
        if m:
            return int(m.group(1)), obj
    return None


def repeat(printed: str | None) -> tuple[int | None, float | None, RepeatUnit | None, str] | None:
    """Count and interval from repeat words, by the fixed word table (schema v1.3) or printed digits:
    "thrice (at weekly interval" -> (3, 1, weeks). None when neither is found (the fact is held)."""
    t = _clean(printed or "")
    count = next((n for w, n in COUNT_WORDS.items() if re.search(r"\b%s\b" % w, t)), None)
    if count is None:
        m = re.search(r"\b(\d+)\s*times\b", t)
        count = int(m.group(1)) if m else None
    interval = unit = None
    word = next((w for w in INTERVAL_WORDS if re.search(r"\b%s\b" % w, t)), None)
    period = next((w for w in PERIOD_WORDS if re.search(r"\b%s\s+later\b" % w, t)), None)
    if word:
        interval, u = INTERVAL_WORDS[word]
        unit = RepeatUnit(u)
    elif period:                                     # schema v1.4: "second a week later" -> every 1 week
        interval, u = PERIOD_WORDS[period]
        unit = RepeatUnit(u)
    else:
        m = re.search(r"\b(?:every|at)\s*(\d+(?:\.\d+)?)\s*(days?|weeks?)\b|\b(\d+(?:\.\d+)?)\s*(days?|weeks?)\s*interval",
                      t)
        if m:
            interval = float(m.group(1) or m.group(3))
            unit = RepeatUnit((m.group(2) or m.group(4)).rstrip("s") + "s")
    if count is None and interval is None:
        return None
    rule = "repeat %r -> count %s, interval %s %s (word table)" % (printed, count, interval, unit.value if unit else "")
    return count, interval, unit, rule


def period_offset(timing_raw: str | None) -> tuple[float, str, str] | None:
    """Schema v1.4: a time printed only in words, "a week before harvest" -> (-1, "weeks", rule). One week is
    one week; it is never turned into days. None when the words are not in the word table."""
    t = _clean(timing_raw or "")
    for words, (n, unit) in PERIOD_WORDS.items():
        m = re.search(r"\b%s\s+(before|prior to|after)\b" % words, t)
        if m:
            sign = -1 if m.group(1) in ("before", "prior to") else 1
            return sign * n, unit, "offset %r -> %g %s (word table)" % (timing_raw, sign * n, unit)
    return None


def ratio_words(printed: str | None) -> tuple[float, float, str] | None:
    """Schema v1.4: a ratio printed only in words, "in equal volume" -> part 1, rest 1 (word table)."""
    t = _clean(printed or "")
    for words, (part, rest) in RATIO_WORDS.items():
        if t == words:
            return part, rest, "ratio %r -> %g : %g (word table)" % (printed, part, rest)
    return None


DURATION_UNITS = {"h": DurationUnit.HOURS, "hr": DurationUnit.HOURS, "hrs": DurationUnit.HOURS,
                  "hour": DurationUnit.HOURS, "hours": DurationUnit.HOURS, "min": DurationUnit.MINUTES,
                  "mins": DurationUnit.MINUTES, "minute": DurationUnit.MINUTES, "minutes": DurationUnit.MINUTES,
                  "day": DurationUnit.DAYS, "days": DurationUnit.DAYS}


def canon_duration_unit(printed: str | None) -> DurationUnit | None:
    """Schema v1.4: "h", "hrs", "minutes" -> hours / minutes / days. Anything else holds the fact."""
    return DURATION_UNITS.get((printed or "").strip().lower().rstrip("."))


FORMULATION_CODE = re.compile(r"(?<![A-Za-z])(%s)(?![A-Za-z])" % "|".join(
    sorted(FORMULATION_OPERATION, key=len, reverse=True)))


def formulation_code(formulation: str | None) -> str | None:
    """The formulation code in a printed formulation ("1.5% DP" -> "DP", "3% CG" -> "CG"), or None."""
    found = FORMULATION_CODE.findall(formulation or "")
    return found[-1] if found else None


def water_l_per_ha(printed: str | None) -> float | None:
    """"500 l/ha" -> 500; anything else (e.g. "1lit of water" for soaking) has no slot."""
    if not printed:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:l|lit|litres?)\s*/\s*ha", printed.strip().lower())
    return float(m.group(1)) if m else None
