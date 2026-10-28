"""Raw extraction model (step 9), separate from the final schema models in kg.schema.

The fields follow schema v1.2, but names, units and bases are kept as printed
("DAP", "kg", "per 20 cents"), never as IDs or canonical units; step 10 normalises
and links them. Numbers are parsed into value / min / max, and each keeps its
printed text. Crop and the book's regions are not asked of the model: code adds
them from the chapter and the unit.
"""

from typing import Annotated, ClassVar, Literal, Union

from pydantic import Field, PositiveInt, StringConstraints, TypeAdapter, model_validator

from kg.schema.core import Model, Text, check_groups, check_range
from kg.schema.vocab import (CONDITION_VARIABLES, Anchor, CautionKind, ConditionOp, ControlClass,
                             DoseBasis, DurationGroup, ExtractionFlag, OffsetUnit, OperationType, Subtype,
                             WeatherAdvice)

Pct = Annotated[float, Field(ge=0, le=100)]
NonNeg = Annotated[float, Field(ge=0)]
TableRef = Annotated[str, StringConstraints(pattern=r"^(tr:p\d{3,4})?#/tables/\d+$")]   # tr: a transcription
# Prompt v2 flags plus v1.3's scope_from_heading and operation_from_formulation (kg.schema.vocab).
# Step 11 sends every flagged fact to needs_review; kg.extract.versions says which flags a version may use.


class RawCondition(Model):
    """A runtime check, only for a variable in the fixed registry."""
    variable: str
    op: ConditionOp
    value: float | str | list[float | str]
    value_max: float | str | None = None
    unit: str | None = None                     # as printed
    any_of_group: PositiveInt = 1
    raw: Text

    @model_validator(mode="after")
    def _known(self):
        if self.variable not in CONDITION_VARIABLES:
            raise ValueError("unknown condition variable %r" % self.variable)
        return self


