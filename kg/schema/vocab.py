"""Fixed vocabularies from docs/schema_v1.2.md.

Every closed list in the schema lives here. Lists the schema leaves open
(production systems, soil types, nutrients: they end in "...") are concepts,
not vocabularies, and are seeded from concepts/.
"""

from enum import IntEnum, StrEnum
from typing import NamedTuple


# --- numbers -----------------------------------------------------------------

class Unit(StrEnum):
    """Canonical units (Conventions table)."""
    KG = "kg"
    G = "g"
    T = "t"
    L = "l"
    ML = "ml"
    CM = "cm"
    M = "m"
    DAYS = "days"
    MONTHS = "months"
    PCT = "pct"
    COUNT = "count"


class ConditionOnlyUnit(StrEnum):
    """Schema v1.2: units used only by condition variables."""
    MM = "mm"
    DEGC = "degC"


class Basis(StrEnum):
    """What a quantity is per (Conventions table). Also used for ThresholdClause.sampling_unit."""
    PER_HA = "per_ha"
    PER_KG_SEED = "per_kg_seed"
    PER_L_WATER = "per_l_water"
    PER_M2 = "per_m2"
    PER_HILL = "per_hill"
    PER_TILLER = "per_tiller"
    # value is the amount per one cent of nursery; `area_cents` records the nursery area the
    # source stated (provenance): "40 kg per 20 cents nursery" = value 2, area_cents 20
    PER_CENT_NURSERY = "per_cent_nursery"
    PER_PLANT = "per_plant"
    ABSOLUTE = "absolute"


# --- recommendation core -------------------------------------------------------

class Status(StrEnum):
    EXTRACTED = "extracted"
    AUTO_VERIFIED = "auto_verified"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Subtype(StrEnum):
    """All 16 subtypes; only the first slice has models in subtypes.py."""
    VARIETY_RECOMMENDATION = "VarietyRecommendation"
    SOWING_WINDOW = "SowingWindow"
    SEED_RATE = "SeedRate"
    SPACING = "Spacing"
    SEED_TREATMENT = "SeedTreatment"
    NUTRIENT_DOSE = "NutrientDose"
    DOSE_FORMULA = "DoseFormula"
    IRRIGATION_RULE = "IrrigationRule"
    PEST_THRESHOLD = "PestThreshold"
    CONTROL_MEASURE = "ControlMeasure"
    WEATHER_RULE = "WeatherRule"
    HARVEST_RULE = "HarvestRule"
    DRYING_SPEC = "DryingSpec"
    STORAGE_RULE = "StorageRule"
    QUALITY_SPEC = "QualitySpec"
    CAUTION = "Caution"


