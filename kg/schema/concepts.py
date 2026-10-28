"""Concept nodes seeded from concepts/ (schema "Concept nodes" and "Regions, seasons and scope").

Only the concepts the first seed needs are modelled. Every concept has
`name_en` (schema Conventions: "name_en on every concept"), a review_status,
and an optional `source` saying where a hand-entered value came from.
References to other concepts become edges (EDGES); the loader checks that
their targets exist.
"""

import json
from typing import ClassVar, Literal

from pydantic import Field, PositiveInt, field_validator, model_validator

from .core import Model, SourceSpan, Text, check_range
from .ids import (ActiveIngredientId, AIGroupId, CountryId, CropId, DiseaseId, DistrictId, FertilizerId,
                  InputId, LabelId, LocalSeasonId, NutrientId, OperationId, OrganicInputId, PestId,
                  PurposeId, SeasonId, SoilId, SourceId, StateId, SystemId, VarietyId, WeedId, ZoneId,
                  label_id)
from .vocab import (CropGroup, DurationGroup, InputKind, LabelKind, OperationType as OperationVocab,
                    OrganicInputKind, PathogenType, PestContext, PestType,
                    Purpose as PurposeVocab, RegStatus, ReviewStatus, Season as SeasonVocab,
                    UseClass, VarietyKind, WeedType, ZoneScheme)


class Concept(Model):
    LABEL: ClassVar[str]
    # field -> (relationship type, target node label); the field becomes an edge, not a property
    EDGES: ClassVar[dict[str, tuple[str, str]]] = {}
    # field -> target node label; the field stays a property but must point at an existing node
    REFS: ClassVar[dict[str, str]] = {}
    # closed vocabulary the id slug must belong to, if any
    VOCAB: ClassVar[type | None] = None

    id: str
    name_en: Text
    review_status: ReviewStatus
    source: str | None = None

    @model_validator(mode="after")
    def _slug_in_vocab(self):
        if self.VOCAB is not None:
            slug = self.id.split(":", 1)[1]
            if slug not in {m.value for m in self.VOCAB}:
                raise ValueError("%s is not in the schema's %s list" % (self.id, self.LABEL))
        return self

    def references(self) -> list[tuple[str, str, str]]:
        """(field, target id, target label) for every edge or reference field that is set."""
        targets = {f: label for f, (_, label) in self.EDGES.items()} | self.REFS
        return [(f, getattr(self, f), label) for f, label in targets.items()
                if getattr(self, f) is not None]

    def edges(self) -> list[tuple[str, str, str, dict]]:
        """(relationship type, target label, target id, relationship properties) for the loader."""
        return [(rel, label, getattr(self, f), {}) for f, (rel, label) in self.EDGES.items()
                if getattr(self, f) is not None]

    def props(self) -> dict:
        """Node properties. Neo4j properties are primitives or arrays of them, never maps:
        anything map-shaped is an edge (see Fertilizer.contains)."""
        return self.model_dump(mode="json", exclude={"id", *self.EDGES})


# --- regions ---------------------------------------------------------------------

class Country(Concept):
    LABEL = "Country"
    id: CountryId
    level: Literal[1] = 1


class State(Concept):
    LABEL = "State"
    EDGES = {"country_id": ("IN_COUNTRY", "Country")}
    id: StateId
    level: Literal[2] = 2
    country_id: CountryId


class AgroClimaticZone(Concept):
    LABEL = "AgroClimaticZone"
    REFS = {"state_id": "State"}
    id: ZoneId
    level: Literal[3] = 3
    scheme: ZoneScheme
    state_id: StateId | None = None     # a property, not an edge (schema)

    @model_validator(mode="after")
    def _state_scheme(self):
        if self.scheme is ZoneScheme.STATE_BOOK and self.state_id is None:
            raise ValueError("a state_book zone needs state_id")
        return self