class RawQuantity(Model):
    """Step -[:APPLIES]-> what is applied; the amount as printed."""
    target: Text                                # name as printed: "DAP", "Carbendazim"
    value: NonNeg | None = None
    min: NonNeg | None = None
    max: NonNeg | None = None
    min_inclusive: bool = True
    max_inclusive: bool = True
    unit: str | None = None                     # as printed: "kg", "g", "ml", "tonne"
    basis: str | None = None                    # as printed: "/ha", "per 20 cents", "/kg of seed";
                                                # null when none is printed and the section gives none
    basis_inferred: bool = False                # basis not stated for this quantity: a guess, reviewed
    basis_rule: str | None = None               # the approved default-scope rule that gave the basis
    formulation: str | None = None              # "50 WP", "talc based"
    water_raw: str | None = None                # spray volume as printed: "500 l/ha"
    raw: Text | None = None                     # the whole quantity phrase
    quantity_ref: Literal["previous"] | None = None   # the amount was stated in an earlier bullet
    # prompt v3 (schema v1.3): strength, mixing parts and share of a dose, as printed
    conc_value: NonNeg | None = None
    conc_min: NonNeg | None = None
    conc_max: NonNeg | None = None
    conc_unit: str | None = None                # as printed: "%", "N", "µM"
    conc_raw: Text | None = None
    ratio_part: Annotated[float, Field(gt=0)] | None = None   # "1 part … with 49 parts": 1
    ratio_rest: Annotated[float, Field(gt=0)] | None = None   # … 49 (code computes the whole, 50)
    ratio_raw: Text | None = None
    share_pct: Annotated[float, Field(gt=0, le=100)] | None = None   # "basal (50%)": 50
    share_raw: Text | None = None
    # prompt v4 (schema v1.4): strength in a prepared mix and what the input is applied with or on
    mix_conc_value: Annotated[float, Field(gt=0)] | None = None   # "at 0.005%": 0.005
    mix_conc_unit: str | None = None            # as printed: "%"
    mix_conc_raw: Text | None = None
    carrier_raw: Text | None = None             # "chopped paddy straw", "popped corn/rice/dry fish"

    @model_validator(mode="after")
    def _amount(self):
        has_amount = any(v is not None for v in (self.value, self.min, self.max))
        if self.value is not None and (self.min is not None or self.max is not None):
            raise ValueError("give either value or min/max, not both")
        check_range(self, "min", "max")
        has_conc = any(v is not None for v in (self.conc_value, self.conc_min, self.conc_max))
        if has_conc and (self.conc_unit is None or self.conc_raw is None):
            raise ValueError("a strength needs conc_unit and conc_raw as printed")
        if self.conc_value is not None and (self.conc_min is not None or self.conc_max is not None):
            raise ValueError("give either conc_value or conc_min/conc_max, not both")
        check_range(self, "conc_min", "conc_max")
        has_ratio = any(v is not None for v in (self.ratio_part, self.ratio_rest, self.ratio_raw))
        numbers = (self.ratio_part, self.ratio_rest)
        # prompt v4: a ratio printed only in words ("in equal volume") is ratio_raw alone; the program reads it
        if (any(v is not None for v in numbers) and None in (*numbers, self.ratio_raw)) or \
                (self.ratio_part is None) != (self.ratio_rest is None):
            raise ValueError("a ratio needs ratio_part, ratio_rest and ratio_raw")
        if (self.share_pct is None) != (self.share_raw is None):
            raise ValueError("share_pct and share_raw go together")
        mix = (self.mix_conc_value, self.mix_conc_unit, self.mix_conc_raw)
        if any(v is not None for v in mix) and None in mix:
            raise ValueError("mix_conc_value, mix_conc_unit and mix_conc_raw go together")
        if has_amount:
            if self.raw is None or self.unit is None:
                raise ValueError("an amount needs its raw phrase and its unit as printed")
            if self.quantity_ref is not None:
                raise ValueError("quantity_ref is only for an amount stated earlier, not given here")
        elif self.quantity_ref is None and not (has_conc or has_ratio or self.share_pct is not None
                                                or self.mix_conc_value is not None):
            raise ValueError("no amount: set quantity_ref='previous' if it was stated earlier, "
                             "or give a strength, ratio or share")
        if self.basis_inferred and self.basis_rule:
            raise ValueError("a basis from an approved rule is not inferred")
        if (self.basis_inferred or self.basis_rule) and self.basis is None:
            raise ValueError("basis_inferred / basis_rule need the basis they give")
        if self.water_raw is not None and self.raw is None:
            raise ValueError("water_raw needs the raw quantity phrase")
        return self


class RawStep(Model):
    order: PositiveInt
    alt_group: PositiveInt | None = None
    alt_option: PositiveInt | None = None
    alt_priority: Literal[1, 2] | None = None   # 1 = preferred, 2 = fallback
    condition_raw: Text | None = None           # the words that make the step conditional or a fallback
    operation: OperationType | None = None      # null when no operation type fits (reported)
    method: str | None = None
    anchor: Anchor | None = None
    offset_min: float | None = None             # relative to anchor; negative = before
    offset_max: float | None = None
    offset_min_inclusive: bool = True
    offset_max_inclusive: bool = True
    offset_unit: OffsetUnit = OffsetUnit.DAYS
    stage: str | None = None                    # growth stage as printed
    month_start: int | None = Field(default=None, ge=1, le=12)
    month_end: int | None = Field(default=None, ge=1, le=12)
    timing_raw: Text | None = None
    repeat_raw: Text | None = None              # prompt v3: the repeat words as printed ("thrice (at weekly
                                                # interval"); code reads count and interval from a word table
    repeat_offsets: list[float] = []            # prompt v4: an option list at stated times, "15 and 30 DAT"
    duration_min: Annotated[float, Field(gt=0)] | None = None   # prompt v4: "soak for 12 - 16 h"
    duration_max: Annotated[float, Field(gt=0)] | None = None
    duration_min_inclusive: bool = True
    duration_max_inclusive: bool = True
    duration_unit: str | None = None            # as printed: "h", "hrs", "minutes"
    duration_raw: Text | None = None            # the phrase; "overnight" alone, with no number
    purpose_raw: Text | None = None             # prompt v4: why, copied verbatim
    instruction_en: Text | None = None          # prompt v1 only; from v2 code writes it (kg.extract.versions)
    applies: list[RawQuantity] = []
    conditions: list[RawCondition] = []

    @model_validator(mode="after")
    def _timing(self):
        timed = [self.offset_min, self.offset_max, self.stage, self.month_start, self.month_end]
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
        if self.repeat_offsets:
            if self.repeat_raw is None or self.timing_raw is None or self.anchor is None:
                raise ValueError("repeat_offsets need repeat_raw, timing_raw and an anchor")
            if self.offset_min != self.repeat_offsets[0] or self.offset_max != self.repeat_offsets[0]:
                raise ValueError("with repeat_offsets, offset_min and offset_max hold the first time")
        numbers = self.duration_min is not None or self.duration_max is not None
        if numbers and (self.duration_unit is None or self.duration_raw is None):
            raise ValueError("a duration needs its unit and its phrase as printed")
        if self.duration_unit is not None and not numbers:
            raise ValueError("duration_unit without a duration")
        check_range(self, "duration_min", "duration_max")
        return self


