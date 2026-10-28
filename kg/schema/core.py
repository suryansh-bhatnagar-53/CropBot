"""Recommendation core, value objects and provenance (docs/schema_v1.2.md).

A Recommendation model is a fact document: the node's properties plus its
outgoing edges as fields (regions, steps, conditions, evidence, ...). The
loader turns them into nodes and relationships. Whether an id points at an
existing concept is checked later, against concepts/, not here.
"""

import re
from datetime import date, datetime
from typing import Annotated, ClassVar, Literal

from pydantic import (BaseModel, ConfigDict, Field, PositiveInt, StringConstraints,
                      model_validator)

from .ids import (AppliesTargetId, CropId, PurposeId, RecId, RegionId, SeasonRef,
                  SoilId, SourceId, SpanId, StageId, StateId, SystemId, VarietyId,
                  _matcher)
from .vocab import (CONDITION_VARIABLES, Anchor, AuthorityTier, Basis, ConcUnit, ConditionOnlyUnit,
                    ConditionOp, DurationGroup, DurationUnit, ExtractionFlag, ExtractionMethod, OffsetUnit,
                    OperationType, Purpose, Rating, RegionOrigin, RepeatUnit, SamplingObject, Status,
                    Subtype, Unit, ValueType)

# at least one non-space character; source text is never stripped or rewritten
Text = Annotated[str, StringConstraints(pattern=r"\S")]
TABLE_REF = r"^(tr:p\d{3,4})?#/tables/\d+$"      # converter table, or a page transcription's (kg.transcribe)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def check_bound(obj, name: str) -> None:
    """A bound marked exclusive (`<name>_inclusive = False`) must have a value."""
    if not getattr(obj, name + "_inclusive", True) and getattr(obj, name) is None:
        raise ValueError("%s_inclusive is false but %s is empty" % (name, name))


def check_range(obj, low: str, high: str) -> None:
    """low <= high, and an equal pair must include both ends (else the range is empty)."""
    check_bound(obj, low)
    check_bound(obj, high)
    lo, hi = getattr(obj, low), getattr(obj, high)
    if lo is None or hi is None:
        return
    if lo > hi:
        raise ValueError("%s (%s) is greater than %s (%s)" % (low, lo, high, hi))
    both_inclusive = getattr(obj, low + "_inclusive", True) and getattr(obj, high + "_inclusive", True)
    if lo == hi and not both_inclusive:
        raise ValueError("%s and %s are equal but not both inclusive: empty range" % (low, high))


def check_groups(conditions: list["Condition"]) -> None:
    """any_of_group numbers on one owner run 1..n with no gaps."""
    groups = sorted({c.any_of_group for c in conditions})
    if groups != list(range(1, len(groups) + 1)):
        raise ValueError("any_of_group values must run 1..n without gaps, got %s" % groups)


# --- Condition ---------------------------------------------------------------------

_is_variety = _matcher("variety")
_EQUALITY_OPS = {ConditionOp.EQ, ConditionOp.NE, ConditionOp.IN}
_CONCEPT_VALUE = re.compile(r"^(pest|disease):[a-z0-9_]+$")


def _check_condition_value(value_type: ValueType, value) -> None:
    if value_type is ValueType.NUMBER:
        ok = isinstance(value, float)
    elif value_type is ValueType.RATING:
        ok = value in set(Rating)
    elif value_type is ValueType.PURPOSE:
        ok = value in set(Purpose)
    elif value_type is ValueType.DATE:
        try:
            ok = isinstance(value, str) and bool(date.fromisoformat(value))
        except ValueError:
            ok = False
    elif value_type is ValueType.CONCEPT:    # schema v1.4: endemic_area names a pest or disease
        ok = isinstance(value, str) and bool(_CONCEPT_VALUE.match(value))
    else:  # VARIETY
        try:
            ok = isinstance(value, str) and bool(_is_variety(value))
        except ValueError:
            ok = False
    if not ok:
        raise ValueError("%r is not a valid %s value" % (value, value_type.value))