class District(Concept):
    LABEL = "District"
    EDGES = {"state_id": ("IN_STATE", "State"), "zone_id": ("IN_ZONE", "AgroClimaticZone")}
    id: DistrictId
    level: Literal[4] = 4
    state_id: StateId
    zone_id: ZoneId | None = None       # IN_ZONE {scheme} edge; scheme is copied from the zone


# --- seasons, systems, soils, purposes, operations ----------------------------------

class Season(Concept):
    LABEL = "Season"
    VOCAB = SeasonVocab
    id: SeasonId


class LocalSeason(Concept):
    LABEL = "LocalSeason"
    EDGES = {"maps_to": ("MAPS_TO", "Season")}
    REFS = {"state_id": "State"}
    id: LocalSeasonId
    state_id: StateId                   # required: a Samba window never reaches another state
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    maps_to: SeasonId | None = None


class Purpose(Concept):
    LABEL = "Purpose"
    VOCAB = PurposeVocab
    id: PurposeId


class ProductionSystem(Concept):
    LABEL = "ProductionSystem"
    id: SystemId


class SoilType(Concept):
    LABEL = "SoilType"
    id: SoilId


class OperationType(Concept):
    LABEL = "OperationType"
    VOCAB = OperationVocab
    id: OperationId


# --- inputs and crops ------------------------------------------------------------------

class Nutrient(Concept):
    LABEL = "Nutrient"
    id: NutrientId
    symbol: Text                        # as the schema writes it: N, P2O5, K2O, ...


class NutrientShare(Model):
    """One (:Fertilizer)-[:CONTAINS {pct, raw}]->(:Nutrient) edge."""
    nutrient_id: NutrientId
    pct: float = Field(ge=0, le=100)
    raw: Text                           # the percentage as the source states it


class Fertilizer(Concept):
    """N, P2O5 and K2O stay properties (code turns "50 kg N" into kg of fertilizer with them);
    schema other{} (Zn, Fe, S, ...) is stored as CONTAINS edges, since a property is never a map."""
    LABEL = "Fertilizer"
    id: FertilizerId
    # optional (decided 2026-10-20): a fertilizer with no sourced grade still loads and links, and the
    # alternatives check skips it, since it uses approved percentages only
    n_pct: float | None = Field(default=None, ge=0, le=100)
    p2o5_pct: float | None = Field(default=None, ge=0, le=100)
    k2o_pct: float | None = Field(default=None, ge=0, le=100)
    contains: list[NutrientShare] = []  # seed CSV: a JSON list of {nutrient_id, pct, raw}
    source: Text                        # required: where the percentages come from

    @field_validator("contains", mode="before")
    @classmethod
    def _json(cls, v):
        return json.loads(v) if isinstance(v, str) else v

    @model_validator(mode="after")
    def _one_share_per_nutrient(self):
        ids = [s.nutrient_id for s in self.contains]
        if len(ids) != len(set(ids)):
            raise ValueError("a nutrient appears twice in contains")
        return self

    def references(self):
        return super().references() + [("contains", s.nutrient_id, "Nutrient") for s in self.contains]

    def edges(self):
        return super().edges() + [("CONTAINS", "Nutrient", s.nutrient_id, {"pct": s.pct, "raw": s.raw})
                                  for s in self.contains]

    def props(self) -> dict:
        return self.model_dump(mode="json", exclude={"id", "contains", *self.EDGES})


class OrganicInput(Concept):
    LABEL = "OrganicInput"
    id: OrganicInputId
    kind: OrganicInputKind


class AIGroup(Concept):
    """Schema v1.3: a chemical class a book names as a whole ("synthetic pyrethroids")."""
    LABEL = "AIGroup"
    id: AIGroupId