class RawThresholdClause(Model):
    observation: Text                           # "hoppers", "dead hearts"
    value: NonNeg
    unit: str | None = None                     # as printed: "%", "no."
    sampling_unit: str | None = None            # as printed: "/tiller", "per hill"
    stage: str | None = None                    # as printed
    raw: Text
    conditions: list[RawCondition] = []

    @model_validator(mode="after")
    def _groups(self):
        check_groups(self.conditions)
        return self


class RawExcludedRegion(Model):
    name: Text                                  # as printed: "Cauvery Delta"
    raw: Text                                   # the whole phrase: "other than Cauvery Delta"


class RawFact(Model):
    """Core of every raw fact. A subtype's numeric fields need raw[field]."""
    NUMERIC_FIELDS: ClassVar[tuple[str, ...]] = ()

    subtype: Subtype
    summary_en: Text
    quote: Text                                 # exact, contiguous source text
    table_ref: TableRef | None = None
    table_row: int | None = Field(default=None, ge=0)
    table_col: int | None = Field(default=None, ge=0)
    duration_group: DurationGroup | None = None
    # applicability as printed; crop and the book's regions come from code
    varieties: list[Text] = []
    seasons: list[Text] = []
    systems: list[Text] = []
    soils: list[Text] = []
    purposes: list[Text] = []
    stages: list[Text] = []
    regions: list[Text] = []                    # only regions the text names as this fact's scope
    excluded_regions: list[RawExcludedRegion] = []
    unmapped: list[Text] = []                   # source phrases with no slot
    extraction_flags: list[ExtractionFlag] = []  # prompt v2
    raw: dict[str, Text] = {}
    steps: list[RawStep] = []
    conditions: list[RawCondition] = []

    @model_validator(mode="after")
    def _core(self):
        for name in self.NUMERIC_FIELDS:
            if getattr(self, name) is not None and name not in self.raw:
                raise ValueError("%s needs its printed text in raw[%r]" % (name, name))
        extra = set(self.raw) - set(self.NUMERIC_FIELDS)
        if extra:
            raise ValueError("raw has entries for non-numeric fields: %s" % sorted(extra))
        if (self.table_row is not None or self.table_col is not None) and self.table_ref is None:
            raise ValueError("table_row/table_col need a table_ref")
        check_groups(self.conditions)
        return self


# --- the 16 subtypes (schema v1.2 "Recommendation subtypes") -----------------------------

class VarietyRecommendation(RawFact):
    subtype: Literal["VarietyRecommendation"]
    recommends: list[Text] = Field(min_length=1)    # variety names as printed
    note: str | None = None


