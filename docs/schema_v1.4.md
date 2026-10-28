# CropBot Knowledge Graph Schema (v1.4)

Oct 2026 · @Shivaansh Gusain · v1.4 folds in what evaluation, the gold set and the expert-review preparation (steps 15–16) taught us; see "Changes from v1.3" at the end.

Every agronomic fact is stored as its own Recommendation node: where and when it applies, the runtime conditions it depends on, the ordered steps it prescribes, and the exact source text it came from. The bot can then answer only with facts that apply to this farmer, and cite them.

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
| Node ID | `<type>:<slug>`, prefixed and lowercase everywhere, unique per label, including closed-list concepts | `crop:rice`, `variety:adt_53`, `pest:brown_planthopper`, `ai:chlorantraniliprole`, `season:rabi`, `nutrient:p2o5` |
| Region ID | Official LGD code for states and districts | `district:<lgd_code>`, `state:33` (Tamil Nadu), `country:in` |
| Zone ID | State scheme prefix + slug | `zone:tn_cauvery_delta` |
| Variety ID | Slug of the name as written in the source; spellings are never merged in code | "ADT 53" → `variety:adt_53` |
| Canonical name | `name_en` on every concept; other names are `Label` nodes | `name_en: "Brown planthopper"` |
| Units | `kg, g, t, l, ml, cm, m, days, months, pct, count`; in Conditions only, also `mm` and `degC` | Code converts acre, cent and quintal; the LLM never converts units |
| Basis | `per_ha, per_kg_seed, per_l_water, per_m2, per_hill, per_tiller, per_cent_nursery, per_plant, absolute` | "40 kg DAP per 20 cents of nursery" = basis `per_cent_nursery` |
| Raw text | Every number keeps its source text: `raw` on APPLIES (the whole quantity phrase), Condition and ThresholdClause; a `raw_<field>` property on subtypes and Variety for every non-null numeric field | `raw: "150 ml"`; `raw_target_moisture_pct_max: "12 - 13 %"` |
| Strict bounds | Every bound has a `<field>_inclusive` flag, default true | "less than 8 %" = `max_moisture_pct: 8, max_moisture_pct_inclusive: false` |
| Loading | Always `MERGE` on `id`, never `CREATE` | Re-loading a book never duplicates nodes |
| Properties | Primitives or lists of primitives only, never maps. Field maps become flat properties (`raw_<field>`, `coef_<name>`); opaque provenance becomes one JSON string (`cells_json`); nutrient content becomes edges | `(:Fertilizer)-[:CONTAINS {pct, raw}]->(:Nutrient)` |
| Concentration | Solution strengths sit on `APPLIES`, beside the dose or alone when no dose is printed ("1% KCl solution", "basal (50%)"): `conc_value`/`conc_min`/`conc_max`, `conc_unit` (`pct \| normal \| micromolar`), `conc_raw`; ratios as `ratio_part`, `ratio_whole`, `ratio_raw` | "1 % KCl" = `conc_value: 1, conc_unit: pct`; "1 part … 49 parts" = `ratio_part: 1, ratio_whole: 50` |

1 cent = 40.47 m² = 1/100 acre. A rule such as "doses are per ha unless otherwise specified" is a `default_scope` rule on the Source. `default_scope` is a list; each rule may be limited to one section, and only rules approved in the source registry are applied at extraction time.

## Concept nodes

Concepts are the stable things facts talk about. All of them also carry the shared label `:Concept` for the vector index.

Every concept and Label carries `review_status` (`approved | needs_review`) and `source` (where its values came from). Concepts are seeded by hand; the only ones created by code are Variety records pivoted from tables. Linking may use a `needs_review` concept, but any fact linked to one is itself `needs_review`.

| Label | Key properties | Edges and notes |
| --- | --- | --- |
| `Crop` | id, name\_en, scientific\_name, crop\_group (`cereal \| millet \| pulse \| oilseed \| fibre \| sugar \| forage \| vegetable \| fruit`) | Root of every fact |
| `Variety` | id, name\_en, name (as printed), kind (`variety \| hybrid`), release\_year, parentage, duration\_days\_min/max, duration\_group (`short \| medium \| long`), avg\_yield\_kg\_ha, grain\_type, traits\[\], `raw_<field>`, `cells_json` (per value: table\_ref, row, col, pages, cell text; opaque, never queried) | `-[:VARIETY_OF]->Crop`, `-[:EVIDENCED_BY]->SourceSpan`. Pivoted from tables in code, always `needs_review` until approved |
| `GrowthStage` | id, crop\_id, name\_en, code (e.g. `PI`), order | `-[:TYPICAL_TIMING {duration_group, anchor, day_min, day_max}]->Crop` turns a sowing date into a stage |
| `Pest` | id, name\_en, scientific\_name, pest\_type (`insect \| mite \| nematode \| rodent \| bird \| mollusc`), context (`field \| storage \| both`) | Storage pests use `context: storage` |
| `Disease` | id, name\_en, pathogen, pathogen\_type (`fungus \| bacterium \| virus \| phytoplasma \| nematode`) |  |
| `Weed` | id, name\_en, scientific\_name, weed\_type (`grass \| sedge \| broadleaf`) |  |
| `Disorder` | id, name\_en, kind (`deficiency \| toxicity \| physiological`) | `-[:INVOLVES]->Nutrient` |
| `Symptom` | id, description\_en, plant\_part, stage\_hint | `-[:SYMPTOM_OF]->Pest \| Disease \| Disorder` (diagnosis) |
| `ActiveIngredient` | id, name\_en, use\_class (`insecticide \| acaricide \| fungicide \| herbicide \| nematicide \| rodenticide \| PGR \| biopesticide`, optional), reg\_status (`registered \| restricted \| banned \| unknown`) | reg\_status comes from the official registration list, never from books. `-[:MEMBER_OF]->AIGroup` |
| `AIGroup` | id (`ai_group:` prefix), name\_en (e.g. "synthetic pyrethroids") | A chemical class a book names as a whole; Cautions may concern a group |
| `Fertilizer` | id, name\_en, n\_pct, p2o5\_pct, k2o\_pct (all optional: blank means no sourced grade) | Other nutrients as `-[:CONTAINS {pct, raw}]->Nutrient`. Lets code turn "50 kg N" into kg of urea; the alternatives check uses approved percentages only |
| `OrganicInput` | id, name\_en, kind (`fym \| compost \| green_manure \| biofertilizer \| press_mud \| other`) |  |
| `Input` | id, name\_en, kind (`seed \| bioagent \| trap \| device \| salt \| chemical \| botanical \| amendment \| other`) | Anything applied that is not a nutrient, fertiliser, organic input or pesticide ingredient: seed, Trichogramma, traps, common salt, nitric acid, gypsum (`amendment`), plain leaf extracts (`botanical`). Identity follows the substance, not the use: KCl (muriate of potash) and KNO3 (potassium nitrate) are Fertilizers even when used as seed-treatment solutions; a botanical sold as a pesticide product (neem seed kernel extract, neem oil, azadirachtin) is an ActiveIngredient. `input:` prefix |
| `Nutrient` | id (`n, p2o5, k2o, s, zn, fe, b, …`) | IDs are prefixed: `nutrient:p2o5` |
| `OperationType` | id (`sowing, transplanting, irrigation, fertilizer_application, spraying, dusting, application, seed_treatment, weeding, release, trapping, baiting, bund_management, sanitation, harvest, threshing, drying, storage`) |  |
| `Country`, `State`, `District` | id, name\_en, level (Country 1, State 2, District 4) | `District-[:IN_STATE]->State-[:IN_COUNTRY]->Country` |
| `AgroClimaticZone` | id, name\_en, scheme (`state_book \| icar_acz`), state\_id, level 3 | `District-[:IN_ZONE {scheme}]->AgroClimaticZone` |
| `Season` | id (`kharif \| rabi \| zaid \| summer \| perennial`) |  |
| `LocalSeason` | id, name\_en (e.g. Samba, Kuruvai), state\_id, start\_month, end\_month | `-[:MAPS_TO]->Season`; how the current month becomes a season |
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