class DurationGroup(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class RegionOrigin(StrEnum):
    """Where an IN_REGION edge's scope came from."""
    TEXT = "text"
    SECTION = "section"
    SOURCE = "source"
    TEXT_EXCLUSION = "text_exclusion"   # schema v1.2: code expanded "other than <region>"


class Anchor(StrEnum):
    """Step timing anchors."""
    SOWING = "sowing"
    TRANSPLANTING = "transplanting"
    PI = "PI"
    FLOWERING = "flowering"
    HARVEST = "harvest"
    LAST_PUDDLING = "last_puddling"
    PULLING_OUT = "pulling_out"
    CALENDAR = "calendar"
    STORAGE_START = "storage_start"


class OffsetUnit(StrEnum):
    """Schema v1.2: unit of Step.offset_min/offset_max (v1.4 adds weeks: "a week before harvest")."""
    DAYS = "days"
    HOURS = "hours"
    WEEKS = "weeks"


class DurationUnit(StrEnum):
    """Schema v1.4: unit of Step.duration_min/duration_max ("soak for 12 - 16 h", "for 30 minutes")."""
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


class OperationType(StrEnum):
    SOWING = "sowing"
    TRANSPLANTING = "transplanting"
    IRRIGATION = "irrigation"
    FERTILIZER_APPLICATION = "fertilizer_application"
    SPRAYING = "spraying"
    DUSTING = "dusting"                  # schema v1.3
    APPLICATION = "application"          # v1.3: granules, biopesticides, treated material to soil or water
    SEED_TREATMENT = "seed_treatment"
    WEEDING = "weeding"
    RELEASE = "release"                  # v1.3: parasitoids, bioagents
    TRAPPING = "trapping"                # v1.3
    BAITING = "baiting"                  # v1.3
    BUND_MANAGEMENT = "bund_management"  # v1.3
    SANITATION = "sanitation"            # v1.3: removing or destroying stubble, egg masses, collected insects
    HARVEST = "harvest"
    THRESHING = "threshing"
    DRYING = "drying"
    STORAGE = "storage"


class ConditionOp(StrEnum):
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    EQ = "=="
    NE = "!="
    IN = "in"
    BETWEEN = "between"


# --- subtype fields ------------------------------------------------------------

class DoseBasis(StrEnum):
    BLANKET = "blanket"
    SOIL_TEST = "soil_test"
    LCC = "lcc"


class ControlClass(StrEnum):
    CULTURAL = "cultural"
    MECHANICAL = "mechanical"
    BIOLOGICAL = "biological"
    CHEMICAL = "chemical"
    PHYSICAL = "physical"


class WeatherAdvice(StrEnum):
    AVOID = "avoid"
    DELAY = "delay"
    DO = "do"
    PROTECT = "protect"


class CautionKind(StrEnum):
    PROHIBITION = "prohibition"
    SAFETY = "safety"
    INCOMPATIBILITY = "incompatibility"
    BANNED = "banned"
    WAITING_PERIOD = "waiting_period"


# --- provenance ----------------------------------------------------------------

class ExtractionMethod(StrEnum):
    NATIVE_TEXT = "native_text"
    OCR = "ocr"
    TABLE_PARSE = "table_parse"
    MANUAL_TRANSCRIPTION = "manual_transcription"   # v1.5 candidate: an approved page transcription (kg.transcribe)


class WindowFor(StrEnum):
    """Schema v1.6: which operation a SowingWindow is for, so a transplanting window is never served as a
    sowing window."""
    NURSERY_SOWING = "nursery_sowing"
    DIRECT_SEEDING = "direct_seeding"
    TRANSPLANTING = "transplanting"
    SOWING = "sowing"


class AuthorityTier(IntEnum):
    """0 = regulatory (official procurement or quality specification; schema v1.5); 1 = state agricultural
    university package of practices; 2 = ICAR national guidance; 3 = other. Lower ranks first."""
    REGULATORY = 0
    STATE_POP = 1
    ICAR = 2
    OTHER = 3


# --- schema v1.5: QualitySpec ------------------------------------------------------

class CommodityForm(StrEnum):
    PADDY = "paddy"
    RAW_RICE = "raw_rice"
    PARBOILED_RICE = "parboiled_rice"


class Grade(StrEnum):
    GRADE_A = "grade_a"
    COMMON = "common"


class LimitType(StrEnum):
    MAX = "max"
    MIN = "min"
    ABSENT = "absent"          # "free from …": the substance must not be present


class QualityParameter(StrEnum):
    """The fixed list (schema v1.5 "QualitySpec parameters"). A combined refraction is one parameter."""
    FOREIGN_MATTER_INORGANIC = "foreign_matter_inorganic"
    FOREIGN_MATTER_ORGANIC = "foreign_matter_organic"
    DAMAGED_DISCOLOURED_SPROUTED_WEEVILLED = "damaged_discoloured_sprouted_weevilled"
    DAMAGED_SPROUTED_WEEVILLED = "damaged_sprouted_weevilled"
    IMMATURE_SHRUNKEN_SHRIVELLED = "immature_shrunken_shrivelled"
    ADMIXTURE_LOWER_CLASS = "admixture_lower_class"
    MOISTURE = "moisture"
    POISONOUS_SEEDS = "poisonous_seeds"
    DHATURA_SEEDS = "dhatura_seeds"
    AKRA_SEEDS = "akra_seeds"
    LENGTH_BREADTH_RATIO = "length_breadth_ratio"
    # substances a specification requires to be absent (limit_type absent), as printed on DFPD p. 6
    MOULDS = "moulds"
    WEEVILS = "weevils"
    OBNOXIOUS_SMELL = "obnoxious_smell"
    ARGEMONE_MEXICANA = "argemone_mexicana"
    LATHYRUS_SATIVUS = "lathyrus_sativus"
    DELETERIOUS_SUBSTANCES = "deleterious_substances"


ABSENT_PARAMETERS = frozenset({QualityParameter.MOULDS, QualityParameter.WEEVILS, QualityParameter.OBNOXIOUS_SMELL,
                               QualityParameter.ARGEMONE_MEXICANA, QualityParameter.LATHYRUS_SATIVUS,
                               QualityParameter.DELETERIOUS_SUBSTANCES})
UNITLESS_PARAMETERS = frozenset({QualityParameter.LENGTH_BREADTH_RATIO})   # a ratio has no unit


# --- concepts (closed lists only; used by concepts/ seeds) ------------------------

class Season(StrEnum):
    KHARIF = "kharif"
    RABI = "rabi"
    ZAID = "zaid"
    SUMMER = "summer"
    PERENNIAL = "perennial"


class Purpose(StrEnum):
    GRAIN = "grain"
    SEED = "seed"
    FODDER = "fodder"
    GREEN_MANURE = "green_manure"


class CropGroup(StrEnum):
    CEREAL = "cereal"
    MILLET = "millet"
    PULSE = "pulse"
    OILSEED = "oilseed"
    FIBRE = "fibre"
    SUGAR = "sugar"
    FORAGE = "forage"
    VEGETABLE = "vegetable"
    FRUIT = "fruit"


class VarietyKind(StrEnum):
    VARIETY = "variety"
    HYBRID = "hybrid"


class PestType(StrEnum):
    INSECT = "insect"
    MITE = "mite"
    NEMATODE = "nematode"
    RODENT = "rodent"
    BIRD = "bird"
    MOLLUSC = "mollusc"


class PestContext(StrEnum):
    FIELD = "field"
    STORAGE = "storage"
    BOTH = "both"


class PathogenType(StrEnum):
    FUNGUS = "fungus"
    BACTERIUM = "bacterium"
    VIRUS = "virus"
    PHYTOPLASMA = "phytoplasma"
    NEMATODE = "nematode"


class WeedType(StrEnum):
    GRASS = "grass"
    SEDGE = "sedge"
    BROADLEAF = "broadleaf"


class DisorderKind(StrEnum):
    DEFICIENCY = "deficiency"
    TOXICITY = "toxicity"
    PHYSIOLOGICAL = "physiological"


class UseClass(StrEnum):
    INSECTICIDE = "insecticide"
    ACARICIDE = "acaricide"              # schema v1.3
    FUNGICIDE = "fungicide"
    HERBICIDE = "herbicide"
    NEMATICIDE = "nematicide"
    RODENTICIDE = "rodenticide"
    PGR = "PGR"
    BIOPESTICIDE = "biopesticide"        # schema v1.3


class RegStatus(StrEnum):
    REGISTERED = "registered"
    RESTRICTED = "restricted"
    BANNED = "banned"
    UNKNOWN = "unknown"


class OrganicInputKind(StrEnum):
    FYM = "fym"
    COMPOST = "compost"
    GREEN_MANURE = "green_manure"
    BIOFERTILIZER = "biofertilizer"
    PRESS_MUD = "press_mud"
    OTHER = "other"


class InputKind(StrEnum):
    """Schema v1.3 `Input`: applied things that are not nutrients, fertilisers, organic inputs or
    pesticide ingredients. Identity follows the substance, not the use."""
    SEED = "seed"
    BIOAGENT = "bioagent"
    TRAP = "trap"
    DEVICE = "device"
    SALT = "salt"
    CHEMICAL = "chemical"
    BOTANICAL = "botanical"
    AMENDMENT = "amendment"
    OTHER = "other"


class ConcUnit(StrEnum):
    """Schema v1.3: solution strength on APPLIES (conc_unit)."""
    PCT = "pct"
    NORMAL = "normal"
    MICROMOLAR = "micromolar"


class SamplingObject(StrEnum):
    """Schema v1.3: ThresholdClause samples outside Basis ("/25 net sweeps", "/100 earheads")."""
    NET_SWEEP = "net_sweep"
    EARHEAD = "earhead"
    PASS = "pass"


class RepeatUnit(StrEnum):
    """Schema v1.3: Step.repeat_interval_unit."""
    DAYS = "days"
    WEEKS = "weeks"


class ExtractionFlag(StrEnum):
    """How a fact was read when the page alone does not settle it (prompt v2, plus v1.3's two).
    A flagged fact is always reviewed."""
    LINE_ORDER_PAIRING = "line_order_pairing"      # a value matched to its label only by line order
    SPANS_TABLE_ROWS = "spans_table_rows"          # the quote runs across two table rows
    SPLIT_FROM_SHARED_LINE = "split_from_shared_line"   # one line split into several facts
    SHARED_AMOUNT = "shared_amount"                # one printed amount for several targets
    TARGET_FROM_HEADING = "target_from_heading"    # no target printed; taken from a heading
    ANCHOR_FROM_CONTEXT = "anchor_from_context"    # the timing anchor is not printed in the quote
    SCOPE_FROM_HEADING = "scope_from_heading"      # v1.3: applicability taken from a sub-heading
    OPERATION_FROM_FORMULATION = "operation_from_formulation"   # v1.3: mixed "Dust/ spray" lists
    GENERAL_PRACTICE = "general_practice"          # v1.5 candidate: a ControlMeasure naming no pest (set by code)


# Schema v1.3: count and interval words code reads (never the model): "thrice at weekly interval"
COUNT_WORDS = {"once": 1, "twice": 2, "thrice": 3}
INTERVAL_WORDS = {"daily": (1, "days"), "weekly": (1, "weeks"), "fortnightly": (2, "weeks")}
# Schema v1.4 (approved 2026-10-22): word readings code makes, never the model. "a week" is 1 week, never 7 days
PERIOD_WORDS = {"a week": (1, "weeks")}
RATIO_WORDS = {"in equal volume": (1, 1)}          # part : rest, as for "at the ratio of 1 : 1"

# Schema v1.4: the operation a formulation code implies. Only D/DP and G/GR/CG override a printed "spray";
# the spray codes confirm it. Any other printed verb, a carrier, a bait or a seed treatment is never overridden.
FORMULATION_OPERATION = {"D": "dusting", "DP": "dusting", "G": "application", "GR": "application",
                         "CG": "application", "EC": "spraying", "WP": "spraying", "SC": "spraying",
                         "WG": "spraying", "SG": "spraying", "SP": "spraying", "SL": "spraying"}
FORMULATION_OVERRIDES = {"D", "DP", "G", "GR", "CG"}

# Scope-like `unmapped` phrases (approved 2026-10-21): the fact carries no edge or condition for them, so
# its served scope would be wider than printed. Step 11 flags them; step 14 hides such a fact (not a
# Caution) until a person approves it. Regexes, case-insensitive. A phrase starting with "especially"
# narrows nothing ("especially in BPH and leaffolder prone areas/seasons" applies everywhere).
SCOPE_IN_UNMAPPED = {
    "variety": (r"\bfor\s+(\w+\s+)?(hybrids?|variet(y|ies))\b", r"\b(short|medium|long)\s+duration\b"),
    "area": (r"\b(areas?|endemic|prone|regions?|zones?|delta|tracts?|districts?)\b",),
    "condition": (r"\b(when|if|unless)\b", r"\bdepending\s+on\b", r"\bonly\b", r"\bsoils?\b"),
    "moisture": (r"\b\d+(\.\d+)?\s*(%|per\s*cent)\s+moisture\b",),
}
NOT_SCOPE = r"^\s*especially\b"
SCOPE_IN_UNMAPPED_REASON = "scope in unmapped: served scope would be wider than printed"


class ZoneScheme(StrEnum):
    STATE_BOOK = "state_book"
    ICAR_ACZ = "icar_acz"


class RegionLevel(IntEnum):
    COUNTRY = 1
    STATE = 2
    ZONE = 3
    DISTRICT = 4


class ReviewStatus(StrEnum):
    """Review state of a seeded concept or label. Facts linked to a needs_review
    concept must themselves be needs_review."""
    APPROVED = "approved"
    NEEDS_REVIEW = "needs_review"


class LabelKind(StrEnum):
    CANONICAL = "canonical"
    ALIAS = "alias"
    VERNACULAR = "vernacular"
    TRANSLITERATION = "transliteration"
    ABBREVIATION = "abbreviation"


# --- condition variables ---------------------------------------------------------

class OnUnknown(StrEnum):
    """What happens when a condition variable is missing from the farm context."""
    ASK_THEN_BRANCH = "ask_then_branch"   # ask; if the farmer does not know, branch
    CONSERVATIVE = "conservative"         # Cautions and "avoid" WeatherRules fire
    ASK = "ask"


class ValueType(StrEnum):
    NUMBER = "number"
    RATING = "rating"     # Rating values
    DATE = "date"         # ISO date
    VARIETY = "variety"   # a variety: id
    PURPOSE = "purpose"   # a Purpose value
    CONCEPT = "concept"   # schema v1.4: a pest: or disease: id ("endemic_area == disease:tungro")


class Rating(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConditionVariable(NamedTuple):
    value_type: ValueType
    unit: Unit | ConditionOnlyUnit | None
    on_unknown: OnUnknown


_N, _R = ValueType.NUMBER, ValueType.RATING
_ATB, _CONS, _ASK = OnUnknown.ASK_THEN_BRANCH, OnUnknown.CONSERVATIVE, OnUnknown.ASK

# Every condition variable named in schema v1.1: the examples under "Conditions",
# the farm-context example, and the on_unknown table in "Missing data".
CONDITION_VARIABLES: dict[str, ConditionVariable] = {
    "forecast_rain_mm_24h": ConditionVariable(_N, ConditionOnlyUnit.MM, _CONS),
    "forecast_rain_days_3d": ConditionVariable(_N, Unit.DAYS, _CONS),
    "tmax_c": ConditionVariable(_N, ConditionOnlyUnit.DEGC, _CONS),
    # sowing_date, variety and purpose are here for their on_unknown policy only.
    # Whether a fact applies to a variety or purpose is an edge (FOR_VARIETY,
    # FOR_PURPOSE), never a Condition.
    "sowing_date": ConditionVariable(ValueType.DATE, None, _ATB),
    "das": ConditionVariable(_N, Unit.DAYS, _ATB),
    "variety": ConditionVariable(ValueType.VARIETY, None, _ATB),
    "purpose": ConditionVariable(ValueType.PURPOSE, None, _ATB),
    "storage_months": ConditionVariable(_N, Unit.MONTHS, _ATB),
    "soil_N_rating": ConditionVariable(_R, None, _ATB),
    "soil_P_rating": ConditionVariable(_R, None, _ATB),
    "soil_K_rating": ConditionVariable(_R, None, _ATB),
    # schema v1.3: soil-test findings used as scope ("zinc deficient soils": deficient -> low)
    "soil_Zn_rating": ConditionVariable(_R, None, _ATB),
    "soil_pH": ConditionVariable(_N, None, _ATB),   # other soil values: add when a source needs them
    "grain_moisture_pct": ConditionVariable(_N, Unit.PCT, _ATB),
    "pest_count": ConditionVariable(_N, Unit.COUNT, _ASK),
    "spider_count_per_hill": ConditionVariable(_N, Unit.COUNT, _ASK),
    # schema v1.4: the farm lies in an area known for a pest or disease ("in tungro endemic area",
    # "in BPH prone areas/seasons"); the value is that concept
    "endemic_area": ConditionVariable(ValueType.CONCEPT, None, _ATB),
}
