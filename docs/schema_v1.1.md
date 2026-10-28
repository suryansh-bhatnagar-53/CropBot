Superseded: this is the v1.1 draft. The current schema is docs/schema_v1.2.md in the CropBot repo (branch kg-pipeline). Don’t edit or export this doc; schema changes are made in the repo.

# CropBot Knowledge Graph Schema (v1.1)

Oct 20, 2026 · @Shivaansh Gusain

Every agronomic fact is stored as its own Recommendation node: where and when it applies, the runtime conditions it depends on, the ordered steps it prescribes, and the exact source text itp came from. The bot can then answer only with facts that apply to this farmer, and cite them.

## At a glance

&#91;embedded content: schema at a glance · farm context, query, recommendation and its parts\]

The agent turns the farmer's context into slots for one query template; the template reads Recommendation nodes through their applicability edges, evaluates their Conditions, and returns Steps with their source quotes.

## Design principles

The schema follows eight rules. Every later section applies them.

1. **One fact = one node.** Farm advice is n-ary: "150:50:50 kg NPK/ha for irrigated medium-duration rice in zone Z, split three ways" has about ten participants. Neo4j relationships cannot point at other relationships, so each fact is a `Recommendation` node with edges to everything it involves.
2. **Every fact has the same four parts:** applicability (where and for whom) + runtime conditions (when) + ordered steps (what to do) + provenance (where it came from).
3. **Numbers are typed, never only text.** Doses, durations, moisture levels and counts are stored as values with a unit and a basis, and the original text is kept beside them.
4. **Scope is explicit.** Every fact has at least one region edge. A missing edge never means "applies everywhere"; national scope is an explicit edge to the country node.
5. **Conflicts are kept, never averaged.** Two sources that disagree become two nodes, linked as conflicting, and the bot shows the disagreement.
6. **Unknown resolves toward safety.** If farm data is missing, a caution still fires and an action is withheld (the bot asks or branches).
7. **Canonical facts are in English with language-neutral IDs.** Other languages attach as labels; embeddings are used for matching, not for storing facts.
8. **The graph holds knowledge, not live data.** Weather, mandi prices and farmer profiles live outside it and are passed in at question time.

## Conventions

IDs are stable, readable and prefixed by type; numbers always carry a canonical unit and a basis.

| Convention | Rule | Examples |
| --- | --- | --- |
| Node ID | `<type>:<slug>`, lowercase, unique per label | `crop:rice`, `variety:adt53`, `pest:brown_planthopper`, `ai:chlorantraniliprole` |
| Region ID | Official LGD code for states and districts | `district:<lgd_code>`, `state:<lgd_code>`, `country:in` |
| Zone ID | State scheme prefix + slug | `zone:tn_cauvery_delta` |
| Canonical name | `name_en` on every concept; other names are `Label` nodes | `name_en: "Brown planthopper"` |
| Units | `kg, g, t, l, ml, cm, m, days, months, pct, count` | Code converts acre, cent and quintal; the LLM never converts units |
| Basis | `per_ha, per_kg_seed, per_l_water, per_m2, per_hill, per_tiller, per_cent_nursery, per_plant, absolute` | "40 kg DAP per 20 cents of nursery" = basis `per_cent_nursery` |
| Raw text | Every number keeps its `raw` source string | `raw: "150 ml"` |
| Loading | Always `MERGE` on `id`, never `CREATE` | Re-loading a book never duplicates nodes |

1 cent = 40.47 m² = 1/100 acre. A book-level rule such as "doses are per ha unless otherwise specified" is stored once on the Source as `default_scope` and applied at extraction time.

## Concept nodes

Concepts are the stable things facts talk about. All of them also carry the shared label `:Concept` for the vector index.

