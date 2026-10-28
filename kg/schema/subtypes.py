"""Recommendation subtypes (schema v1.3): the nine first-slice subtypes ("Deferred and open
decisions"), then the other seven from the subtype table.

Each subtype adds only its own fields to the core. Numeric subtype fields are
listed in NUMERIC_FIELDS so the core can require their raw text. Every bound
has a `<field>_inclusive` flag (schema v1.2, default true): false
stores "less than 8 %" or "more than 15 months" exactly.
"""

import re
from typing import Annotated, Literal, Union

from pydantic import Field, TypeAdapter, model_validator

from .core import Recommendation, Text, ThresholdClause, check_range
from .ids import (ConcernId, ControlTargetId, NutrientId, PestOrDiseaseId, StorageTargetId, VarietyId)
from .vocab import (UNITLESS_PARAMETERS, CautionKind, CommodityForm, ControlClass, DoseBasis, Grade, LimitType,
                    OperationType, QualityParameter, Unit, WeatherAdvice, WindowFor)

Pct = Annotated[float, Field(ge=0, le=100)]
Months = Annotated[float, Field(ge=0)]


class VarietyRecommendation(Recommendation):
    subtype: Literal["VarietyRecommendation"]
    recommends: list[VarietyId] = Field(min_length=1)       # RECOMMENDS
    note: str | None = None


class SowingWindow(Recommendation):
    NUMERIC_FIELDS = ("start_month", "start_day", "end_month", "end_day")
    subtype: Literal["SowingWindow"]
    window_for: WindowFor = WindowFor.SOWING                # schema v1.6
    start_month: int = Field(ge=1, le=12)
    start_day: int | None = Field(default=None, ge=1, le=31)
    end_month: int = Field(ge=1, le=12)                     # may be before start_month (Dec-Jan)
    end_day: int | None = Field(default=None, ge=1, le=31)


class NutrientDose(Recommendation):
    subtype: Literal["NutrientDose"]
    dose_basis: DoseBasis

    @model_validator(mode="after")
    def _steps_apply(self):
        if not self.steps or any(not s.applies for s in self.steps):
            raise ValueError("a NutrientDose needs Steps, each with APPLIES quantities")
        return self


class PestThreshold(Recommendation):
    subtype: Literal["PestThreshold"]
    pest_ids: list[PestOrDiseaseId] = Field(min_length=1)   # FOR_PEST
    clauses: list[ThresholdClause] = Field(min_length=1)    # HAS_CLAUSE


class ControlMeasure(Recommendation):
    subtype: Literal["ControlMeasure"]
    control_class: ControlClass
    target_ids: list[ControlTargetId] = []  # TARGETS

    @model_validator(mode="after")
    def _has_steps(self):
        if not self.steps:
            raise ValueError("a ControlMeasure needs at least one Step")
        # v1.5 candidate (2026-10-22): targets are optional only for a general practice that names no pest
        if not self.target_ids and "general_practice" not in self.extraction_flags:
            raise ValueError("a ControlMeasure needs a target unless it is flagged general_practice")
        return self


class HarvestRule(Recommendation):
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


class DryingSpec(Recommendation):
    NUMERIC_FIELDS = ("target_moisture_pct_min", "target_moisture_pct_max",
                      "storage_months_min", "storage_months_max")
    subtype: Literal["DryingSpec"]
    target_moisture_pct_min: Pct | None = None
    target_moisture_pct_max: Pct | None = None
    storage_months_min: Months | None = None
    storage_months_max: Months | None = None
    target_moisture_pct_min_inclusive: bool = True
    target_moisture_pct_max_inclusive: bool = True
    storage_months_min_inclusive: bool = True
    storage_months_max_inclusive: bool = True
    storage_term_raw: Text | None = None
    method: str | None = None

    @model_validator(mode="after")
    def _storage_term(self):
        check_range(self, "target_moisture_pct_min", "target_moisture_pct_max")
        check_range(self, "storage_months_min", "storage_months_max")
        months = self.storage_months_min is not None or self.storage_months_max is not None
        if months and self.storage_term_raw and not re.search(r"\d", self.storage_term_raw):
            raise ValueError("storage given only as %r: storage_months must stay null"
                             % self.storage_term_raw)
        return self


class StorageRule(Recommendation):
    NUMERIC_FIELDS = ("storage_months_min", "storage_months_max", "min_moisture_pct", "max_moisture_pct")
    subtype: Literal["StorageRule"]
    storage_months_min: Months | None = None
    storage_months_max: Months | None = None
    min_moisture_pct: Pct | None = None      # schema v1.3: "12 - 13 %" keeps both bounds
    max_moisture_pct: Pct | None = None
    storage_months_min_inclusive: bool = True
    storage_months_max_inclusive: bool = True
    min_moisture_pct_inclusive: bool = True
    max_moisture_pct_inclusive: bool = True
    structure: str | None = None
    target_ids: list[StorageTargetId] = []   # TARGETS storage pests (context checked against concepts)

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "storage_months_min", "storage_months_max")
        check_range(self, "min_moisture_pct", "max_moisture_pct")
        return self