class ActiveIngredient(Concept):
    """reg_status comes from the official registration list (CIB&RC), never from books."""
    LABEL = "ActiveIngredient"
    id: ActiveIngredientId
    use_class: UseClass | None = None   # optional (schema v1.3)
    reg_status: RegStatus = RegStatus.UNKNOWN
    member_of: list[AIGroupId] = []     # MEMBER_OF AIGroup (v1.3); seed CSV: a JSON list of ids

    @field_validator("member_of", mode="before")
    @classmethod
    def _json(cls, v):
        return json.loads(v) if isinstance(v, str) else v

    def references(self):
        return super().references() + [("member_of", g, "AIGroup") for g in self.member_of]

    def edges(self):
        return super().edges() + [("MEMBER_OF", "AIGroup", g, {}) for g in self.member_of]

    def props(self) -> dict:
        return self.model_dump(mode="json", exclude={"id", "member_of", *self.EDGES})


class Input(Concept):
    """Schema v1.3: applied things that are not nutrients, fertilisers, organic inputs or pesticide
    ingredients (seed, Trichogramma, traps, common salt, KNO3, gypsum, plain leaf extracts)."""
    LABEL = "Input"
    id: InputId
    kind: InputKind


# --- pests, diseases, weeds ------------------------------------------------------------

class Pest(Concept):
    LABEL = "Pest"
    id: PestId
    scientific_name: str | None = None
    pest_type: PestType
    context: PestContext = PestContext.FIELD


class Disease(Concept):
    LABEL = "Disease"
    id: DiseaseId
    pathogen: str | None = None
    pathogen_type: PathogenType | None = None


class Weed(Concept):
    LABEL = "Weed"
    id: WeedId
    scientific_name: str | None = None
    weed_type: WeedType


class Crop(Concept):
    LABEL = "Crop"
    id: CropId
    scientific_name: str | None = None
    crop_group: CropGroup


class Variety(Concept):
    """A variety pivoted from a book's variety table (step 8), or seeded by hand (schema v1.6).

    The pivot is the one sanctioned exception to "never create concepts automatically":
    kg/tables always produces needs_review records, a reviewer may later approve them,
    and facts linked to an unapproved Variety are needs_review too. Every number keeps
    its raw text (schema v1.2), and every value keeps the table cell it came from.
    A hand-seeded variety (named outside variety tables, concepts/varieties.csv) has no
    table evidence; it records the printed text it was seeded from instead (`quote`,
    `pdf_page`, `source_id`).
    """
    LABEL = "Variety"
    EDGES = {"crop_id": ("VARIETY_OF", "Crop")}
    NUMERIC_FIELDS: ClassVar[tuple[str, ...]] = ("release_year", "duration_days_min",
                                                 "duration_days_max", "avg_yield_kg_ha")
    id: VarietyId
    name: Text                          # as written in the table header
    crop_id: CropId | None = None       # set only when the chapter is approved
    kind: VarietyKind | None = None     # "hybrid" only when the name says so
    release_year: int | None = None
    parentage: str | None = None
    duration_days_min: float | None = Field(default=None, ge=0)
    duration_days_max: float | None = Field(default=None, ge=0)
    duration_group: DurationGroup | None = None
    avg_yield_kg_ha: float | None = Field(default=None, ge=0)
    grain_type: str | None = None
    traits: list[str] = []
    raw: dict[str, Text] = {}           # schema v1.2
    cells: dict[str, dict] = {}         # field or trait label -> table cell provenance
    evidence: list[SourceSpan] = []     # a pivoted variety's table cells
    # schema v1.6: a hand-seeded variety's printed text, page and source
    quote: Text | None = None
    pdf_page: PositiveInt | None = None
    source_id: SourceId | None = None

    @model_validator(mode="after")
    def _variety_rules(self):
        for name in self.NUMERIC_FIELDS:
            if getattr(self, name) is not None and name not in self.raw:
                raise ValueError("%s needs its raw source text in raw[%r]" % (name, name))
        check_range(self, "duration_days_min", "duration_days_max")
        seeded = (self.quote, self.pdf_page, self.source_id)
        if self.evidence and any(seeded):
            raise ValueError("a variety has table evidence or a hand-seeded quote, not both")
        if not self.evidence and not all(seeded):
            raise ValueError("a variety needs table evidence, or a quote, pdf_page and source_id (hand-seeded)")
        return self

    def props(self) -> dict:
        """As step 13 stores a pivoted variety (kg.load.facts.variety_rows): raw{} as raw_<field> and cells{}
        as cells_json; table evidence becomes EVIDENCED_BY edges there, never a property."""
        props = self.model_dump(mode="json", exclude={"id", "raw", "cells", "evidence", *self.EDGES})
        props |= {"raw_%s" % k: v for k, v in self.raw.items()}
        props["cells_json"] = json.dumps(self.cells, sort_keys=True, ensure_ascii=False)
        return props