class Condition(Model):
    """A runtime check. Same any_of_group = OR; different groups = AND."""
    variable: str
    op: ConditionOp
    value: float | str | list[float | str]
    value_max: float | str | None = None
    unit: Unit | ConditionOnlyUnit | None = None
    any_of_group: PositiveInt
    raw: Text

    @model_validator(mode="after")
    def _normal_form(self):
        spec = CONDITION_VARIABLES.get(self.variable)
        if spec is None:
            raise ValueError("unknown condition variable %r" % self.variable)
        if self.unit != spec.unit:
            raise ValueError("%s takes unit %s, not %s" % (self.variable, spec.unit, self.unit))
        if spec.value_type is not ValueType.NUMBER and spec.value_type is not ValueType.DATE \
                and self.op not in _EQUALITY_OPS:
            raise ValueError("%s only takes ==, != or in" % self.variable)
        is_list = isinstance(self.value, list)
        if self.op is ConditionOp.IN:
            if not is_list or not self.value:
                raise ValueError("`in` needs a non-empty list value")
        elif is_list:
            raise ValueError("only `in` takes a list value")
        if self.op is ConditionOp.BETWEEN:
            if self.value_max is None:
                raise ValueError("`between` needs value and value_max")
        elif self.value_max is not None:
            raise ValueError("value_max is only used with `between`")
        values = list(self.value) if is_list else [self.value]
        if self.value_max is not None:
            values.append(self.value_max)
        for v in values:
            _check_condition_value(spec.value_type, v)
        if self.op is ConditionOp.BETWEEN and not self.value < self.value_max:
            raise ValueError("`between` needs value < value_max")
        return self


# --- ThresholdClause ----------------------------------------------------------------

class ThresholdClause(Model):
    """One threshold. A PestThreshold's clauses are alternatives, each gated by its own WHEN."""
    observation: Text
    value: float = Field(ge=0)
    unit: Unit
    sampling_unit: Basis | None = None
    sampling_count: PositiveInt | None = None        # schema v1.3: "/25 net sweeps" -> 25
    sampling_object: SamplingObject | None = None    # schema v1.3: net_sweep | earhead | pass
    stage_id: StageId | None = None
    any_of_group: PositiveInt | None = None   # optional and unused for now
    raw: Text                                 # schema v1.2: source text of the number
    conditions: list[Condition] = []

    @model_validator(mode="after")
    def _groups(self):
        check_groups(self.conditions)
        if (self.sampling_count is None) != (self.sampling_object is None):
            raise ValueError("sampling_count and sampling_object go together")
        if self.sampling_object is not None and self.sampling_unit is not None:
            raise ValueError("a sample is either a Basis sampling_unit or a count of sampling_object, not both")
        return self


# --- Step and its APPLIES edge ----------------------------------------------------------