Each edge records where its scope came from: `(r)-[:IN_REGION {origin: "text" | "section" | "source" | "text_exclusion"}]->(region)`. The loader rejects any recommendation with no `IN_REGION` edge.

**Exclusions.** Text such as "rice growing tracts of Tamil Nadu (other than Cauvery Delta)" is extracted as `excluded_regions: [{id, raw}]` on the Recommendation. Code, never the LLM, expands it into `IN_REGION` edges to the state's remaining zones with `origin: "text_exclusion"`. A fact with an exclusion is `needs_review`, and an excluded region can never also be one of its regions. Sub-zones with no concept ("new delta") are not mapped: the fact is scoped to the state, the phrase goes to `unmapped`, and the fact is `needs_review`.

**Region rules.**

- Region nodes carry `level`: District 4, Zone 3, State 2, Country 1. Ranking uses the level of the best match.
- Zones from different states are separate schemes and are never matched against each other. A farmer is matched only to zones in their own state's scheme (`scheme: icar_acz` is the only cross-state zone scheme).
- `LocalSeason` always carries `state_id`, so a Samba window never reaches a farmer outside Tamil Nadu.
- The farmer's month maps to a season through `LocalSeason` start and end months for their state.

**Cross-state policy.** When the farmer's own state has no matching fact, some subtypes may fall back to another state's source (the table below is the rule). Wrong extra caution is cheap and a wrong action is harmful, so cautions cross freely and actions do not.

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
   fact_key,              // source + section path + subtype + applicability + conditions
                          //   + identity (pests, targets, kind, concerns, control class,
                          //     dose basis, storage term, ABOUT) + the quote's first passage ref
                          //   + step slots; values excluded. A step outside an alternative group
                          //   keeps [order, operation, method, anchor, targets]; an alternative
                          //   group is one slot [order, alt_group, "options"], so adding, removing
                          //   or renumbering an option changes value_key and id, never fact_key
   scope_in_unmapped,     // list: unmapped phrases that look like scope (check 10); see Visibility
   summary_en,            // one plain line; embedded for vector search
   duration_group,        // optional: short | medium | long
   status,                // extracted | auto_verified | needs_review | approved | rejected
   extraction_model, verifier, verifier_score,
   expert_decision, reviewed_by, reviewed_at, expert_note, applies_uttarakhand,  // from the expert decisions file
   unmapped,              // source phrases the schema has no slot for, kept for review
   extraction_flags,      // list: line_order_pairing, spans_table_rows, split_from_shared_line,
                          //   shared_amount, target_from_heading, anchor_from_context,
                          //   scope_from_heading, operation_from_formulation
   excluded_region_ids, excluded_region_raws,  // parallel lists from "other than …" text
   raw_<field>,           // source text of each numeric field (on every subtype)
   review_reasons,        // list of strings: why the fact is needs_review
   review_notes,          // list of approved reviewer notes ("suspected source typo …")
   verifier_claims, verifier_claim_p_yes, verifier_notes,  // parallel lists from the Jev gate
   conflict_key, value_key,  // value_key includes each option's operation, method, anchor,
                             //   target, formulation and amounts (sorted); conflict_key stays
                             //   per option, so the same product for the same pest still compares
   missing_in_latest_run, // fact absent from the newest extraction run
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
| `FOR_PURPOSE {origin}` | Purpose; `origin` is a list of `text` and/or `section` | No |
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
   offset_min, offset_max,    // relative to anchor; negative = before
   offset_unit,               // days (default) | hours | weeks: "18 to 24 hrs after sowing", "a week before harvest"
   offset_min_inclusive, offset_max_inclusive,
   stage_id,                  // or a growth stage instead of days
   month_start, month_end,    // for calendar anchors
   repeat_count, repeat_interval, repeat_interval_unit,  // "thrice at weekly interval"
   repeat_offsets,            // list of stated times for one option list ("15 and 30 DAT" = [15, 30])
   repeat_raw,
   duration_min, duration_max, duration_unit, duration_raw,  // how long: "soak for 12 - 16 h";
                              //   unit minutes | hours | days; one duration per step;
                              //   "overnight" stays in duration_raw with no number
   purpose_raw,               // why or to what end, copied verbatim ("adapting specific gravity grading",
                              //   "to escape monsoon rains"); shown in the instruction
   timing_raw,
   instruction_en             // written by code from the fields, never by the LLM
})
```

Repeated applications at stated times are separate Steps when the step is a single action; when an option list is applied at several stated times ("spray any one of the following twice, 15 and 30 DAT"), the step keeps one option list (the farmer chooses one product and applies it at every time): `offset_min/max` hold the first time, `repeat_offsets` lists every stated time in the step's `anchor` and `offset_unit` (`[15, 30]`), and `repeat_count` equals its length; a count with an interval ("thrice at weekly interval") uses the `repeat_*` fields, with `repeat_interval_unit` `days | weeks`; code reads count and interval words (once, twice, thrice; weekly, fortnightly) from a fixed table. `application` covers applying granules, biopesticides or treated material to soil or water; `sanitation` covers removing or destroying stubble, egg masses or collected insects. The LLM writes the operation of the printed verb; code then applies the formulation table: in a list introduced by "spray", D/DP options become `dusting` and G/GR/CG options become `application` (EC/WP/SC/WG/SG/SP/SL stay `spraying`); in a mixed "Dust/ spray" list, each option follows its code. A printed verb other than spray is never overridden ("Apply Beauveria bassiana 1.15 WP" stays `application`), and an option applied with a carrier, as a bait or as a seed treatment keeps its printed operation. An option with no code keeps the printed verb's operation, or none (held). A changed operation flags the fact `operation_from_formulation`.

**Quantities sit on the `APPLIES` edge** from a Step to what it applies, so "50 kg N per ha" is one edge. A dose is optional when the book gives only a strength, ratio or share. Seed-to-solution ratios use `ratio_part`/`ratio_whole` with `ratio_raw`: "at the ratio of 1 : 1" as printed, and "in equal volume" as 1:1 from the fixed word table (like "twice"). Ratios of more than two parts ("5:4:1") stay in `ratio_raw` or `unmapped`.

```
(:Step)-[:APPLIES { value, min, max, min_inclusive, max_inclusive, unit, basis, formulation, water_l_per_ha,
                    raw,              // the whole quantity phrase, incl. water and area
                    basis_inferred,   // basis not stated in the text; always reviewed
                    area_cents,       // source area when the dose is given per nursery area
                    quantity_ref,     // "previous": the amount was stated in an earlier bullet
                    inherited,        // true once code copied that amount from the sibling fact
                    conc_value, conc_min, conc_max, conc_unit, conc_raw,  // solution strength
                    ratio_part, ratio_whole, ratio_raw,                    // "1 part … 49 parts"
                    share_pct, share_raw,                                  // "basal (50%)": share of the total dose
                    mix_conc_value, mix_conc_unit, mix_conc_raw,           // strength in the prepared mix
                                                                           //   ("bromadiolone … at 0.005%")
                    carrier_raw                                            // what the input is applied with or on
                                                                           //   ("chopped paddy straw", "popped rice")
                  }]->
       (:Nutrient | :Fertilizer | :OrganicInput | :ActiveIngredient | :Input)