| Label | Key properties | Edges and notes |
| --- | --- | --- |
| `Crop` | id, name\_en, scientific\_name, crop\_group (`cereal \| millet \| pulse \| oilseed \| fibre \| sugar \| forage \| vegetable \| fruit`) | Root of every fact |
| `Variety` | id, name, kind (`variety \| hybrid`), release\_year, parentage, duration\_days\_min/max, duration\_group (`short \| medium \| long`), avg\_yield\_kg\_ha, grain\_type, traits\[\] | `-[:VARIETY_OF]->Crop`, `-[:EVIDENCED_BY]->SourceSpan` |
| `GrowthStage` | id, crop\_id, name\_en, code (e.g. `PI`), order | `-[:TYPICAL_TIMING {duration_group, anchor, day_min, day_max}]->Crop` turns a sowing date into a stage |
| `Pest` | id, name\_en, scientific\_name, pest\_type (`insect \| mite \| nematode \| rodent \| bird \| mollusc`), context (`field \| storage \| both`) | Storage pests use `context: storage` |
| `Disease` | id, name\_en, pathogen, pathogen\_type (`fungus \| bacterium \| virus \| phytoplasma \| nematode`) |  |
| `Weed` | id, name\_en, scientific\_name, weed\_type (`grass \| sedge \| broadleaf`) |  |
| `Disorder` | id, name\_en, kind (`deficiency \| toxicity \| physiological`) | `-[:INVOLVES]->Nutrient` |
| `Symptom` | id, description\_en, plant\_part, stage\_hint | `-[:SYMPTOM_OF]->Pest \| Disease \| Disorder` (diagnosis) |
| `ActiveIngredient` | id, name\_en, use\_class (`insecticide \| fungicide \| herbicide \| nematicide \| rodenticide \| PGR`), reg\_status (`registered \| restricted \| banned \| unknown`) | reg\_status comes from the official registration list, never from books |
| `Fertilizer` | id, name\_en, n\_pct, p2o5\_pct, k2o\_pct, other{} | Lets code turn "50 kg N" into kg of urea |
| `OrganicInput` | id, name\_en, kind (`fym \| compost \| green_manure \| biofertilizer \| press_mud \| other`) |  |
| `Nutrient` | id (`N, P2O5, K2O, S, Zn, Fe, B, …`) |  |
| `OperationType` | id (`sowing, transplanting, irrigation, fertilizer_application, spraying, seed_treatment, weeding, harvest, threshing, drying, storage`) |  |
| `Country`, `State`, `District` | id, name, level (Country 1, State 2, District 4) | `District-[:IN_STATE]->State-[:IN_COUNTRY]->Country` |
| `AgroClimaticZone` | id, name, scheme (`state_book \| icar_acz`), state\_id, level 3 | `District-[:IN_ZONE {scheme}]->AgroClimaticZone` |
| `Season` | id (`kharif \| rabi \| zaid \| summer \| perennial`) |  |
| `LocalSeason` | id, name (e.g. Samba, Kuruvai), state\_id, start\_month, end\_month | `-[:MAPS_TO]->Season`; how the current month becomes a season |
| `ProductionSystem` | id (`irrigated, rainfed, transplanted, wet_dsr, dry_dsr, nursery, garden_land, wetland, sri, …`) |  |
| `SoilType` | id (`clay, sandy, loam, red, black, alluvial, saline, sodic, acidic, …`) |  |
| `Purpose` | id (`grain, seed, fodder, green_manure`) | Grain and seed have different drying and storage targets |

## Regions, seasons and scope

Scope is resolved once, at load time, and stored as real `IN_REGION` edges; queries only read edges and never infer scope.

**Resolution order.** The most specific statement wins:

| Layer | Example | Rule |
| --- | --- | --- |
| Text | "In Thanjavur district only" | Overrides section and source |
| Section | A chapter written for one zone | Overrides the source default; set in the source registry |
| Source | TNAU guide → Tamil Nadu | Default for everything in the book |

Each edge records where its scope came from: `(r)-[:IN_REGION {origin: "text" | "section" | "source"}]->(region)`. The loader rejects any recommendation with no `IN_REGION` edge.

**Region rules.**

- Region nodes carry `level`: District 4, Zone 3, State 2, Country 1. Ranking uses the level of the best match.
- Zones from different states are separate schemes and are never matched against each other. A farmer is matched only to zones in their own state's scheme (`scheme: icar_acz` is the only cross-state zone scheme).
- `LocalSeason` always carries `state_id`, so a Samba window never reaches a farmer outside Tamil Nadu.
- The farmer's month maps to a season through `LocalSeason` start and end months for their state.

**Cross-state policy.** When the farmer's own state has no matching fact, some subtypes may fall back to another state's source. Wrong extra caution is cheap and a wrong action is harmful, so cautions cross freely and actions do not.

| Subtype | Use across states? | Answer label |
| --- | --- | --- |
| `QualitySpec`, `Caution`, `ActiveIngredient.reg_status` | Yes | None (national regulation, or a cheap warning) |
| `DryingSpec`, `StorageRule`, `PestThreshold`, `HarvestRule` | Fallback only | "From a \<state> source" shown with the answer |
| `VarietyRecommendation`, `SowingWindow`, `NutrientDose`, `DoseFormula`, `Spacing`, `SeedRate`, `IrrigationRule`, `SeedTreatment`, `ControlMeasure`, `WeatherRule` | Never | "No local guidance available" |