class Caution(Recommendation):
    subtype: Literal["Caution"]
    kind: CautionKind
    text_en: Text
    concerns: list[ConcernId] = []           # CONCERNS ActiveIngredient | AIGroup (v1.3); optional
    about_ids: list[PestOrDiseaseId] = []    # schema v1.3: ABOUT, the pest a warning names


FIRST_SLICE = (VarietyRecommendation, SowingWindow, NutrientDose, PestThreshold,
               ControlMeasure, HarvestRule, DryingSpec, StorageRule, Caution)


# --- the other seven subtypes (schema v1.2 table "Recommendation subtypes") -------------------

class SeedRate(Recommendation):
    subtype: Literal["SeedRate"]
    method: str | None = None                # the rate is a Step APPLIES quantity (kg per_ha)


class Spacing(Recommendation):
    NUMERIC_FIELDS = ("row_cm", "plant_cm", "hills_per_m2", "seedlings_per_hill_min", "seedlings_per_hill_max")
    subtype: Literal["Spacing"]
    row_cm: float | None = Field(default=None, ge=0)
    plant_cm: float | None = Field(default=None, ge=0)
    hills_per_m2: float | None = Field(default=None, ge=0)
    seedlings_per_hill_min: float | None = Field(default=None, ge=0)   # schema v1.3: "3 - 4 seedlings / hill"
    seedlings_per_hill_max: float | None = Field(default=None, ge=0)
    seedlings_per_hill_min_inclusive: bool = True
    seedlings_per_hill_max_inclusive: bool = True

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "seedlings_per_hill_min", "seedlings_per_hill_max")
        return self


class SeedTreatment(Recommendation):
    subtype: Literal["SeedTreatment"]        # Steps applying an agent per_kg_seed

    @model_validator(mode="after")
    def _has_steps(self):
        if not self.steps:
            raise ValueError("a SeedTreatment needs at least one Step")
        return self


class IrrigationRule(Recommendation):
    NUMERIC_FIELDS = ("depth_cm",)
    subtype: Literal["IrrigationRule"]
    depth_cm: float | None = Field(default=None, ge=0)
    criterion: str | None = None             # e.g. "hairline cracks"; timing via Steps


class DoseFormula(Recommendation):
    NUMERIC_FIELDS = ("coefficients",)
    subtype: Literal["DoseFormula"]
    target_nutrient: NutrientId
    coefficients: dict[Literal["T", "SN", "SP", "SK", "ON", "OP", "OK"], float] | None = None
    target_yield_unit: str | None = None
    soil_series: str | None = None
    valid_range: str | None = None


class WeatherRule(Recommendation):
    subtype: Literal["WeatherRule"]
    operation: OperationType | None = None
    advice: WeatherAdvice                    # Conditions on weather variables are the core `conditions`


class QualitySpec(Recommendation):
    """Schema v1.5: one fact per printed regulatory limit. authority and the season fields come from the
    registry (code), never from the model."""
    NUMERIC_FIELDS = ("limit_value",)
    subtype: Literal["QualitySpec"]
    authority: Text                          # the registry entry's publisher
    season_label: str | None = None          # as printed, e.g. "KHARIF MARKETING SEASON 2026-2027"
    marketing_season: str | None = None      # "KMS"
    season_start_year: int | None = None     # 2026
    commodity_form: CommodityForm
    grades: list[Grade] = Field(min_length=1)
    grades_origin: Literal["text", "section"]   # the quote names the grade, or an approved section scope does
    grades_evidence: str | None = None       # for origin section: the heading the scope quotes
    parameter: QualityParameter
    parameter_raw: Text                      # the refraction as printed
    limit_type: LimitType
    limit_value: float | None = Field(default=None, ge=0)
    limit_inclusive: bool = True
    unit: Unit | None = None
    part_of: QualityParameter | None = None  # the limit this sub-limit sits inside

    @model_validator(mode="after")
    def _limit(self):
        if self.limit_type == LimitType.ABSENT:
            if self.limit_value is not None or self.unit is not None:
                raise ValueError("an absent limit has no limit_value or unit")
        elif self.limit_value is None:
            raise ValueError("a %s limit needs limit_value" % self.limit_type.value)
        elif self.parameter in UNITLESS_PARAMETERS:
            if self.unit is not None:
                raise ValueError("%s has no unit" % self.parameter.value)
        elif self.unit != Unit.PCT:
            raise ValueError("a %s limit on %s is a percentage" % (self.limit_type.value, self.parameter.value))
        if self.part_of == self.parameter:
            raise ValueError("a limit cannot be part of itself")
        if self.grades_origin == "section" and not self.grades_evidence:
            raise ValueError("grades from a section scope need the heading as evidence")
        return self


ALL_SUBTYPES = FIRST_SLICE + (SeedRate, Spacing, SeedTreatment, IrrigationRule, DoseFormula,
                              WeatherRule, QualitySpec)

Fact = Annotated[Union[ALL_SUBTYPES], Field(discriminator="subtype")]
FACT = TypeAdapter(Fact)   # FACT.validate_python(data) picks the model from data["subtype"]