class Applies(Model):
    """Step -[:APPLIES]-> Nutrient | Fertilizer | OrganicInput | ActiveIngredient."""
    target_id: AppliesTargetId
    value: float | None = Field(default=None, ge=0)
    min: float | None = Field(default=None, ge=0)
    max: float | None = Field(default=None, ge=0)
    min_inclusive: bool = True                 # schema v1.2: false for "more than"
    max_inclusive: bool = True                 # schema v1.2: false for "less than"
    unit: Unit | None = None
    basis: Basis | None = None
    formulation: str | None = None
    water_l_per_ha: float | None = Field(default=None, ge=0)
    raw: Text | None = None                    # covers the whole quantity phrase
    basis_inferred: bool = False               # basis not stated in the text; always reviewed
    area_cents: float | None = Field(default=None, gt=0)
    quantity_ref: Literal["previous"] | None = None
    inherited: bool = False
    # schema v1.3: solution strength, mixing ratio and share of the total dose, each with its raw text
    conc_value: float | None = Field(default=None, ge=0)
    conc_min: float | None = Field(default=None, ge=0)
    conc_max: float | None = Field(default=None, ge=0)
    conc_unit: ConcUnit | None = None
    conc_raw: Text | None = None
    ratio_part: float | None = Field(default=None, gt=0)
    ratio_whole: float | None = Field(default=None, gt=0)
    ratio_raw: Text | None = None
    share_pct: float | None = Field(default=None, gt=0, le=100)
    share_raw: Text | None = None
    # schema v1.4: strength in a prepared mix ("bromadiolone … at 0.005%") and what the input is applied
    # with or on ("chopped paddy straw", "popped corn/rice/dry fish")
    mix_conc_value: float | None = Field(default=None, gt=0)
    mix_conc_unit: ConcUnit | None = None
    mix_conc_raw: Text | None = None
    carrier_raw: Text | None = None

    @model_validator(mode="after")
    def _quantity(self):
        amount = [self.value, self.min, self.max]
        has_amount = any(v is not None for v in amount)
        if has_amount or self.water_l_per_ha is not None or self.area_cents is not None:
            if self.raw is None:
                raise ValueError("a quantity needs its raw source text")
        if self.value is not None and (self.min is not None or self.max is not None):
            raise ValueError("give either value or min/max, not both")
        check_range(self, "min", "max")
        has_conc = any(v is not None for v in (self.conc_value, self.conc_min, self.conc_max))
        if has_conc:
            if self.conc_unit is None or self.conc_raw is None:
                raise ValueError("a concentration needs conc_unit and conc_raw")
            if self.conc_value is not None and (self.conc_min is not None or self.conc_max is not None):
                raise ValueError("give either conc_value or conc_min/conc_max, not both")
            check_range(self, "conc_min", "conc_max")
        elif self.conc_unit is not None or self.conc_raw is not None:
            raise ValueError("conc_unit / conc_raw without a concentration value")
        has_ratio = self.ratio_part is not None or self.ratio_whole is not None
        if has_ratio and (self.ratio_part is None or self.ratio_whole is None or self.ratio_raw is None):
            raise ValueError("a ratio needs ratio_part, ratio_whole and ratio_raw")
        if has_ratio and self.ratio_part >= self.ratio_whole:
            raise ValueError("ratio_part must be less than ratio_whole (1 part in 50: part 1, whole 50)")
        if (self.share_pct is None) != (self.share_raw is None):
            raise ValueError("share_pct and share_raw go together")
        mix = (self.mix_conc_value, self.mix_conc_unit, self.mix_conc_raw)
        if any(v is not None for v in mix) and None in mix:
            raise ValueError("mix_conc_value, mix_conc_unit and mix_conc_raw go together")
        if has_amount:
            if self.unit is None or self.basis is None:
                raise ValueError("a quantity needs a unit and a basis")
        elif self.quantity_ref is None and not (has_conc or has_ratio or self.share_pct is not None
                                                or self.mix_conc_value is not None):
            raise ValueError("no amount: set quantity_ref='previous' if it was stated earlier, "
                             "or give a concentration, ratio or share")
        if (self.basis is Basis.PER_CENT_NURSERY) != (self.area_cents is not None):
            raise ValueError("basis per_cent_nursery and area_cents go together")
        if self.inherited and self.quantity_ref != "previous":
            raise ValueError("inherited amounts come from quantity_ref='previous'")
        return self


class Step(Model):
    order: PositiveInt
    alt_group: PositiveInt | None = None
    alt_option: PositiveInt | None = None
    alt_priority: Literal[1, 2] | None = None   # 1 = preferred, 2 = fallback
    condition_raw: Text | None = None
    operation: OperationType
    method: str | None = None
    anchor: Anchor | None = None
    offset_min: float | None = None             # relative to anchor; negative = before
    offset_max: float | None = None
    offset_min_inclusive: bool = True           # schema v1.2
    offset_max_inclusive: bool = True           # schema v1.2
    offset_unit: OffsetUnit = OffsetUnit.DAYS   # schema v1.2: days | hours
    stage_id: StageId | None = None
    month_start: int | None = Field(default=None, ge=1, le=12)
    month_end: int | None = Field(default=None, ge=1, le=12)
    # schema v1.3: a count with an interval ("thrice at weekly interval"); stated times are separate Steps,
    # except (v1.4) an option list applied at several stated times: repeat_offsets lists them all
    repeat_count: PositiveInt | None = None
    repeat_interval: float | None = Field(default=None, gt=0)
    repeat_interval_unit: RepeatUnit | None = None
    repeat_offsets: list[float] = []            # schema v1.4: "twice, 15 and 30 DAT" = [15, 30]
    repeat_raw: Text | None = None
    # schema v1.4: how long ("soak for 12 - 16 h"); "overnight" stays in duration_raw with no number
    duration_min: float | None = Field(default=None, gt=0)
    duration_max: float | None = Field(default=None, gt=0)
    duration_min_inclusive: bool = True
    duration_max_inclusive: bool = True
    duration_unit: DurationUnit | None = None
    duration_raw: Text | None = None
    purpose_raw: Text | None = None             # schema v1.4: why, copied verbatim ("to escape monsoon rains")
    timing_raw: Text | None = None
    instruction_en: Text
    applies: list[Applies] = []
    conditions: list[Condition] = []

    @model_validator(mode="after")
    def _repeat(self):
        if (self.repeat_interval is None) != (self.repeat_interval_unit is None):
            raise ValueError("repeat_interval and repeat_interval_unit go together")
        repeats = self.repeat_count is not None or self.repeat_interval is not None
        if repeats != (self.repeat_raw is not None):
            raise ValueError("a repeat needs repeat_raw, and repeat_raw needs a repeat count or interval")
        if self.repeat_offsets:
            offs = self.repeat_offsets
            if len(offs) < 2 or offs != sorted(set(offs)):
                raise ValueError("repeat_offsets needs at least two stated times, increasing")
            if self.repeat_count != len(offs) or self.repeat_interval is not None:
                raise ValueError("with repeat_offsets, repeat_count equals their number and there is no interval")
            if self.offset_min != offs[0] or self.offset_max != offs[0]:
                raise ValueError("with repeat_offsets, offset_min and offset_max hold the first time")
        return self

    @model_validator(mode="after")
    def _duration(self):
        numbers = self.duration_min is not None or self.duration_max is not None
        if numbers and (self.duration_unit is None or self.duration_raw is None):
            raise ValueError("a duration needs duration_unit and duration_raw")
        if self.duration_unit is not None and not numbers:
            raise ValueError("duration_unit set without a duration")
        check_range(self, "duration_min", "duration_max")
        return self

    @model_validator(mode="after")
    def _timing(self):
        timed = [self.offset_min, self.offset_max, self.stage_id,
                 self.month_start, self.month_end]
        if any(v is not None for v in timed) and self.timing_raw is None:
            raise ValueError("step timing needs timing_raw")
        offsets = self.offset_min is not None or self.offset_max is not None
        if offsets and self.anchor in (None, Anchor.CALENDAR):
            raise ValueError("offsets need a non-calendar anchor")
        if self.offset_unit is not OffsetUnit.DAYS and not offsets:
            raise ValueError("offset_unit %s set without offsets" % self.offset_unit.value)
        check_range(self, "offset_min", "offset_max")
        if (self.anchor is Anchor.CALENDAR) != (self.month_start is not None):
            raise ValueError("a calendar anchor and month_start go together")
        if self.month_end is not None and self.month_start is None:
            raise ValueError("month_end needs month_start")
        if (self.alt_option is not None or self.alt_priority is not None) and self.alt_group is None:
            raise ValueError("alt_option and alt_priority need an alt_group")
        check_groups(self.conditions)
        return self