Query tiers: farmer's district → zone → state → national → allowed cross-state fallback → "no local guidance".

## Recommendation core

Every fact is `(:Recommendation:<Subtype>)` with the same core properties, applicability edges, ordered Steps and runtime Conditions.

**Core properties.**

```
(:Recommendation:<Subtype> {
   id, subtype,
   fact_key,              // source + section path + subtype + applicability + step slot; values excluded
   summary_en,            // one plain line; embedded for vector search
   duration_group,        // optional: short | medium | long
   status,                // extracted | auto_verified | needs_review | approved | rejected
   extraction_model, verifier, verifier_score, reviewed_by,
   unmapped,              // source phrases the schema has no slot for, kept for review
   missing_in_latest_run, // approved fact absent from the newest extraction run
   valid_from, superseded_by, created_at
})
(:Recommendation)-[:REVISION_OF]->(:Recommendation)   // a re-extraction changed its values
```

**Applicability edges** answer "does this fact apply to this farmer at all?". `IN_REGION` is required; the others are optional, and a missing optional edge matches anything. When several edges of the same kind exist, they are alternatives: at least one must match.

| Edge | To | Required |
| --- | --- | --- |
| `FOR_CROP` | Crop | Yes |
| `IN_REGION` | Country \| State \| AgroClimaticZone \| District | Yes, resolved at load time |
| `FOR_VARIETY` | Variety | No |
| `IN_SEASON` | Season \| LocalSeason | No |
| `UNDER_SYSTEM` | ProductionSystem | No |
| `ON_SOIL` | SoilType | No |
| `FOR_PURPOSE` | Purpose | No |
| `AT_STAGE` | GrowthStage | No |

**Steps** are the ordered actions a fact prescribes. Steps with the same `order` and `alt_group` are alternatives ("do one of these"); alt\_priority marks which is preferred (1) and which is a fallback (2).

```
(:Recommendation)-[:HAS_STEP]->(:Step {
   order, alt_group, alt_option,
   alt_priority,              // 1 = preferred, 2 = fallback ("if DAP is not readily available")
   condition_raw,             // the source words that make the step a fallback or conditional
   operation,                 // OperationType id
   method,                    // "broadcast", "foliar spray", "shade drying", "AWD"...
   anchor,                    // sowing | transplanting | PI | flowering | harvest | last_puddling
                              // | pulling_out | calendar | storage_start
   offset_min, offset_max,    // days relative to anchor; negative = before
   stage_id,                  // or a growth stage instead of days
   month_start, month_end,    // for calendar anchors
   timing_raw, instruction_en
})
```

**Quantities sit on the `APPLIES` edge** from a Step to what it applies, so "50 kg N per ha" is one edge.

```
(:Step)-[:APPLIES { value, min, max, unit, basis, formulation, water_l_per_ha, raw,
                    basis_inferred,   // basis not stated in the text; always reviewed
                    area_cents,       // source area when the dose is given per nursery area
                    quantity_ref,     // "previous": the amount was stated in an earlier bullet
                    inherited         // true once code copied that amount from the sibling fact
                  }]->
       (:Nutrient | :Fertilizer | :OrganicInput | :ActiveIngredient)
```

**Conditions** are runtime checks evaluated against the farm context and live data. Conditions sharing an `any_of_group` are OR'd; different groups are AND'd. Extraction must normalise every rule into this form, and the validator rejects anything else.

```
(:Recommendation | :Step | :ThresholdClause)-[:WHEN]->(:Condition {
   variable, op, value, value_max, unit, any_of_group, raw
})
// op: < <= > >= == != in between
```

Condition variables come from a fixed registry (see "Answering a question"), for example `forecast_rain_mm_24h`, `tmax_c`, `das`, `grain_moisture_pct`, `storage_months`, `soil_N_rating`, `soil_pH`, `pest_count`, `spider_count_per_hill`. Counts stay numeric: "spider present at 1/hill" is `spider_count_per_hill >= 1`, not a boolean.

Whole alternative strategies (e.g. transplanted vs direct-seeded rice) link with `(:Recommendation)-[:ALTERNATIVE_TO]->(:Recommendation)`.

## Recommendation subtypes

There are 16 subtypes. Each adds only the fields below to the core; the question numbers refer to the competency questions.