class SowingWindow(RawFact):
    NUMERIC_FIELDS = ("start_month", "start_day", "end_month", "end_day")
    subtype: Literal["SowingWindow"]
    # prompts v1-v5: the model writes the dates as numbers
    start_month: int | None = Field(default=None, ge=1, le=12)
    start_day: int | None = Field(default=None, ge=1, le=31)
    end_month: int | None = Field(default=None, ge=1, le=12)
    end_day: int | None = Field(default=None, ge=1, le=31)
    # prompt v6 (schema v1.6): what the window is for, and its calendar words as printed; the program reads the
    # dates from the fixed word table (kg.normalize.calendar)
    window_for: str | None = None
    start_raw: Text | None = None               # "2 nd fortnight May"
    end_raw: Text | None = None                 # "1 st week of June"; none for a single period

    @model_validator(mode="after")
    def _window(self):
        numbers = (self.start_month, self.start_day, self.end_month, self.end_day)
        if self.start_raw is None:
            if self.start_month is None or self.end_month is None:
                raise ValueError("a sowing window needs start_month and end_month, or start_raw (prompt v6)")
            if self.end_raw is not None:
                raise ValueError("end_raw needs start_raw")
        elif any(v is not None for v in numbers):
            raise ValueError("a window given in calendar words has no numbers; the program reads them")
        return self


class SeedRate(RawFact):
    subtype: Literal["SeedRate"]
    method: str | None = None                       # the rate itself is a Step quantity


class Spacing(RawFact):
    NUMERIC_FIELDS = ("row_cm", "plant_cm", "hills_per_m2", "seedlings_per_hill",
                      "seedlings_per_hill_min", "seedlings_per_hill_max")
    subtype: Literal["Spacing"]
    row_cm: NonNeg | None = None
    plant_cm: NonNeg | None = None
    hills_per_m2: NonNeg | None = None
    seedlings_per_hill: NonNeg | None = None        # prompts v1, v2
    seedlings_per_hill_min: NonNeg | None = None    # prompt v3 (schema v1.3)
    seedlings_per_hill_max: NonNeg | None = None
    seedlings_per_hill_min_inclusive: bool = True
    seedlings_per_hill_max_inclusive: bool = True

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "seedlings_per_hill_min", "seedlings_per_hill_max")
        return self


class SeedTreatment(RawFact):
    subtype: Literal["SeedTreatment"]


class NutrientDose(RawFact):
    subtype: Literal["NutrientDose"]
    dose_basis: DoseBasis

    @model_validator(mode="after")
    def _steps_apply(self):
        if not self.steps or any(not s.applies for s in self.steps):
            raise ValueError("a NutrientDose needs Steps, each with quantities")
        return self


class DoseFormula(RawFact):
    subtype: Literal["DoseFormula"]
    target_nutrient: Text
    coefficients_raw: Text                          # the formula as printed; step 10 parses it
    target_yield_unit: str | None = None
    soil_series: str | None = None
    valid_range: str | None = None


class IrrigationRule(RawFact):
    NUMERIC_FIELDS = ("depth_cm",)
    subtype: Literal["IrrigationRule"]
    depth_cm: NonNeg | None = None
    criterion: str | None = None                    # "hairline cracks"


class PestThreshold(RawFact):
    subtype: Literal["PestThreshold"]
    pests: list[Text] = Field(min_length=1)         # pest or disease names as printed
    clauses: list[RawThresholdClause] = Field(min_length=1)


class ControlMeasure(RawFact):
    subtype: Literal["ControlMeasure"]
    control_class: ControlClass
    # pest, disease, weed or disorder names as printed; prompt v4 never writes a generic target, so a
    # practice with no specific pest may have none (step 10 holds it: the schema needs a target)
    targets: list[Text] = []

    @model_validator(mode="after")
    def _has_steps(self):
        if not self.steps:
            raise ValueError("a ControlMeasure needs at least one Step")
        return self


class WeatherRule(RawFact):
    subtype: Literal["WeatherRule"]
    operation: OperationType | None = None
    advice: WeatherAdvice


class HarvestRule(RawFact):
    NUMERIC_FIELDS = ("harvest_moisture_pct_min", "harvest_moisture_pct_max",
                      "threshing_moisture_pct_min", "threshing_moisture_pct_max")
    subtype: Literal["HarvestRule"]
    maturity_signs: list[Text] = []
    harvest_moisture_pct_min: Pct | None = None
    harvest_moisture_pct_max: Pct | None = None
    threshing_moisture_pct_min: Pct | None = None
    threshing_moisture_pct_max: Pct | None = None
    harvest_moisture_pct_min_inclusive: bool = True
    harvest_moisture_pct_max_inclusive: bool = True
    threshing_moisture_pct_min_inclusive: bool = True
    threshing_moisture_pct_max_inclusive: bool = True

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "harvest_moisture_pct_min", "harvest_moisture_pct_max")
        check_range(self, "threshing_moisture_pct_min", "threshing_moisture_pct_max")
        return self


