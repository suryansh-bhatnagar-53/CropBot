"""ID formats: `<type>:<slug>`, lowercase (schema Conventions).

The schema names some prefixes (crop, variety, pest, ai, state, district,
country, zone, season_local, purpose); the others below are this module's
choice, kept in one place so they can change with the schema.
"""

import hashlib
import re
import unicodedata
from typing import Annotated

from pydantic import AfterValidator

SLUG = r"[a-z0-9][a-z0-9_]*"

PREFIX = {
    "recommendation": "rec",
    "source": "source",
    "span": "span",
    "crop": "crop",
    "variety": "variety",
    "stage": "stage",
    "pest": "pest",
    "disease": "disease",
    "weed": "weed",
    "disorder": "disorder",
    "ai": "ai",
    "ai_group": "ai_group",          # schema v1.3
    "input": "input",                # schema v1.3
    "fertilizer": "fertilizer",
    "organic_input": "organic_input",
    "nutrient": "nutrient",
    "season": "season",
    "local_season": "season_local",
    "system": "system",
    "soil": "soil",
    "purpose": "purpose",
    "operation": "operation",
    "label": "label",
}

# State and district IDs are official LGD codes; zones are a state-scheme prefix + slug.
REGION_RE = re.compile(r"^(country:in|state:\d+|district:\d+|zone:%s)$" % SLUG)


def _matcher(*kinds: str):
    prefixes = "|".join(PREFIX[k] for k in kinds)
    rx = re.compile(r"^(%s):%s$" % (prefixes, SLUG))

    def check(value: str) -> str:
        if not rx.match(value):
            raise ValueError("%r is not a %s id" % (value, " or ".join(kinds)))
        return value
    return check


def _region(value: str) -> str:
    if not REGION_RE.match(value):
        raise ValueError("%r is not a region id (country:in, state:<lgd>, "
                         "district:<lgd>, zone:<slug>)" % value)
    return value


RecId = Annotated[str, AfterValidator(_matcher("recommendation"))]
SourceId = Annotated[str, AfterValidator(_matcher("source"))]
SpanId = Annotated[str, AfterValidator(_matcher("span"))]
CropId = Annotated[str, AfterValidator(_matcher("crop"))]
VarietyId = Annotated[str, AfterValidator(_matcher("variety"))]
StageId = Annotated[str, AfterValidator(_matcher("stage"))]
SeasonRef = Annotated[str, AfterValidator(_matcher("season", "local_season"))]
SystemId = Annotated[str, AfterValidator(_matcher("system"))]
SoilId = Annotated[str, AfterValidator(_matcher("soil"))]
PurposeId = Annotated[str, AfterValidator(_matcher("purpose"))]
ActiveIngredientId = Annotated[str, AfterValidator(_matcher("ai"))]
PestId = Annotated[str, AfterValidator(_matcher("pest"))]
DiseaseId = Annotated[str, AfterValidator(_matcher("disease"))]
WeedId = Annotated[str, AfterValidator(_matcher("weed"))]
OrganicInputId = Annotated[str, AfterValidator(_matcher("organic_input"))]
PestOrDiseaseId = Annotated[str, AfterValidator(_matcher("pest", "disease"))]
ControlTargetId = Annotated[str, AfterValidator(_matcher("pest", "disease", "weed", "disorder"))]
StorageTargetId = Annotated[str, AfterValidator(_matcher("pest"))]
AppliesTargetId = Annotated[str, AfterValidator(
    _matcher("nutrient", "fertilizer", "organic_input", "ai", "input"))]
AIGroupId = Annotated[str, AfterValidator(_matcher("ai_group"))]
InputId = Annotated[str, AfterValidator(_matcher("input"))]
ConcernId = Annotated[str, AfterValidator(_matcher("ai", "ai_group"))]   # Caution CONCERNS (v1.3)


def _pattern(regex: str, what: str):
    rx = re.compile(regex)

    def check(value: str) -> str:
        if not rx.match(value):
            raise ValueError("%r is not a %s" % (value, what))
        return value
    return check


RegionId = Annotated[str, AfterValidator(_region)]
CountryId = Annotated[str, AfterValidator(_pattern(r"^country:in$", "country id (country:in)"))]
StateId = Annotated[str, AfterValidator(_pattern(r"^state:\d+$", "state id (state:<lgd>)"))]
DistrictId = Annotated[str, AfterValidator(
    _pattern(r"^district:\d+$", "district id (district:<lgd>)"))]
ZoneId = Annotated[str, AfterValidator(_pattern(r"^zone:%s$" % SLUG, "zone id (zone:<slug>)"))]
OperationId = Annotated[str, AfterValidator(_matcher("operation"))]
NutrientId = Annotated[str, AfterValidator(_matcher("nutrient"))]
FertilizerId = Annotated[str, AfterValidator(_matcher("fertilizer"))]
LocalSeasonId = Annotated[str, AfterValidator(_matcher("local_season"))]
SeasonId = Annotated[str, AfterValidator(_matcher("season"))]
LabelId = Annotated[str, AfterValidator(_matcher("label"))]


def label_id(concept_id: str, kind: str, lang: str, text: str) -> str:
    """label: + hash of concept id, kind, language and NFC-normalised text.

    Kind is part of the key, so the same text can be both an alias and a
    vernacular name of one concept.
    """
    key = "\x1f".join([concept_id, kind, lang, unicodedata.normalize("NFC", text)])
    return "label:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