| Subtype | Extra fields and edges | Questions |
| --- | --- | --- |
| `VarietyRecommendation` | `-[:RECOMMENDS]->Variety`, note | 1 |
| `SowingWindow` | start\_month, start\_day, end\_month, end\_day | 2 |
| `SeedRate` | Step `APPLIES` (kg per\_ha), method | 3 |
| `Spacing` | row\_cm, plant\_cm, hills\_per\_m2, seedlings\_per\_hill | 3 |
| `SeedTreatment` | Steps applying an agent `per_kg_seed` | 3 |
| `NutrientDose` | dose\_basis (`blanket \| soil_test \| lcc`); ordered Steps, each with its own timing and `APPLIES` quantities; total = sum of Steps | 4, 6 |
| `DoseFormula` | target\_nutrient, coefficients {T, SN, SP, SK, ON, OP, OK}, target\_yield\_unit, soil\_series, valid\_range | 5 |
| `IrrigationRule` | depth\_cm, criterion (e.g. "hairline cracks"), timing via Steps | 6 |
| `PestThreshold` | `-[:FOR_PEST]->Pest \| Disease`, `-[:HAS_CLAUSE]->ThresholdClause {observation, value, unit, sampling_unit, stage_id, any_of_group}` | 8 |
| `ControlMeasure` | control\_class (`cultural \| mechanical \| biological \| chemical \| physical`), `-[:TARGETS]->Pest \| Disease \| Weed \| Disorder`, Steps with `APPLIES` | 9, 18 |
| `WeatherRule` | operation, advice (`avoid \| delay \| do \| protect`), Conditions on weather variables | 10, 11, 13 |
| `HarvestRule` | maturity\_signs\[\], harvest\_moisture\_pct\_min/max, threshing\_moisture\_pct\_min/max, day window via Steps | 12, 13, 14 |
| `DryingSpec` | target\_moisture\_pct\_min/max, storage\_months\_min/max, storage\_term\_raw, method | 15, 16 |
| `StorageRule` | storage\_months\_min/max, max\_moisture\_pct, structure, protectant Steps, `-[:TARGETS]->Pest {context: storage}` | 17, 18 |
| `QualitySpec` | Regulatory: authority, valid\_for\_season, parameter (`moisture \| foreign_matter \| damaged \| …`), limit\_value, unit | 19 |
| `Caution` | kind (`prohibition \| safety \| incompatibility \| banned \| waiting_period`), text\_en, `-[:CONCERNS]->ActiveIngredient` | 9, 10, 20 |
| `WeedControl` | Not a separate subtype: a `ControlMeasure` whose `TARGETS` edge points at a Weed | — |

Storage is described in months, not words. When a source gives only "short term" or "long term" without months, `storage_months_min/max` stay null and the bot asks or branches; it never guesses a mapping. `QualitySpec` values come from the current government procurement notice, not from books, and are re-checked every season.

## Provenance, sources and conflicts

Every recommendation and every variety record points to the exact source text it came from, and every book is registered by hand before extraction.

```
(:Recommendation | :Variety)-[:EVIDENCED_BY]->(:SourceSpan {
   id, page, bbox,
   section_path,          // "Rice > 1.8 Main field > 1.8.6 Irrigation management"
   quote,                 // exact source text
   table_ref,             // Docling JSON pointer, e.g. "#/tables/12"
   extraction_method      // native_text | ocr | table_parse
})-[:IN_SOURCE]->(:Source {
   id, title, publisher, edition_year, language, url, sha256,
   state_id, region_scope, authority_tier, default_scope
})
(:Source)-[:SUPERSEDES]->(:Source)      // newer edition of the same book
```

**Source registry.** A small hand-written file per book, filled in before extraction (a few minutes per book):

| Field | Meaning | Example |
| --- | --- | --- |
| `state_id` | Whose book it is | `state:tn` |
| `region_scope` | States or zones it is written for | `[state:tn]` |
| `authority_tier` | 1 = state agricultural university package of practices; 2 = ICAR national guidance; 3 = other | 1 |
| `edition_year` | Year of the edition | 2020 |
| `default_scope` | Book-wide rules | `dose basis = per_ha unless stated` |
| Section overrides | Section path → region | A zone-specific chapter → that zone |

**Conflicts.** At load time, any two recommendations with the same subtype and applicability but different values are linked with `(:Recommendation)-[:CONFLICTS_WITH]->(:Recommendation)` and set to `needs_review`. Conflicts are never merged; this catches contradictions between books and inside one book.

**Review fields.** `status`, `verifier`, `verifier_score` and `reviewed_by` record what the code checks, the Jev gate and human reviewers decided. A superseded fact sets `superseded_by` and is excluded from answers.

**Revisions.** Re-extracting a section never deletes reviewed work. Old and new facts are matched by `fact_key` (source, section path, subtype, applicability, step slot; values excluded):