class DryingSpec(RawFact):
    NUMERIC_FIELDS = ("target_moisture_pct_min", "target_moisture_pct_max",
                      "storage_months_min", "storage_months_max")
    subtype: Literal["DryingSpec"]
    target_moisture_pct_min: Pct | None = None
    target_moisture_pct_max: Pct | None = None
    storage_months_min: NonNeg | None = None
    storage_months_max: NonNeg | None = None
    target_moisture_pct_min_inclusive: bool = True
    target_moisture_pct_max_inclusive: bool = True
    storage_months_min_inclusive: bool = True
    storage_months_max_inclusive: bool = True
    storage_term_raw: Text | None = None            # "short term", "long term"
    method: str | None = None

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "target_moisture_pct_min", "target_moisture_pct_max")
        check_range(self, "storage_months_min", "storage_months_max")
        return self


class StorageRule(RawFact):
    NUMERIC_FIELDS = ("storage_months_min", "storage_months_max", "min_moisture_pct", "max_moisture_pct")
    subtype: Literal["StorageRule"]
    storage_months_min: NonNeg | None = None
    storage_months_max: NonNeg | None = None
    min_moisture_pct: Pct | None = None             # prompt v3 (schema v1.3)
    max_moisture_pct: Pct | None = None
    storage_months_min_inclusive: bool = True
    storage_months_max_inclusive: bool = True
    min_moisture_pct_inclusive: bool = True
    max_moisture_pct_inclusive: bool = True
    structure: str | None = None
    targets: list[Text] = []                        # storage pests as printed

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "storage_months_min", "storage_months_max")
        check_range(self, "min_moisture_pct", "max_moisture_pct")
        return self


class QualitySpec(RawFact):
    NUMERIC_FIELDS = ("limit_value",)
    subtype: Literal["QualitySpec"]
    authority: str | None = None                    # prompts v1-v4; v5 takes it from the registry
    valid_for_season: str | None = None             # prompts v1-v4; v5 takes the season from the registry
    parameter: Text                                 # v5: a value of the fixed list (step 10 checks it)
    limit_value: NonNeg | None = None
    unit: str | None = None                         # as printed ("%"), or empty for a ratio or an absent limit
    # prompt v5 (schema v1.5); step 10 checks the vocabulary values
    commodity_form: str | None = None
    grades: list[str] = []                          # only when the quote names the grade
    parameter_raw: str | None = None                # the refraction as printed
    limit_type: str | None = None                   # max | min | absent
    limit_inclusive: bool = True
    part_of: str | None = None                      # the parameter a sub-limit sits inside


class Caution(RawFact):
    subtype: Literal["Caution"]
    kind: CautionKind
    text_en: Text
    concerns: list[Text] = []                       # active ingredients or a class as printed
    about: list[Text] = []                          # prompt v3: the pest the caution names, as printed


SUBTYPES = (VarietyRecommendation, SowingWindow, SeedRate, Spacing, SeedTreatment, NutrientDose,
            DoseFormula, IrrigationRule, PestThreshold, ControlMeasure, WeatherRule, HarvestRule,
            DryingSpec, StorageRule, QualitySpec, Caution)
assert {m.model_fields["subtype"].annotation.__args__[0] for m in SUBTYPES} == set(Subtype)

Fact = Annotated[Union[SUBTYPES], Field(discriminator="subtype")]
FACT = TypeAdapter(Fact)


class NotExtracted(Model):
    """Prompt v2: a passage that is not a fact, with the reason. Its quote is checked too."""
    quote: Text
    reason: Text


NESTED = (RawStep, RawQuantity, RawCondition, RawThresholdClause, RawExcludedRegion)
