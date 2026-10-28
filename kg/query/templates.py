"""Parameterised query templates (schema "Answering a question"). The Cypher is fixed; only parameters
change, and the LLM never writes graph queries. Each template fetches every candidate of its subtype for
the crop (no LIMIT); applicability, conditions, ranking and visibility are applied in kg.query.answer.
"""

from typing import NamedTuple

# schema "Cross-state policy"
CROSS_FREELY = {"QualitySpec", "Caution"}
FALLBACK_ONLY = {"DryingSpec", "StorageRule", "PestThreshold", "HarvestRule"}


QUALITY_FIELDS = ("commodity_form", "grades", "parameter", "parameter_raw", "limit_type", "limit_value",
                  "limit_inclusive", "unit", "part_of", "season_label", "authority")


class Template(NamedTuple):
    subtype: str
    fields: tuple[str, ...]        # the values an answer shows
    window: bool = False           # storage_months window (DryingSpec, StorageRule)
    safety: bool = False           # join Cautions; ingredients fail closed
    needs_pest: bool = False


TEMPLATES = {
    "drying_target": Template("DryingSpec", (
        "target_moisture_pct_min", "target_moisture_pct_max", "target_moisture_pct_min_inclusive",
        "target_moisture_pct_max_inclusive", "storage_term_raw", "storage_months_min", "storage_months_max",
        "method"), window=True),
    "storage": Template("StorageRule", (
        "storage_months_min", "storage_months_max", "storage_months_min_inclusive", "storage_months_max_inclusive",
        "min_moisture_pct", "min_moisture_pct_inclusive", "max_moisture_pct", "max_moisture_pct_inclusive",
        "structure"), window=True, safety=True),
    "harvest_readiness": Template("HarvestRule", (
        "maturity_signs", "harvest_moisture_pct_min", "harvest_moisture_pct_max", "threshing_moisture_pct_min",
        "threshing_moisture_pct_max", "duration_group")),
    "threshold": Template("PestThreshold", (), needs_pest=True),
    # schema v1.5: Q19 "Will the mandi accept my paddy at 18% moisture?"
    "quality_check": Template("QualitySpec", QUALITY_FIELDS),
    # schema v1.6: Q1 "Which paddy variety should I sow?" (the varieties are RECOMMENDS edges) and Q2 "When
    # should I sow?" (one answer slot per window_for); neither ever crosses state lines
    "varieties_for": Template("VarietyRecommendation", ("note",)),
    "sowing_window": Template("SowingWindow", ("window_for", "start_month", "start_day", "end_month", "end_day",
                                               "raw_start_month", "raw_end_month")),
}

_MATCH = """
MATCH (r:Recommendation:%s)-[:FOR_CROP]->(:Crop {id: $crop})
WHERE r.status <> 'rejected' AND r.superseded_by IS NULL
  AND (coalesce(r.missing_in_latest_run, false) = false OR r.status = 'approved')
  AND ($pest IS NULL OR EXISTS { (r)-[:FOR_PEST]->(:Concept {id: $pest}) })
  AND %s
"""
_LOCAL = "EXISTS { (r)-[:IN_REGION]->(g) WHERE g.id IN $region_ids }"
# another state's source, used only when the farmer's own regions return nothing
_FALLBACK = ("NOT EXISTS { (r)-[:IN_REGION]->(g) WHERE g.id IN $region_ids } "
             "AND EXISTS { (r)-[:EVIDENCED_BY]->(:SourceSpan)-[:IN_SOURCE]->(src:Source) "
             "WHERE src.state_id IS NOT NULL AND ($state IS NULL OR src.state_id <> $state) }")