# --- labels ----------------------------------------------------------------------------

class Label(Model):
    """A word farmers or books use for a concept. Scientific names are Crop properties, not labels."""
    LABEL: ClassVar[str] = "Label"
    EDGES: ClassVar[dict[str, tuple[str, str]]] = {"concept_id": ("LABEL_OF", "Concept")}

    id: LabelId | None = None           # computed from concept_id, kind, lang and text
    concept_id: str
    text: Text
    lang: Text
    script: Text
    kind: LabelKind
    review_status: ReviewStatus
    source: str | None = None

    @model_validator(mode="after")
    def _id(self):
        expected = label_id(self.concept_id, self.kind.value, self.lang, self.text)
        if self.id is not None and self.id != expected:
            raise ValueError("label id %s does not match its fields (expected %s)"
                             % (self.id, expected))
        self.id = expected
        return self

    def references(self) -> list[tuple[str, str, str]]:
        return [("concept_id", self.concept_id, "Concept")]

    def edges(self) -> list[tuple[str, str, str, dict]]:
        return [("LABEL_OF", "Concept", self.concept_id, {})]

    def props(self) -> dict:
        return self.model_dump(mode="json", exclude={"id", "concept_id"})


SEED_FILES: dict[str, type] = {
    "countries.csv": Country,
    "states.csv": State,
    "zones.csv": AgroClimaticZone,
    "districts.csv": District,
    "seasons.csv": Season,
    "local_seasons.csv": LocalSeason,
    "purposes.csv": Purpose,
    "production_systems.csv": ProductionSystem,
    "soil_types.csv": SoilType,
    "operation_types.csv": OperationType,
    "nutrients.csv": Nutrient,
    "fertilizers.csv": Fertilizer,
    "crops.csv": Crop,
    "varieties.csv": Variety,                # schema v1.6: hand-seeded; after crops (VARIETY_OF)
    "pests.csv": Pest,
    "diseases.csv": Disease,
    "weeds.csv": Weed,
    "ai_groups.csv": AIGroup,                # schema v1.3; before active_ingredients (MEMBER_OF)
    "active_ingredients.csv": ActiveIngredient,
    "organic_inputs.csv": OrganicInput,
    "inputs.csv": Input,                     # schema v1.3
    "labels.csv": Label,
}

# concept models whose rows are drafted in concepts/proposed/ and not loaded until approved
PROPOSED_FILES: dict[str, type] = {
    "states.csv": State,                     # schema v1.6: Uttarakhand and its zones
    "zones.csv": AgroClimaticZone,
    "varieties.csv": Variety,                # schema v1.6: hand-seeded varieties
    "pests.csv": Pest,
    "diseases.csv": Disease,
    "weeds.csv": Weed,
    "ai_groups.csv": AIGroup,
    "active_ingredients.csv": ActiveIngredient,
    "organic_inputs.csv": OrganicInput,
    "inputs.csv": Input,
    "fertilizers.csv": Fertilizer,
    "labels.csv": Label,
}

# seed files that must hold exactly the schema's closed list
CLOSED_LISTS = {Season: SeasonVocab, Purpose: PurposeVocab, OperationType: OperationVocab}