# --- Provenance ---------------------------------------------------------------------------

class BBox(Model):
    l: float
    t: float
    r: float
    b: float
    coord_origin: Literal["TOPLEFT", "BOTTOMLEFT"]   # as Docling reports it


class SourceSpan(Model):
    """(:Recommendation)-[:EVIDENCED_BY]->(:SourceSpan)-[:IN_SOURCE]->(:Source)."""
    id: SpanId
    source_id: SourceId
    # schema v1.2: replaces v1.1's single `page`
    pdf_page: PositiveInt                 # PDF page, to locate the text (what Docling reports)
    printed_page: str | None = None       # page label printed in the book, for citations
    bbox: BBox | None = None
    section_path: Text                    # "Rice > 1.8 Main field > 1.8.6 Irrigation management"
    quote: Text                           # exact source text
    # "#/tables/N" in the converter's document, or "tr:p006#/tables/N" in a page transcription (v1.5 candidate)
    table_ref: Annotated[str, StringConstraints(pattern=TABLE_REF)] | None = None
    table_row: int | None = Field(default=None, ge=0)   # schema v1.2: cell inside table_ref
    table_col: int | None = Field(default=None, ge=0)   # schema v1.2
    extraction_method: ExtractionMethod
    # v1.5 candidate: the approved transcription the quote comes from, and its body hash
    transcription: str | None = None
    transcription_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None

    @model_validator(mode="after")
    def _table_cell(self):
        if (self.table_row is not None or self.table_col is not None) and self.table_ref is None:
            raise ValueError("table_row/table_col need a table_ref")
        manual = self.extraction_method == ExtractionMethod.MANUAL_TRANSCRIPTION
        if manual != bool(self.transcription and self.transcription_sha256):
            raise ValueError("a manual_transcription span names its transcription and body hash; no other span does")
        if self.table_ref and self.table_ref.startswith("tr:") and not manual:
            raise ValueError("a tr: table_ref needs extraction_method manual_transcription")
        return self