# Optional relationship types are matched with type() so a graph that has none yet gives no warnings.
_RETURN = """
RETURN r {.*} AS fact,
  [(r)-[e:IN_REGION]->(g) | {id: g.id, level: g.level, origin: e.origin}] AS regions,
  [(r)-[e]->(x) WHERE type(e) = 'FOR_VARIETY' | x.id] AS variety_ids,
  [(r)-[e]->(x) WHERE type(e) = 'IN_SEASON' | x.id] AS season_ids,
  [(r)-[e]->(x) WHERE type(e) = 'UNDER_SYSTEM' | x.id] AS system_ids,
  [(r)-[e]->(x) WHERE type(e) = 'ON_SOIL' | x.id] AS soil_ids,
  [(r)-[e]->(x) WHERE type(e) = 'FOR_PURPOSE' | x.id] AS purpose_ids,
  [(r)-[e]->(x) WHERE type(e) = 'AT_STAGE' | x.id] AS stage_ids,
  [(r)-[e]->(x) WHERE type(e) = 'FOR_PEST' | x.id] AS pest_ids,
  [(r)-[e]->(x) WHERE type(e) = 'TARGETS' | x.id] AS target_ids,
  [(r)-[e]->(x) WHERE type(e) = 'CONCERNS' | x.id] AS concerns,
  [(r)-[e]->(x) WHERE type(e) = 'RECOMMENDS' | {id: x.id, name: x.name_en}] AS recommends,
  [(r)-[e]->(c) WHERE type(e) = 'WHEN' | c {.*}] AS conditions,
  [(r)-[:HAS_STEP]->(st) | st {.*,
      applies: [(st)-[a:APPLIES]->(t) | a {.*, target_id: t.id, target_name: t.name_en,
                                           is_ai: t:ActiveIngredient, reg_status: t.reg_status}],
      conditions: [(st)-[e]->(c) WHERE type(e) = 'WHEN' | c {.*}]}] AS steps,
  [(r)-[e]->(cl) WHERE type(e) = 'HAS_CLAUSE' | cl {.*, conditions: [(cl)-[w]->(c) WHERE type(w) = 'WHEN' | c {.*}]}]
      AS clauses,
  [(r)-[k]-(o) WHERE type(k) = 'CONFLICTS_WITH' | {id: o.id, subtype: o.subtype, status: o.status, origin: k.origin,
                                                   summary_en: o.summary_en,
                                                   quote: head([(o)-[:EVIDENCED_BY]->(os) | os.quote])}] AS conflicts,
  [(r)-[:EVIDENCED_BY]->(s)-[:IN_SOURCE]->(src) | {span: s {.*}, source: src {.id, .title, .authority_tier,
                                                   .edition_year, .state_id}}] AS evidence,
  [(r)-[:HAS_STEP]->()-[:APPLIES]->(:ActiveIngredient)<-[e]-(c:Caution) WHERE type(e) = 'CONCERNS' |
      c {.id, .summary_en, .text_en, .kind, .status}]
  + [(r)-[:HAS_STEP]->()-[:APPLIES]->(:ActiveIngredient)-[m]->(:AIGroup)<-[e]-(c:Caution)
     WHERE type(m) = 'MEMBER_OF' AND type(e) = 'CONCERNS' |
      c {.id, .summary_en, .text_en, .kind, .status}] AS cautions
"""
STATE_NAMES = "MATCH (s:State) RETURN s.id AS id, s.name_en AS name"


def query(template: Template, scope: str) -> str:
    """The template's Cypher for scope 'local' or 'fallback'."""
    if scope == "fallback" and template.subtype not in FALLBACK_ONLY | CROSS_FREELY:
        raise ValueError("%s never crosses state lines" % template.subtype)
    return _MATCH % (template.subtype, _LOCAL if scope == "local" else _FALLBACK) + _RETURN


def fetch(driver, template: Template, ctx, scope: str, database=None) -> list[dict]:
    rows, _, _ = driver.execute_query(query(template, scope), crop=ctx.crop, pest=ctx.pest,
                                      region_ids=ctx.region_ids(), state=ctx.state, database_=database)
    return [r.data() for r in rows]