```

**Conditions** are runtime checks evaluated against the farm context and live data. Conditions sharing an `any_of_group` are OR'd; different groups are AND'd. Extraction must normalise every rule into this form, and the validator rejects anything else.

```
(:Recommendation | :Step | :ThresholdClause)-[:WHEN]->(:Condition {
   variable, op, value, value_max, unit, any_of_group, raw
})
// op: < <= > >= == != in between
// unit: the dose units, plus mm and degC (Conditions only)
```

Condition variables come from a fixed registry (see "Answering a question"), for example `forecast_rain_mm_24h`, `tmax_c`, `das`, `grain_moisture_pct`, `storage_months`, `soil_N_rating`, `soil_Zn_rating`, `soil_pH`, `pest_count`, `spider_count_per_hill`, `endemic_area` (value: the concept the area is known for, e.g. `disease:tungro`, `pest:bph`; ask, then branch). Soil-test findings a book uses as scope ("zinc deficient soils") are Conditions on a rating variable, not SoilTypes; "deficient" maps to rating `low`, keeping the printed word in `raw`. Counts stay numeric: "spider present at 1/hill" is `spider_count_per_hill >= 1`, not a boolean.

Whole alternative strategies (e.g. transplanted vs direct-seeded rice) link with `(:Recommendation)-[:ALTERNATIVE_TO]->(:Recommendation)`.

## Recommendation subtypes

There are 16 subtypes. Each adds only the fields below to the core; the question numbers refer to the competency questions.

| Subtype | Extra fields and edges | Questions |
| --- | --- | --- |
| `VarietyRecommendation` | `-[:RECOMMENDS]->Variety`, note | 1 |
| `SowingWindow` | start\_month, start\_day, end\_month, end\_day | 2 |
| `SeedRate` | Step `APPLIES` (kg per\_ha), method | 3 |
| `Spacing` | row\_cm, plant\_cm, hills\_per\_m2, seedlings\_per\_hill\_min/max | 3 |
| `SeedTreatment` | Steps applying an agent `per_kg_seed` | 3 |
| `NutrientDose` | dose\_basis (`blanket \| soil_test \| lcc`); ordered Steps, each with its own timing and `APPLIES` quantities; total = sum of Steps | 4, 6 |
| `DoseFormula` | target\_nutrient, `coef_T, coef_SN, coef_SP, coef_SK, coef_ON, coef_OP, coef_OK`, target\_yield\_unit, soil\_series, valid\_range | 5 |
| `IrrigationRule` | depth\_cm, criterion (e.g. "hairline cracks"), timing via Steps | 6 |
| `PestThreshold` | `-[:FOR_PEST]->Pest \| Disease`, `-[:HAS_CLAUSE]->ThresholdClause {observation, value, unit, sampling_unit, sampling_count, sampling_object, stage_id, any_of_group, raw}`; clauses are alternatives, each gated by its own Conditions. Scope that belongs to one clause ("2/hill in tungro endemic area") sits on that clause as a Condition (`endemic_area == disease:tungro`), never in the fact's `unmapped`; the same condition carries "in BPH prone areas/seasons" on a whole fact | 8 |
| `ControlMeasure` | control\_class (`cultural \| mechanical \| biological \| chemical \| physical`), `-[:TARGETS]->Pest \| Disease \| Weed \| Disorder`, Steps with `APPLIES` | 9, 18 |
| `WeatherRule` | operation, advice (`avoid \| delay \| do \| protect`), Conditions on weather variables | 10, 11, 13 |
| `HarvestRule` | maturity\_signs\[\], harvest\_moisture\_pct\_min/max, threshing\_moisture\_pct\_min/max, day window via Steps | 12, 13, 14 |
| `DryingSpec` | target\_moisture\_pct\_min/max, storage\_months\_min/max, storage\_term\_raw, method | 15, 16 |
| `StorageRule` | storage\_months\_min/max, min\_moisture\_pct, max\_moisture\_pct (each + `_inclusive`), structure, protectant Steps, `-[:TARGETS]->Pest {context: storage}` | 17, 18 |
| `QualitySpec` | Regulatory: authority, valid\_for\_season, parameter (`moisture \| foreign_matter \| damaged \| …`), limit\_value, unit | 19 |
| `Caution` | kind (`prohibition \| safety \| incompatibility \| banned \| waiting_period`), text\_en, `-[:CONCERNS]->ActiveIngredient \| AIGroup`, `-[:ABOUT]->Pest \| Disease` (e.g. the pest a resurgence warning names) | 9, 10, 20 |
| `WeedControl` | Not a separate subtype: a `ControlMeasure` whose `TARGETS` edge points at a Weed | — |

`sampling_unit` stays from the Basis list when it fits; samples such as "/25 net sweeps" or "/100 earheads" use `sampling_count` (25, 100) and `sampling_object` (`net_sweep \| earhead \| pass`); per-hill, per-tiller, per-plant and per-m² samples stay in `sampling_unit`. Every min/max pair above also has `<field>_inclusive` flags (default true), and every non-null numeric field has its source text in a `raw_<field>` property. Storage is described in months, not words. When a source gives only "short term" or "long term" without months, `storage_months_min/max` stay null and the bot asks or branches; it never guesses a mapping. `QualitySpec` values come from the current government procurement notice, not from books, and are re-checked every season.

## Provenance, sources and conflicts

Every recommendation and every variety record points to the exact source text it came from, and every book is registered by hand before extraction.

```
(:Recommendation | :Variety)-[:EVIDENCED_BY]->(:SourceSpan {
   id, bbox,
   pdf_page,              // PDF page, used to locate the text (Docling's numbering)
   printed_page,          // page number printed in the book, used in citations; null if none
   section_path,          // "Rice > 1.8 Main field > 1.8.6 Irrigation management"
   quote,                 // exact source text
   table_ref,             // Docling JSON pointer, e.g. "#/tables/12"
   table_row, table_col,  // the cell inside table_ref
   extraction_method      // native_text | ocr | table_parse
})-[:IN_SOURCE]->(:Source {
   id, title, publisher, language, url, sha256,
   edition_year,          // integer start year, used for ranking
   edition_label,         // the edition as written, e.g. "2021-22"
   state_id, region_scope, authority_tier,
   default_scope          // list of the approved rules, as text
})
(:Source)-[:SUPERSEDES]->(:Source)      // newer edition of the same book
```

**Source registry.** A small hand-written file per book, filled in before extraction (a few minutes per book):

| Field | Meaning | Example |
| --- | --- | --- |
| `state_id` | Whose book it is | `state:33` |
| `region_scope` | States or zones it is written for | `[state:33]` |
| `authority_tier` | 1 = state agricultural university package of practices; 2 = ICAR national guidance; 3 = other | 1 |
| `edition_year`, `edition_label` | Start year, and the edition as written | 2021, "2021-22" |
| `default_scope` | List of rules, each with its quote, page, optional section and status | `dose basis = per_ha unless stated` (p. 63, rice main field only) |
| `section_scope` | Section (heading text + PDF page range) → region, with status | A zone-specific chapter → that zone |
| `printed_pages` | Runs of PDF pages with a constant offset to printed page numbers | PDF 13–146: printed = PDF − 12 |
| `chapters` | The contents table, mapped to PDF pages, with crop_id | `1. RICE`, printed 1 = PDF 13 |
| `heading_fix` | Approved corrections: `split` a run-on heading, or `restore` a heading the converter turned into a list item | "1.1.1. Wet nursery Nursery area"; "Harvesting" → "1.5. Harvesting" |
| `reading_order_fix` | Moves a block the converter placed out of printed order, after an anchor | The COW(W)1 block after "I. SEASON AND VARIETY" |
| `section_scope.purposes` | Purpose taken from the section heading | "RICE - VARIETAL SEED PRODUCTION" → `purpose:seed` |
| `acknowledged_gap` | A numbering gap printed in the book itself, reported separately | Wheat has no printed "1." before "2. Morphological Description" |
| `review_note` | An approved note attached to matching facts; values never change | "suspected source typo: same product printed in g on p. 65" |
| `conflict` | A reviewer-approved contradiction between two facts, named by quote and page | Seed drying 8–9 % "long term" vs storage over 15 months below 8 % |

Rules and overrides carry `status` (`proposed \| approved \| rejected`); only approved ones are used. A section that matches no section, or more than one, fails loudly.

**Conflicts.** At load time, any two recommendations with the same subtype, applicability, identity and slot (step operation and method, targets with formulation, anchor, storage-month window) but different values are linked with `(:Recommendation)-[:CONFLICTS_WITH {origin: "detected"}]->(:Recommendation)` and set to `needs_review`. The link runs from the smaller id to the larger and queries match it undirected. Reviewers may also link facts of different subtypes that contradict each other through an approved registry `conflict` entry, which loads as `CONFLICTS_WITH {origin: "review"}` (worked example 2 links a DryingSpec to a StorageRule). The link is recorded on both facts, once per pair, however often detection runs. Conflicts are never merged; this catches contradictions between books and inside one book.

**Review fields.** `status`, `verifier`, `verifier_score` and `reviewed_by` record what the code checks, the Jev gate and human reviewers decided. Human decisions (approve, reject, needs change, with reviewer, date, note and an Uttarakhand-applicability answer) live in a committed decisions file keyed by fact id and a row hash of quote, values and scope; every load re-applies the ones whose hash still matches and lists the rest as stale. Approval never overrides fail-closed: an unregistered ingredient stays hidden. AI pre-check notes are hints in the review sheet, never decisions. A superseded fact sets `superseded_by` and is excluded from answers.

**Revisions.** Re-extracting a section never deletes reviewed work. Old and new facts are matched by `fact_key` (as defined under Recommendation: alternatives keyed at the list level; values excluded):

| Case | Action |
| --- | --- |
| Same values | Keep the node and its status, including `approved` |
| Different values | New node `(:new)-[:REVISION_OF]->(:old)` set to `needs_review`; the old approved fact keeps serving until the new one is approved |
| Fact missing from the new run | Never deleted; flagged `missing_in_latest_run`. An approved one keeps serving with the flag in its citation and is listed for review (usually a recall drop in the new prompt). The old side of a revision is not flagged |

`superseded_by` is reserved for a newer edition of a source; `REVISION_OF` is for re-extraction of the same edition.

## Answering a question

The agent builds a farm context, picks one of about 20 parameterised query templates, and ranks the facts that come back; the LLM never writes graph queries from scratch.

**Farm context.** Built at question time and never stored in the graph:

```json
{
  "district": "district:<lgd>", "zones": ["zone:..."], "state": "state:33",
  "month": 11, "local_seasons": ["season_local:samba"], "season": "season:rabi",
  "crop": "crop:rice", "variety": "variety:adt_53", "duration_group": "medium",
  "sowing_date": "2026-09-10", "das": 70, "stage": "stage:rice_flowering",
  "soil": {"N": "low", "P": "medium", "K": "high", "pH": 8.2},
  "forecast": {"rain_mm_24h": 18, "rain_days_3d": 2, "tmax_c": 34},
  "purpose": "purpose:grain", "storage_months": 3
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
5. `edition_year`, the integer start year (newer is better)

Ranking runs per answer slot (subtype, identity, storage window or term, duration group, which values the fact gives, and the branch taken on an unknown variable), so a narrow rule for one storage period never hides rules for another. Superseded and rejected facts are excluded. If several facts tie on all five keys and give different values, the answer shows the disagreement with both sources, together with any `CONFLICTS_WITH`. There is no `LIMIT`: the app takes the top-ranked group of each slot.

**Missing data: three-valued logic.** Every condition evaluates to TRUE, FALSE or UNKNOWN (value missing from the farm context). FALSE AND UNKNOWN = FALSE, TRUE OR UNKNOWN = TRUE, anything else involving UNKNOWN stays UNKNOWN. Each condition variable has one `on_unknown` policy:

| Variables | on\_unknown |
| --- | --- |
| soil ratings and values, sowing\_date / das, variety, purpose, storage\_months, grain\_moisture\_pct | Ask the farmer; if they do not know, branch ("if your soil N is low… otherwise…") |
| forecast variables (weather call failed) | Conservative: Cautions and "avoid" WeatherRules fire; say the forecast is unavailable |
| pest\_count, spider\_count\_per\_hill | Ask ("how many hoppers per tiller?") |

Safety rule: an UNKNOWN condition lets a Caution fire and withholds an action. Evaluation is top-down: Recommendation conditions, then Step conditions, then ThresholdClause conditions. FALSE at a parent prunes its children; UNKNOWN at a parent passes its policy down.

**Safety joins.** Any template that returns `ControlMeasure`, `SeedTreatment` or `StorageRule` must:

- always join the related `Caution` nodes;
- drop any step whose `APPLIES` points to an ingredient whose `reg_status` is not `registered`: `banned`, `restricted` and `unknown` all fail closed, and the answer says why the step is withheld.

If no fact matches, the bot says it has no guidance. It never lets the LLM fill the gap, especially for chemical questions.

**Unreviewed facts.** `extracted` and `needs_review` are both unreviewed. `auto_verified` facts are served labelled "checked automatically against the source"; `approved` facts are served plainly. What farmers see while a fact is unreviewed (decided):

| Fact type | While unreviewed |
| --- | --- |
| Chemical doses; anything with an inferred basis or inherited quantity; banned or restricted ingredients | Hidden: the bot says it has no verified guidance |
| Fertiliser doses with explicit units | Hidden |
| Descriptive facts: maturity signs, storage structures, drying targets with explicit values | Shown, marked "not yet verified by an expert" |
| Pest thresholds (what to count, not what to apply) | Shown, marked "not yet verified by an expert"; the control doses stay hidden |
| Cautions | Shown, marked "not yet verified by an expert" (a wrong extra warning is cheap) |

A fact with `scope_in_unmapped` is hidden until a person approves it, unless it is a Caution (shown labelled). A fact flagged `missing_in_latest_run` is excluded unless it is approved. Every served fact carries its citation: quote, PDF and printed page, source title, status and `verifier_score`.

**Example template: `drying_target`.**

```cypher
// $region_ids = farmer's district + zones (own state scheme) + state + 'country:in'
MATCH (r:Recommendation:DryingSpec)-[:FOR_CROP]->(:Crop {id:$crop})
WHERE r.status IN ['approved','auto_verified'] AND r.superseded_by IS NULL
  AND EXISTS { (r)-[:IN_REGION]->(g) WHERE g.id IN $region_ids }
  AND (NOT EXISTS { (r)-[:FOR_PURPOSE]->() }
       OR EXISTS { (r)-[:FOR_PURPOSE]->(p) WHERE p.id = $purpose })
  AND ($storage_months IS NULL                       // UNKNOWN: keep all, app asks or branches
       OR ((r.storage_months_min IS NULL OR r.storage_months_min < $storage_months
            OR (r.storage_months_min = $storage_months AND coalesce(r.storage_months_min_inclusive, true)))
       AND (r.storage_months_max IS NULL OR $storage_months < r.storage_months_max
            OR ($storage_months = r.storage_months_max AND coalesce(r.storage_months_max_inclusive, true)))))
MATCH (r)-[:EVIDENCED_BY]->(s:SourceSpan)-[:IN_SOURCE]->(src:Source)
WITH r, s, src,
     reduce(m = 0, x IN [(r)-[:IN_REGION]->(g) WHERE g.id IN $region_ids | g.level] |
            CASE WHEN x > m THEN x ELSE m END)                     AS region_level,
     CASE WHEN EXISTS { (r)-[:FOR_PURPOSE]->() } THEN 1 ELSE 0 END AS purpose_explicit
RETURN r, s.quote, s.pdf_page, s.printed_page, src.title, region_level, purpose_explicit,
       src.authority_tier, src.edition_year,
       [(r)-[:CONFLICTS_WITH]-(c) | c.id] AS conflicts
ORDER BY region_level DESC, purpose_explicit DESC, src.authority_tier ASC, src.edition_year DESC
```

The example filters to served statuses for brevity; the implementation fetches all candidate facts and applies the visibility rules above in code. If the farmer's state returns nothing, a second query follows the cross-state policy table: `QualitySpec` and `Caution` cross without a label; `DryingSpec`, `StorageRule`, `PestThreshold` and `HarvestRule` fall back with the source-state label ("From a Tamil Nadu source"); the rest answer "No local guidance available".

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

1. **Register the source** (by hand, about 10 minutes per book): state, authority tier, edition, default-scope rules, section scopes, printed-page runs, chapter list and heading fixes.
2. **Convert.** Docling turns the PDF into lossless JSON: text, headings, tables, page and position. Legacy-font and image-only pages are OCR'd. Local, no LLM.
3. **Segment.** One extraction unit per section: heading path, text, tables, pages, section scope. Never fixed-size chunks, because bullets refer back to each other ("for that situation"). Docling's heading levels are unreliable, so the section tree is rebuilt from the numbering text and the approved chapter list.
4. **Parse and check tables in code.** Where a table has rulings, cell text is rebuilt from the PDF text layer by the ruled row and column bands (moving words only, with exact character conservation per table part), because the converter's cell boxes can cross rulings; parts without rulings keep the converter's cells. Cells whose box crosses a full-width row or column ruling are flagged. Then stitch tables across pages and pivot variety tables, and compare each table's header and row count against the page before trusting it. Variety rows become Variety records without an LLM.
5. **Extract.** One LLM call per unit returns a list of facts in the Pydantic models, each value with its raw text and a quote. Text fields (method, observation, maturity signs, structures) are copied verbatim from the quote; a target taken from a heading is flagged `target_from_heading`; a generic target ("Pest") is never written; "avoid …" advice is extracted as a prohibition `Caution`, not as a control step. Guesses are flagged (`basis_inferred`), phrases with no slot go to `unmapped`, an amount stated in an earlier bullet is marked `quantity_ref` rather than invented, and fallbacks get `alt_priority` 2.
6. **Normalise and link (code).** Units and bases to canonical form; ranges to min/max; names to concept IDs by exact, alias, then embedding lookup, else a proposed new concept for review. `quantity_ref` is resolved to the sibling fact in the same section with `inherited: true`; an ambiguous reference goes to review.
7. **Validate (code).** Nothing is auto-corrected.
   - Quote: normalise the quote and the unit's text the same way (whitespace, dash characters, soft hyphens, ligatures), then require an exact match against the text the LLM was given.
   - Numbers: every raw number in a fact, including words ("one tonne") and fractions, must appear in its quote. Normalised values are not checked here.
   - Vocabulary, value ranges, normalised condition form; every active ingredient against the official banned and restricted list.
   - Alternatives: in an `alt_group` whose options are all fertilisers, nutrient totals per option must agree within about 15%, else flag. Only approved fertiliser percentages are used.
   - Quote location: found exactly once in its unit, on the fact's table row when it has one.
   - Ranges: a printed range stored as a single bound fails as `range_narrowed`.
   - Active ingredients fail closed unless `reg_status = "registered"`.
   - No stored text contains U+FFFD; every printed target, unit and copied text field (method, observation, maturity sign, structure) appears in the quote (case-insensitive), in the fact's own table row, or, for a fact flagged `scope_from_heading` or `target_from_heading`, in its sub-heading.
   - A number that survives only in text (`unmapped` or `purpose_raw`, e.g. "hastened by 3-4 days") adds a review reason.
   - Scope in `unmapped` (a variety type, area, condition or moisture phrase; "especially …" excluded) sets `scope_in_unmapped`.
8. **Verify with Jev 1.14.** Code builds the claims from the stored fields, one per step and value, in the book's own wording wherever a stored value is an interpretation (printed names, printed condition text, "to 12 %" rather than "at most 12 %"); the LLM never writes them. One request per unit carries all its claims; a fact's `verifier_score` is its lowest claim's P(yes). Control claims with one number changed check that Jev reads values. A fact with no code-built claim can never be `auto_verified`. The `auto_verified` cut-off is set by measuring precision on the gold set.
9. **Load (code).** Resolve scope edges, merge by `fact_key` under the revision rules, then add conflict links, embeddings and indexes, and run the 20 competency questions.

**Review queue.** Ordered by risk: chemical doses and banned or restricted ingredients first, fertiliser doses next, descriptive facts last.

**Measurement.** Precision and recall per subtype, against a small set of sections annotated by a person who has not seen any model output. Both Claude's and Sarvam's extractions are scored against that set. The gold workbook is frozen by sha256; every disagreement is adjudicated against the printed page in a committed adjudications file (by category rule or one by one), never decided in code. Rates are reported with Wilson 95 % intervals, and "agreeing" as a lower and upper bound while any verdict is unclear. Controls vary number, unit and pest.

**Hand-run first.** Rice wet-nursery nutrients, brown planthopper threshold and control, and rice harvest → drying → storage, before any bulk run.

**Alternatives check, worked.** The rice nursery section offers 40 kg DAP, or as a fallback 16 kg urea + 120 kg super phosphate. DAP gives 7.2 kg N and 18.4 kg P₂O₅; the fallback gives 7.4 kg N and 19.2 kg P₂O₅, so the check passes.

Jev facts: hosted only (TypeSafe); text in, probabilities out. A `noul` question returns the probability of "yes", and every question in a call is evaluated independently against the same state, so one call per section can carry all its claims; about $0.042 per million input tokens, output free; English is its strongest language. Checking 20,000 claims at about 2,000 tokens each costs roughly $1.70. The free tier answers about one request per minute (HTTP 429 with `retry-after: 60` otherwise).

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

The values below come from the rice chapter of the TNAU Crop Production Guide 2020; page numbers are filled in at extraction. All three examples carry `IN_REGION {origin:"source"}` → `state:33`.

**1. Brown planthopper threshold.** Source text: "1 hopper/tiller in the absence of predatory spider and 2 hoppers/tiller when spider is present at 1/hill".

```
(:Recommendation:PestThreshold {summary_en:"BPH: act at 1/tiller, or 2/tiller if spiders >= 1/hill"})
   -[:FOR_CROP]->(crop:rice)   -[:FOR_PEST]->(pest:brown_planthopper)
   -[:HAS_CLAUSE]->(:ThresholdClause {observation:"hoppers", value:1, unit:"count", sampling_unit:"per_tiller", raw:"1 hopper/tiller"})
        -[:WHEN]->(:Condition {variable:"spider_count_per_hill", op:"<", value:1})
   -[:HAS_CLAUSE]->(:ThresholdClause {observation:"hoppers", value:2, unit:"count", sampling_unit:"per_tiller", raw:"2 hoppers/tiller"})
        -[:WHEN]->(:Condition {variable:"spider_count_per_hill", op:">=", value:1})
   -[:EVIDENCED_BY]->(:SourceSpan {quote:"1 hopper/ tiller in the absence of predatory spider..."})
```

If the farmer has not counted spiders, `spider_count_per_hill` is UNKNOWN and the bot asks.

**2. Rice seed storage, and a conflict inside the book.** The storage section gives three month ranges; the drying section, half a page earlier, calls 8–9% "long term".

```
StorageRule {storage_months_min:8,  storage_months_max:9,    min_moisture_pct:12, max_moisture_pct:13, structure:"gunny or cloth bag"}
StorageRule {storage_months_min:12, storage_months_max:15,   min_moisture_pct:8,  max_moisture_pct:9,  structure:"polylined gunny bag"}
StorageRule {storage_months_min:15, storage_months_min_inclusive:false, storage_months_max:null,
             max_moisture_pct:8, max_moisture_pct_inclusive:false, structure:"700 gauge polythene bag"}
   (all three: FOR_PURPOSE → purpose:seed)

DryingSpec  {storage_term_raw:"long term", target_moisture_pct_min:8, target_moisture_pct_max:9}
   -[:CONFLICTS_WITH]-> StorageRule (>15 months, <8%)          → status: needs_review
```

The first rule follows the book ("short term storage (8-9 months)"); v1.1 wrongly showed 0–9. The third is "more than 15 months" at "less than 8 %", so both bounds are strict. The book leaves a gap between 9 and 12 months; a farmer storing for 10 months gets a question back, not a guess.

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
- [ ] Confirm the procurement moisture limits for `QualitySpec` from the current season's notice. The TNAU harvest rules are for seed crops only, so grain harvest moisture needs this or another source.
- [ ] Seed `GrowthStage` concepts for rice (stage timing currently does not link).
- [ ] Load the official CIB&RC registration list into `reg_status`; until then every chemical recommendation stays hidden.
- [ ] Neo4j edition for deployment.

## Changes from v1.3

1. **KNO3 is a Fertilizer**, not an Input; identity follows the substance. Fertilizer percentages are optional.
2. **`fact_key` written out in full** (identity and the quote's first passage ref), and **alternatives keyed at the list level**: adding, removing or renumbering an option changes `value_key` and id, so it loads as `REVISION_OF`. `conflict_key` stays per option.
3. **Formulation → operation for spray lists:** D/DP → dusting and G/GR/CG → application override a printed "spray"; any other printed verb, carriers, baits and seed treatments keep their operation.
4. **An `APPLIES` may have no dose** (a strength, ratio or share alone); new `mix_conc_*` (strength in a prepared mix) and `carrier_raw`.
5. **Step durations and purpose:** `duration_*` and `purpose_raw`; the farmer-facing instruction keeps the printed purpose.
6. **Option lists applied at several stated times** record them in `repeat_offsets` (one product, applied at every time); `repeat_count` equals its length.
7. **Clause-level scope** for thresholds: condition `endemic_area` (a concept value, e.g. `disease:tungro`) on the clause, never in the fact's `unmapped`.
8. **`scope_in_unmapped`** on the fact, and its visibility rule (hidden until approved, except Cautions).
9. **Expert review:** decisions file, row hash, re-application on load, `reviewed_at`, `expert_note`, `applies_uttarakhand`; AI pre-check notes are hints only.
10. **Extraction rules:** verbatim text fields, `target_from_heading` for heading targets, no generic targets, "avoid …" advice as a prohibition Caution; `offset_unit` gains `weeks`; "in equal volume" is 1:1 from the word table.
11. **Pipeline:** tables rebuilt from rulings with ruling checks; validation adds lost-glyph, printed-text and scope checks; evaluation uses a frozen gold set, adjudication files and Wilson intervals.

## Changes from v1.2

1. **No map properties.** Neo4j rejects maps: `raw{}` becomes `raw_<field>`, DoseFormula `coefficients{}` becomes `coef_<name>` (case as in the formula: `coef_SN`), Variety `cells{}` becomes `cells_json`, and Fertilizer `other{}` becomes `CONTAINS {pct, raw}` edges to Nutrient.
2. **StorageRule `min_moisture_pct`** (+ `_inclusive`), so "12 - 13 %" keeps both bounds; `Spacing.seedlings_per_hill_min/max` likewise.
3. **New OperationType values:** `dusting`, `application`, `release`, `trapping`, `baiting`, `bund_management`, `sanitation`; mixed dust/spray lists take each option's operation from its formulation.
4. **`Input` concept** for applied things that are not nutrients, fertilisers, organic inputs or active ingredients.
5. **Concentrations, ratios and shares** on `APPLIES`: `conc_*`, `ratio_*` and `share_pct`.
6. **Sampling units** on ThresholdClause: `sampling_count` and `sampling_object` (net sweep, earhead, pass).
7. **Repeat schedules** on Step: `repeat_count`, `repeat_interval`, `repeat_interval_unit` (days or weeks), `repeat_raw`.
8. **AIGroup concept** and `MEMBER_OF`; Cautions may concern a group and name the pest they are `ABOUT`; `acaricide` and `biopesticide` use classes; `use_class` optional.
9. **Soil-test findings as Conditions** (`soil_Zn_rating` and similar), not SoilTypes.
10. **`FOR_PURPOSE {origin}`**, a list of `text` and/or `section`.
11. **Fail closed:** a step applying an ingredient is served only if its `reg_status` is `registered`.
12. **Visibility and ranking:** `extracted` is unreviewed like `needs_review`; pest thresholds are shown labelled; approved facts missing from the latest run keep serving with a flag; ranking is per answer slot; every answer carries a citation.
13. **Conflicts:** `CONFLICTS_WITH {origin: detected | review}`, detection includes the step method and storage window, reviewer links come from registry `conflict` entries.
14. **`fact_key`** adds conditions and the step's method and anchor. **Core properties** record `extraction_flags`, `review_reasons`, `review_notes`, the Jev claim lists, `conflict_key` and `value_key`; `excluded_regions` become parallel lists.
15. **Registry additions:** `restore` heading fixes, `reading_order_fix`, `section_scope.purposes`, `acknowledged_gap`, `review_note`, `conflict`.
16. **Pipeline:** validation adds quote location, `range_narrowed` and fail-closed checks; Jev claims use the book's wording, the fact score is the lowest claim, control claims are sent, and the free tier allows about one request per minute.

## Changes from v1.1

1. **Two page numbers.** `SourceSpan.page` is replaced by `pdf_page` (locating) and `printed_page` (citations); the registry's `printed_pages` runs map one to the other.
2. **Raw text for every number.** `ThresholdClause.raw`; a `raw` map on every subtype and on Variety; `APPLIES.raw` covers the whole quantity phrase.
3. **Condition-only units** `mm` and `degC`.
4. **Strict bounds.** `<field>_inclusive` flags, default true, on every bound; the `drying_target` template honours them.
5. **Hour offsets.** `Step.offset_unit`: `days` (default) or `hours`.
6. **Editions.** `edition_year` is the integer start year; `edition_label` keeps the edition as written.
7. **IDs are prefixed and lowercase everywhere**, including the farm context (`season:rabi`, `purpose:grain`) and Nutrient (`nutrient:p2o5`). Tamil Nadu is `state:33`. Variety IDs are a slug of the name as written (`variety:adt_53`). Regions and LocalSeason use `name_en` like every concept.
8. **Worked example 2 fixed:** short-term seed storage is 8–9 months, as in the book.
9. **`default_scope` is a list of rules,** each optionally section-scoped and approved in the registry.
10. **Exclusions:** `excluded_regions`, expanded by code into `IN_REGION` edges with `origin: "text_exclusion"`; such facts are `needs_review`.
11. **Table cells in provenance:** `SourceSpan.table_row` / `table_col`; Variety numbers keep their raw text. Variety records pivoted from tables are the one sanctioned case of concepts created by code, and stay `needs_review` until approved.

Also: concepts carry `review_status` and `source`; cross-subtype conflicts may be linked by reviewers; `grain_moisture_pct` is in the on-unknown table; the source registry now lists `section_scope`, `printed_pages`, `chapters` and `heading_fix`; segmentation rebuilds the section tree from heading numbers; and the Jev notes record what a `noul` answer means.

## Sources

- [TNAU Crop Production Guide — Agriculture 2020](https://agritech.tnau.ac.in/pdf/AGRICULTURE.pdf) (examples and patterns)
- [TypeSafe model docs — Jev 1.14](https://docs.typesafe.ai/models)
- [TypeSafe docs — confidence and outputs](https://docs.typesafe.ai/confidence)
- [Akita — comparison of Jev-like decision models](https://akitaonrails.com/en/2026/10/10/which-jev-like-ai-decision-classifier-model-is-best/)
- [Neo4j — navigating a knowledge graph with Jev](https://neo4j.com/blog/genai/navigating-a-neo4j-knowledge-graph-with-jev/)
- [Neo4j — rescored binary vector search](https://neo4j.com/blog/developer/rescored-binary-vector-search-in-neo4j-search-more-with-less-memory/)
- [FAO AGROVOC](https://agrovoc.fao.org)
