"""What each prompt version's answer looks like. The raw model is shared; a version adds its
envelope and the fields it requires or forbids, so answers stored under v1 still check as v1."""

from typing import NamedTuple

from kg.schema.vocab import ExtractionFlag

from .model import NESTED, SUBTYPES, NotExtracted


class Version(NamedTuple):
    name: str
    envelope: str               # "list": a JSON list of facts; "object": {"facts", "not_extracted"}
    forbidden: frozenset        # fields the answer must not contain
    step_requires: frozenset    # fields every step must have
    coverage: bool              # every text line and table row must be quoted somewhere
    flags: frozenset = frozenset()   # extraction flags the version may use


# fields prompt v3 adds for schema v1.3; v1 and v2 answers never have them
V3_FIELDS = frozenset({"conc_value", "conc_min", "conc_max", "conc_unit", "conc_raw", "ratio_part", "ratio_rest",
                       "ratio_raw", "share_pct", "share_raw", "repeat_raw", "about", "seedlings_per_hill_min",
                       "seedlings_per_hill_max", "seedlings_per_hill_min_inclusive",
                       "seedlings_per_hill_max_inclusive", "min_moisture_pct", "min_moisture_pct_inclusive"})
V2_FLAGS = frozenset({"line_order_pairing", "spans_table_rows", "split_from_shared_line", "shared_amount",
                      "target_from_heading", "anchor_from_context"})
# fields prompt v4 adds for schema v1.4; v1 to v3 answers never have them
V4_FIELDS = frozenset({"repeat_offsets", "duration_min", "duration_max", "duration_min_inclusive",
                       "duration_max_inclusive", "duration_unit", "duration_raw", "purpose_raw", "mix_conc_value",
                       "mix_conc_unit", "mix_conc_raw", "carrier_raw"})
# general_practice is set by step 10 code only (2026-10-22); no prompt version may use it
V3_FLAGS = frozenset(f.value for f in ExtractionFlag) - {"general_practice"}
# v4: the program, not the model, applies the formulation table and sets operation_from_formulation
V4_FLAGS = V3_FLAGS - {"operation_from_formulation"}

# fields prompt v5 adds for schema v1.5's QualitySpec; v1 to v4 answers never have them. v5 drops authority and
# valid_for_season, which code takes from the registry
V5_FIELDS = frozenset({"commodity_form", "grades", "parameter_raw", "limit_type", "limit_inclusive", "part_of"})
V5_DROPPED = frozenset({"authority", "valid_for_season"})
# fields prompt v6 adds for schema v1.6's SowingWindow; v1 to v5 answers never have them. v6 drops the window's
# numbers: the model copies the calendar words and the program reads the dates
V6_FIELDS = frozenset({"window_for", "start_raw", "end_raw"})
V6_DROPPED = frozenset({"start_month", "start_day", "end_month", "end_day"})

VERSIONS = {
    "v1": Version("v1", "list", frozenset({"extraction_flags"}) | V3_FIELDS | V4_FIELDS | V5_FIELDS | V6_FIELDS,
                  frozenset({"instruction_en"}), False),
    "v2": Version("v2", "object", frozenset({"instruction_en"}) | V3_FIELDS | V4_FIELDS | V5_FIELDS | V6_FIELDS,
                  frozenset(), True, V2_FLAGS),
    "v3": Version("v3", "object", frozenset({"instruction_en", "seedlings_per_hill"}) | V4_FIELDS | V5_FIELDS
                  | V6_FIELDS, frozenset(), True, V3_FLAGS),
    "v4": Version("v4", "object", frozenset({"instruction_en", "seedlings_per_hill"}) | V5_FIELDS | V6_FIELDS,
                  frozenset(), True, V4_FLAGS),
    "v5": Version("v5", "object", frozenset({"instruction_en", "seedlings_per_hill"}) | V5_DROPPED | V6_FIELDS,
                  frozenset(), True, V4_FLAGS),
    "v6": Version("v6", "object", frozenset({"instruction_en", "seedlings_per_hill"}) | V5_DROPPED | V6_DROPPED,
                  frozenset(), True, V4_FLAGS),
}
# the default for prepare/report, and for step 10 when a source pins none (registry [extraction] prompt_version).
# v6 since 2026-10-24 (v5 from 2026-10-23); TNAU pins v4 and DFPD v5, the prompts their hand-runs used
LATEST = "v6"


def source_version(entry) -> str:
    """The prompt version a source's runs use: its registry pin, else LATEST."""
    return entry.extraction.prompt_version or LATEST


def field_names(version: str) -> set[str]:
    """Every field name the version's answer may use (the prompt's field reference lists them)."""
    v = VERSIONS[version]
    names = set()
    for m in SUBTYPES + NESTED:
        names |= set(m.model_fields)
    names -= v.forbidden
    if v.envelope == "object":
        names |= {"facts", "not_extracted"} | set(NotExtracted.model_fields)
    return names


def version_problems(item, version: str) -> list[str]:
    """Rules of the version that the shared model does not enforce."""
    v, out = VERSIONS[version], []
    if not isinstance(item, dict):
        return out
    for name in v.forbidden & set(item):
        out.append("%s: not part of prompt %s" % (name, version))
    for flag in set(item.get("extraction_flags") or []) - v.flags:
        if "extraction_flags" not in v.forbidden:
            out.append("extraction_flags: %r is not a flag of prompt %s" % (flag, version))
    if version in ("v1", "v2", "v3") and item.get("subtype") == "ControlMeasure" and not item.get("targets"):
        out.append("targets: a ControlMeasure needs a target in prompt %s" % version)
    if int(version[1:]) >= 6 and item.get("subtype") == "SowingWindow":
        for name in ("window_for", "start_raw"):
            if not item.get(name):
                out.append("%s: a SowingWindow needs it in prompt %s" % (name, version))
    for i, step in enumerate(item.get("steps") or []):
        if not isinstance(step, dict):
            continue
        for name in v.forbidden & set(step):
            out.append("steps.%d.%s: not part of prompt %s" % (i, name, version))
        for name in v.step_requires - set(step):
            out.append("steps.%d.%s: required by prompt %s" % (i, name, version))
        for j, q in enumerate(step.get("applies") or []):
            if isinstance(q, dict):
                for name in v.forbidden & set(q):
                    out.append("steps.%d.applies.%d.%s: not part of prompt %s" % (i, j, name, version))
    return out