| Case | Action |
| --- | --- |
| Same values | Keep the node and its status, including `approved` |
| Different values | New node `(:new)-[:REVISION_OF]->(:old)` set to `needs_review`; the old approved fact keeps serving until the new one is approved |
| Approved fact missing from the new run | Never deleted; flagged `missing_in_latest_run` for review (usually a recall drop in the new prompt) |

`superseded_by` is reserved for a newer edition of a source; `REVISION_OF` is for re-extraction of the same edition.

## Answering a question

The agent builds a farm context, picks one of about 20 parameterised query templates, and ranks the facts that come back; the LLM never writes graph queries from scratch.

**Farm context.** Built at question time and never stored in the graph:

```json
{
  "district": "district:<lgd>", "zones": ["zone:..."], "state": "state:...",
  "month": 11, "local_seasons": ["season_local:samba"], "season": "rabi",
  "crop": "crop:rice", "variety": "variety:adt53", "duration_group": "medium",
  "sowing_date": "2026-09-10", "das": 70, "stage": "stage:rice_flowering",
  "soil": {"N": "low", "P": "medium", "K": "high", "pH": 8.2},
  "forecast": {"rain_mm_24h": 18, "rain_days_3d": 2, "tmax_c": 34},
  "purpose": "grain", "storage_months": 3
}
```

**Flow.**

1. Link the farmer's words to concepts (full-text and vector search on `Label`).
2. Pick the template (a Choice over the template list; Jev or the LLM, run on the English translation).
3. Fill its slots from the farm context: district → zones and state, month → season, sowing date → days after sowing and stage.
4. Run the template; evaluate Conditions; rank; join safety information.
5. The LLM writes the answer from the returned facts and quotes, in the farmer's language.

**Ranking.** Results are compared on the first key, then the next only if tied:

1. Region level of the best matching region (District 4 → Country 1)
2. Variety match (specific to the farmer's variety beats crop-level)
3. Explicit matches on season, system, soil and purpose (explicit match beats wildcard)
4. `authority_tier` (lower is better)
5. `edition_year` (newer is better)

Superseded and rejected facts are excluded. If several facts tie on all five keys and give different values, the answer shows the disagreement with both sources. There is no `LIMIT`: the app takes the top-ranked group.

**Missing data: three-valued logic.** Every condition evaluates to TRUE, FALSE or UNKNOWN (value missing from the farm context). FALSE AND UNKNOWN = FALSE, TRUE OR UNKNOWN = TRUE, anything else involving UNKNOWN stays UNKNOWN. Each condition variable has one `on_unknown` policy:

| Variables | on\_unknown |
| --- | --- |
| soil ratings and values, sowing\_date / das, variety, purpose, storage\_months | Ask the farmer; if they do not know, branch ("if your soil N is low… otherwise…") |
| forecast variables (weather call failed) | Conservative: Cautions and "avoid" WeatherRules fire; say the forecast is unavailable |
| pest\_count, spider\_count\_per\_hill | Ask ("how many hoppers per tiller?") |

Safety rule: an UNKNOWN condition lets a Caution fire and withholds an action. Evaluation is top-down: Recommendation conditions, then Step conditions, then ThresholdClause conditions. FALSE at a parent prunes its children; UNKNOWN at a parent passes its policy down.

**Safety joins.** Any template that returns `ControlMeasure`, `SeedTreatment` or `StorageRule` must:

- always join the related `Caution` nodes;
- drop any step whose `APPLIES` points to an ingredient with `reg_status = "banned"`;
- attach a caution to any step whose ingredient is `restricted`.

If no fact matches, the bot says it has no guidance. It never lets the LLM fill the gap, especially for chemical questions.

**Unreviewed facts.** What farmers see while a fact is still `needs_review` (decided):

| Fact type | While unreviewed |
| --- | --- |
| Chemical doses; anything with an inferred basis or inherited quantity; banned or restricted ingredients | Hidden: the bot says it has no verified guidance |
| Fertiliser doses with explicit units | Hidden |
| Descriptive facts: maturity signs, storage structures, drying targets with explicit values | Shown, marked "not yet verified by an expert" |

**Example template: `drying_target`.**

```cypher
// $region_ids = farmer's district + zones (own state scheme) + state + 'country:in'
MATCH (r:Recommendation:DryingSpec)-[:FOR_CROP]->(:Crop {id:$crop})
WHERE r.status IN ['approved','auto_verified'] AND r.superseded_by IS NULL
  AND EXISTS { (r)-[:IN_REGION]->(g) WHERE g.id IN $region_ids }
  AND (NOT EXISTS { (r)-[:FOR_PURPOSE]->() }
       OR EXISTS { (r)-[:FOR_PURPOSE]->(p) WHERE p.id = $purpose })
  AND ($storage_months IS NULL                       // UNKNOWN: keep all, app asks or branches
       OR ((r.storage_months_min IS NULL OR r.storage_months_min <= $storage_months)
       AND (r.storage_months_max IS NULL OR $storage_months <= r.storage_months_max)))
MATCH (r)-[:EVIDENCED_BY]->(s:SourceSpan)-[:IN_SOURCE]->(src:Source)
WITH r, s, src,
     reduce(m = 0, x IN [(r)-[:IN_REGION]->(g) WHERE g.id IN $region_ids | g.level] |
            CASE WHEN x > m THEN x ELSE m END)                     AS region_level,
     CASE WHEN EXISTS { (r)-[:FOR_PURPOSE]->() } THEN 1 ELSE 0 END AS purpose_explicit
RETURN r, s.quote, s.page, src.title, region_level, purpose_explicit,
       src.authority_tier, src.edition_year,
       [(r)-[:CONFLICTS_WITH]-(c) | c.id] AS conflicts
ORDER BY region_level DESC, purpose_explicit DESC, src.authority_tier ASC, src.edition_year DESC
```

If the farmer's state returns nothing, a second query runs only for subtypes allowed to cross state lines, and its answers carry the source-state label.

## Multilingual layer and indexes

Facts stay in English; every concept collects names in other languages as `Label` nodes, and embeddings live on labels and summaries for matching only.

```
(:Label { text, lang, script, kind, embedding })-[:LABEL_OF]->(any concept)
// kind: canonical | alias | vernacular | transliteration | abbreviation
// "धान" (hi), "நெல்" (ta), "paddy", "dhaan" → crop:rice
// "BPH" → pest:brown_planthopper
```

| Index | On | Purpose |
| --- | --- | --- |
| Unique constraint | `id` of every label | No duplicates; all loads use `MERGE` |
| Full-text | `Label.text` | Exact codes and names: "ADT 53", "BPH", "Carbendazim" |
| Vector | `Label.embedding` | A word in any Indian language finds the right concept |
| Vector | `Recommendation` summary embedding | Fallback search when no template fits |

Starting embedding model: BGE-M3 (multilingual, dense plus sparse). AGROVOC concept IDs can be stored as `agrovoc_uri` where they exist, but AGROVOC has Indian-language labels only for Hindi and Telugu, so most labels must be built by the team. Neo4j 2026.09 creates vector indexes with rescored binary quantisation by default; check the release notes for the version you deploy.

## Build pipeline

No fact reaches the graph as `approved` without passing code checks, an independent classifier gate and, for anything uncertain, a human reviewer.

1. **Register the source** (by hand, about 10 minutes per book): state, authority tier, edition, book-wide default rules, section scopes.
2. **Convert.** Docling turns the PDF into lossless JSON: text, headings, tables, page and position. Legacy-font and image-only pages are OCR'd. Local, no LLM.
3. **Segment.** One extraction unit per section: heading path, text, tables, pages, section scope. Never fixed-size chunks, because bullets refer back to each other ("for that situation").
4. **Parse and check tables in code.** Stitch tables across pages and pivot variety tables, then compare each table's header and row count against the page before trusting it. Variety rows become Variety records without an LLM.
5. **Extract.** One LLM call per unit returns a list of facts in the Pydantic models, each value with its raw text and a quote. Guesses are flagged (`basis_inferred`), phrases with no slot go to `unmapped`, an amount stated in an earlier bullet is marked `quantity_ref` rather than invented, and fallbacks get `alt_priority` 2.
6. **Normalise and link (code).** Units and bases to canonical form; ranges to min/max; names to concept IDs by exact, alias, then embedding lookup, else a proposed new concept for review. `quantity_ref` is resolved to the sibling fact in the same section with `inherited: true`; an ambiguous reference goes to review.
7. **Validate (code).** Nothing is auto-corrected.
   - Quote: normalise the quote and the unit's text the same way (whitespace, dash characters, soft hyphens, ligatures), then require an exact match against the text the LLM was given.
   - Numbers: every raw number in a fact, including words ("one tonne") and fractions, must appear in its quote. Normalised values are not checked here.
   - Vocabulary, value ranges, normalised condition form; every active ingredient against the official banned and restricted list.
   - Alternatives: in an `alt_group` whose options are all fertilisers, nutrient totals per option must agree within about 15%, else flag.
8. **Verify with Jev 1.14.** Code builds the claims from the stored fields, one per step and value (for example "DAP, 40 kg, before last puddling, seedlings 20–25 days"); the LLM never writes them. The `auto_verified` cut-off is set by measuring precision on the gold set.
9. **Load (code).** Resolve scope edges, merge by `fact_key` under the revision rules, then add conflict links, embeddings and indexes, and run the 20 competency questions.

**Review queue.** Ordered by risk: chemical doses and banned or restricted ingredients first, fertiliser doses next, descriptive facts last.

**Measurement.** Precision and recall per subtype, against a small set of sections annotated by a person who has not seen any model output. Both Claude's and Sarvam's extractions are scored against that set.

**Hand-run first.** Rice wet-nursery nutrients, brown planthopper threshold and control, and rice harvest → drying → storage, before any bulk run.

**Alternatives check, worked.** The rice nursery section offers 40 kg DAP, or as a fallback 16 kg urea + 120 kg super phosphate. DAP gives 7.2 kg N and 18.4 kg P₂O₅; the fallback gives 7.4 kg N and 19.2 kg P₂O₅, so the check passes.

Jev facts: hosted only (TypeSafe); text in, probabilities out; about $0.042 per million input tokens, output free; English is its strongest language. Checking 20,000 claims at about 2,000 tokens each costs roughly $1.70.

## Competency questions

These 20 questions are the schema's test set: each maps to one template, and every slot must exist in the schema.

| # | Stage | Farmer question | Template | Facts used |
| --- | --- | --- | --- | --- |
| 1 | Before sowing | Which paddy variety should I sow this season in my district? | `varieties_for` | VarietyRecommendation, Variety |
| 2 | Before sowing | When should I sow? | `sowing_window` | SowingWindow |
| 3 | Before sowing | How much seed per acre, and what seed treatment? | `seed_rate_treatment` | SeedRate, SeedTreatment (acre ↔ ha in code) |
| 4 | Nutrients | What fertiliser, and when? | `nutrient_schedule` | NutrientDose → Steps |
| 5 | Nutrients | My soil card says N low and pH 8.2. Should I change the dose? | `nutrient_adjust` | NutrientDose with soil Conditions, DoseFormula |
| 6 | Nutrients | I'm at 20 days after transplanting. What should I apply now? | `stage_actions` | Steps whose timing matches the farmer's day count |
| 7 | Protection | Leaves have yellow-orange tips. What is it? | `diagnose` | Symptom → Pest, Disease, Disorder |
| 8 | Protection | When is brown planthopper bad enough to spray? | `threshold` | PestThreshold |
| 9 | Protection | How do I control it, and what must I avoid? | `control` | ControlMeasure, Caution |
| 10 | Weather | Rain tomorrow. Should I spray or apply urea today? | `weather_check` | WeatherRule, Caution |
| 11 | Weather | It's very hot at flowering. Anything to do? | `weather_check` | WeatherRule |
| 12 | Harvest | How do I know my paddy is ready? | `harvest_readiness` | HarvestRule |
| 13 | Harvest | Rain is due in 3 days. Should I harvest now? | `harvest_vs_weather` | HarvestRule, WeatherRule |
| 14 | Harvest | At what moisture should I thresh? | `harvest_readiness` | HarvestRule threshing moisture |
| 15 | Post-harvest | To what moisture should I dry paddy before selling? | `drying_target` | DryingSpec, QualitySpec |
| 16 | Post-harvest | I'm keeping some as seed for next season. How dry? | `drying_target` | DryingSpec (purpose = seed) |
| 17 | Post-harvest | How do I store wheat for 3 months without weevils? | `storage` | StorageRule, storage Pest, ControlMeasure |
| 18 | Post-harvest | I see moths in my stored rice. What do I do? | `control` | Storage Pest → ControlMeasure, Caution |
| 19 | Post-harvest | Will the mandi accept my paddy at 18% moisture? | `quality_check` | QualitySpec (current season) |
| 20 | Safety | Can I mix this insecticide with this fungicide? | `caution` | Caution; abstain if no fact |

The list should grow with real questions from farmers, a KVK, or Kisan Call Centre transcripts; any question that no template can answer shows a gap in the schema.

## Worked examples

The values below come from the rice chapter of the TNAU Crop Production Guide 2020; page numbers are filled in at extraction. All three examples carry `IN_REGION {origin:"source"}` → `state:tn`.

**1. Brown planthopper threshold.** Source text: "1 hopper/tiller in the absence of predatory spider and 2 hoppers/tiller when spider is present at 1/hill".

```
(:Recommendation:PestThreshold {summary_en:"BPH: act at 1/tiller, or 2/tiller if spiders >= 1/hill"})
   -[:FOR_CROP]->(crop:rice)   -[:FOR_PEST]->(pest:brown_planthopper)
   -[:HAS_CLAUSE]->(:ThresholdClause {observation:"hoppers", value:1, unit:"count", sampling_unit:"per_tiller"})
        -[:WHEN]->(:Condition {variable:"spider_count_per_hill", op:"<", value:1})
   -[:HAS_CLAUSE]->(:ThresholdClause {observation:"hoppers", value:2, unit:"count", sampling_unit:"per_tiller"})
        -[:WHEN]->(:Condition {variable:"spider_count_per_hill", op:">=", value:1})
   -[:EVIDENCED_BY]->(:SourceSpan {quote:"1 hopper/ tiller in the absence of predatory spider..."})
```

If the farmer has not counted spiders, `spider_count_per_hill` is UNKNOWN and the bot asks.

**2. Rice seed storage, and a conflict inside the book.** The storage section gives three month ranges; the drying section, half a page earlier, calls 8–9% "long term".

```
StorageRule {storage_months_min:0,  storage_months_max:9,    max_moisture_pct:13, structure:"gunny or cloth bag"}
StorageRule {storage_months_min:12, storage_months_max:15,   max_moisture_pct:9,  structure:"polylined gunny bag"}
StorageRule {storage_months_min:15, storage_months_max:null, max_moisture_pct:8,  structure:"700 gauge polythene bag"}
   (all three: FOR_PURPOSE → purpose:seed)

DryingSpec  {storage_term_raw:"long term", target_moisture_pct_min:8, target_moisture_pct_max:9}
   -[:CONFLICTS_WITH]-> StorageRule (>15 months, <8%)          → status: needs_review
```

The book leaves a gap between 9 and 12 months; a farmer storing for 10 months gets a question back, not a guess.

**3. Grain vs seed drying.** "Dry the grains to 12% moisture level for storage" and "Dry the seeds to 12–13% moisture content for short term storage" become two separate DryingSpec nodes, one with `FOR_PURPOSE → purpose:grain` and one with `FOR_PURPOSE → purpose:seed`, so question 15 and question 16 get different answers.

## Deferred and open decisions

The first build covers one slice; the rest is deliberately left out until the slice passes its questions.

**First slice.**

- Crops: paddy and wheat.
- Concepts: Crop, Variety, region nodes, Season and LocalSeason, Pest, Disease, ActiveIngredient.
- Subtypes: VarietyRecommendation, SowingWindow, NutrientDose, PestThreshold, ControlMeasure, HarvestRule, DryingSpec, StorageRule, Caution.
- Value objects: Step quantities and timing, Condition, SourceSpan.

**Deferred.** BBCH growth-stage codes, an `Implement` node, separate brand-level `Product` nodes (formulation stays on the `APPLIES` edge), and the cross-cutting chapters (composting, agromet, machinery, mushroom), which stay as plain text chunks for retrieval.

**Never in the graph.** Weather and forecasts, mandi prices and MSP, farmer profiles and soil-test values. These are tools and data stores the agent calls.

**Open decisions.**

- [ ] Wheat source: the TNAU guide has only 3 pages on wheat; a second book is needed.
- [ ] Pilot region and its tier-1 books, entered in the source registry.
- [ ] Reviewer for pesticide doses and other `needs_review` facts.
- [ ] Jev thresholds, set on a hand-checked gold set from the first slice.
- [ ] Confirm the procurement moisture limits for `QualitySpec` from the current season's notice.

## Sources

- [TNAU Crop Production Guide — Agriculture 2020](https://agritech.tnau.ac.in/pdf/AGRICULTURE.pdf) (examples and patterns)
- [TypeSafe model docs — Jev 1.14](https://docs.typesafe.ai/models)
- [TypeSafe docs — confidence and outputs](https://docs.typesafe.ai/confidence)
- [Akita — comparison of Jev-like decision models](https://akitaonrails.com/en/2026/10/10/which-jev-like-ai-decision-classifier-model-is-best/)
- [Neo4j — navigating a knowledge graph with Jev](https://neo4j.com/blog/genai/navigating-a-neo4j-knowledge-graph-with-jev/)
- [Neo4j — rescored binary vector search](https://neo4j.com/blog/developer/rescored-binary-vector-search-in-neo4j-search-more-with-less-memory/)
- [FAO AGROVOC](https://agrovoc.fao.org)