class Source(Model):
    id: SourceId
    title: Text
    publisher: Text
    edition_year: int | None = None       # start year, used for ranking ("2021-22" -> 2021)
    edition_label: str | None = None      # schema v1.2: the edition as written, e.g. "2021-22"
    language: Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}$")]
    url: Annotated[str, StringConstraints(pattern=r"^https?://\S+$")]
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    state_id: StateId | None = None       # whose book it is; None for national books
    region_scope: list[RegionId] = Field(min_length=1)
    authority_tier: AuthorityTier
    # schema v1.2: a list of approved rules, each optionally section-scoped;
    # the registry (registry/*.toml) holds the full rule with its quote and page
    default_scope: list[str] = []

    @model_validator(mode="after")
    def _edition(self):
        if self.edition_label is not None:
            if self.edition_year is None or not self.edition_label.startswith(str(self.edition_year)):
                raise ValueError("edition_year must be the start year of edition_label %r"
                                 % self.edition_label)
        return self


# --- Recommendation core ----------------------------------------------------------------

class RegionRef(Model):
    id: RegionId
    origin: RegionOrigin


class ExcludedRegion(Model):
    """Schema v1.2: a region the text excludes ("other than Cauvery Delta").

    The extractor records it; code (never the LLM) expands it into IN_REGION
    edges to the state's remaining zones, with origin text_exclusion.
    """
    id: RegionId
    raw: Text


class Recommendation(Model):
    """Shared core of every (:Recommendation:<Subtype>) node."""
    NUMERIC_FIELDS: ClassVar[tuple[str, ...]] = ()   # subtype fields that need a raw entry

    id: RecId
    subtype: Subtype
    fact_key: Text
    summary_en: Text
    duration_group: DurationGroup | None = None
    status: Status = Status.EXTRACTED
    extraction_model: str | None = None
    verifier: str | None = None
    verifier_score: float | None = Field(default=None, ge=0, le=1)
    reviewed_by: str | None = None
    unmapped: list[str] = []
    extraction_flags: list[ExtractionFlag] = []   # schema v1.3: copied from the step 9 fact
    review_notes: list[str] = []                  # schema v1.3: approved registry notes (step 11)
    scope_in_unmapped: list[str] = []             # step 11: unmapped phrases that look like scope (not yet in v1.3)
    missing_in_latest_run: bool = False
    valid_from: date | None = None
    superseded_by: RecId | None = None
    created_at: datetime | None = None
    # schema v1.2: source text for each numeric subtype field
    raw: dict[str, Text] = {}

    # applicability edges; several edges of one kind are alternatives
    crop_ids: list[CropId] = Field(min_length=1)          # FOR_CROP (required)
    regions: list[RegionRef] = Field(min_length=1)        # IN_REGION (required)
    excluded_regions: list[ExcludedRegion] = []           # schema v1.2
    variety_ids: list[VarietyId] = []                     # FOR_VARIETY
    season_ids: list[SeasonRef] = []                      # IN_SEASON
    system_ids: list[SystemId] = []                       # UNDER_SYSTEM
    soil_ids: list[SoilId] = []                           # ON_SOIL
    purpose_ids: list[PurposeId] = []                     # FOR_PURPOSE
    stage_ids: list[StageId] = []                         # AT_STAGE

    steps: list[Step] = []                                # HAS_STEP
    conditions: list[Condition] = []                      # WHEN
    evidence: list[SourceSpan] = Field(min_length=1)      # EVIDENCED_BY (required)

    revision_of: RecId | None = None                      # REVISION_OF
    alternative_to: list[RecId] = []                      # ALTERNATIVE_TO
    conflicts_with: list[RecId] = []                      # CONFLICTS_WITH

    @model_validator(mode="after")
    def _core_rules(self):
        for name in self.NUMERIC_FIELDS:
            if getattr(self, name) is not None and name not in self.raw:
                raise ValueError("%s needs its raw source text in raw[%r]" % (name, name))
        extra = set(self.raw) - set(self.NUMERIC_FIELDS)
        if extra:
            raise ValueError("raw has entries for non-numeric fields: %s" % sorted(extra))
        if self.conflicts_with and self.status is not Status.NEEDS_REVIEW:
            raise ValueError("a recommendation with conflicts must be needs_review")
        expanded = any(r.origin is RegionOrigin.TEXT_EXCLUSION for r in self.regions)
        if expanded and not self.excluded_regions:
            raise ValueError("text_exclusion regions need the excluded_regions they were expanded from")
        if self.excluded_regions:
            if self.status is not Status.NEEDS_REVIEW:
                raise ValueError("a recommendation with an exclusion must be needs_review")
            clash = {r.id for r in self.regions} & {x.id for x in self.excluded_regions}
            if clash:
                raise ValueError("excluded region also in regions: %s" % sorted(clash))
        check_groups(self.conditions)
        return self
