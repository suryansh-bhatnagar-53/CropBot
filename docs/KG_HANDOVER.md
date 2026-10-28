# CropBot knowledge graph: handover

For teammates who haven't worked on the pipeline. The KG-building phase closed on 2026-10-24. This page says what is in the graph, how to get it on your machine, and how the agent asks it questions. Everything else (every decision, every number, every known problem) is in `CLAUDE.md`; the schema is `docs/schema_v1.6.md`.

## 1. What is in the graph (main database, 2026-10-24)

Snapshot `13c96aefbc1ee99265369282f5f0746446ef6a86795e24d319337855ff5c681d`: 842 nodes, 1,280 relationships (`uv run python -m kg.load.facts --snapshot` prints it; if the hash differs, the graph changed).

Every agronomic fact is a `Recommendation` node with a subtype label, applicability edges (crop, region, system, …), and a `SourceSpan` holding the exact quote, the PDF page and the source.

| Source | Region | Authority tier | Facts in the graph | Held (not loaded) |
|---|---|---|---|---|
| `source:tnau_agriculture_2020`: TNAU Crop Production Guide, Agriculture 2020 (rice chapter, 4 sections) | Tamil Nadu (`state:33`) | 1 (state university) | 113: 12 extracted, 101 needs_review | 11 |
| `source:dfpd_uniform_spec_kms_2026_27`: DFPD uniform specification, paddy, KMS 2026-27 (DFPD letter dated 17.08.2026) | national (`country:in`) | 0 (regulatory) | 18 QualitySpec, all **approved** | 0 |
| `source:gbpuat_kharif_advisory_2020`: GBPUAT Pantnagar, "Advisory for Kharif Season in Uttarakhand", dated 02.05.2020 (rice rows) | Uttarakhand (`state:5`) | 1 | 8, all **approved**: 2 VarietyRecommendation, 6 SowingWindow | 4 (Chetki Dhan, Jethi Rice) |

TNAU by subtype: ControlMeasure 44, NutrientDose 13, Caution 12, SeedTreatment 12, PestThreshold 8, IrrigationRule 6, HarvestRule 5, StorageRule 5, SeedRate 4, DryingSpec 3, Spacing 1.

The GBPUAT advisory is dated 02.05.2020 (the date in its URL's file name and its PDF metadata; the page itself prints no date). Its windows and varieties are for the 2020 kharif season and have not been checked against a newer advisory.

**Status.** Code sets `extracted` or `needs_review` (steps 10–12: needs_review whenever something about the fact needs a person's look; `auto_verified` would also come from code, but no threshold is set, so no fact has it). Only `approved` and `rejected` come from people, through the expert decisions file (`data/review/expert_decisions.csv`). `approved` facts are served as they are; `extracted` and `needs_review` are unreviewed (section 5). No TNAU fact has been reviewed yet.

**The three approved answers** (served with no warning label):
1. **Paddy procurement quality** (`quality_check`): the 18 DFPD limits for paddy, KMS 2026-27 (moisture at most 17 %, foreign matter, damaged grains, the substances paddy must be free from, …), for every state.
2. **Rice varieties for Uttarakhand** (`varieties_for`): 16 varieties for Tarai, Bhabhar & Plain; 8 for the irrigated hills (mid and high hills).
3. **Rice sowing and transplanting windows for Uttarakhand** (`sowing_window`): Tarai nursery 16 May – 7 June and transplanting 25 June – 7 July; irrigated mid hills nursery 1–15 May and transplanting 16–30 June; irrigated high hills nursery 16–30 April and transplanting 1–15 June.

## 2. Getting the graph on your machine

**The graph is in the repository**, in `kg_snapshot/` (2026-10-24; written by `kg.export`):

| File | Bytes | What it is |
|---|---|---|
| `nodes.jsonl` | 554,424 | every node, one per line: `{"id", "labels", "props"}`, sorted by id |
| `relationships.jsonl` | 149,930 | every relationship: `{"type", "start", "end", "props"}`, sorted by type, start, end |
| `manifest.json` | 2,430 | snapshot hash, counts by label and type, facts by source and status, export time, source commit, Neo4j version, file sha256s |
| `neo4j.dump` | 345,615 | the same graph as a Neo4j dump (store format `block-block-1.1`, Neo4j 2026.09.0 Enterprise) |

All four hold snapshot `13c96aef…` (842 nodes, 1,280 relationships). The JSONL is plain text and diffs cleanly: it is the reviewable copy. `.gitattributes` keeps these files byte for byte on every checkout, so their sha256s in the manifest still hold. Rebuilt from the JSONL alone, `cropbot-test` gave exactly this snapshot hash, `created_at` included, and the same counts and statuses as main.

The older backups (the zipped `data/` folders and the first dump) are on Google Drive:

Dump shared at: https://drive.google.com/drive/folders/1JxrvL_QkruGKKS9QinPvpJGMPF_RY-6E?usp=sharing (open the "backups" subfolder: all 12 files from `backups/` are there, their sizes checked against the local copies)

Download the files you need; don't delete or overwrite anything in this folder: it is the only shared copy of the backups. Ask Suryansh before changing it.

### Steps

1. **Clone the repository** (`kg-pipeline` branch).
2. **Install Neo4j Desktop and create a local DBMS of version 2026.09 or newer.** Desktop's local DBMSs are Neo4j Enterprise under the developer licence, the edition the dump needs. The dump was made with and loaded on 2026.09.0 (Neo4j Desktop 2, 2026-10-24); a newer DBMS version is expected to load it but has not been tried. Set the DBMS's password and leave it stopped. Don't use Community edition for now (see "Community edition" below).
3. **Python environment:** install [uv](https://docs.astral.sh/uv/), then in the repo root:

   ```bash
   uv sync
   ```

   The project needs Python 3.13 (`requires-python = ">=3.13"`, pinned to 3.13 in `.python-version`); uv fetches it if it is missing.
4. **`.env`:** copy `.env.example` to `.env` in the repo root and fill in `NEO4J_URI` (your DBMS's Bolt URL, port 7687 by default), `NEO4J_USER` and `NEO4J_PASSWORD` (the password you set in step 2). `NEO4J_HOME` (the DBMS's folder) and `NEO4J_JAVA_HOME` (Neo4j Desktop's Java 21 runtime) are needed only to make a dump; `BEATAPI_API_KEY` only to build the graph. Never commit `.env`.
5. **Load the graph**, either way:
   - **(a) the dump, into the home database `neo4j`.** With the DBMS stopped, from the DBMS's installation folder:

     ```bash
     bin/neo4j-admin database load neo4j --from-path=<repo>/kg_snapshot --overwrite-destination=true
     ```

     On Windows it is `bin\neo4j-admin.bat`, and it needs `JAVA_HOME` set to Neo4j Desktop's bundled Java 21 runtime. If the DBMS is already running, stop just the database instead: run `STOP DATABASE neo4j WAIT` on the `system` database, load, then `START DATABASE neo4j WAIT`. Then start the DBMS.
   - **(b) the JSONL, into a separate empty database.** `kg.export load` writes through Bolt (no `neo4j-admin`) and refuses any database that is not empty, and the home database by default (`--into-empty-home` allows an empty one: see "Community edition and AuraDB Free" below), so it never overwrites a graph. Create the database first (Enterprise, on the `system` database: `CREATE DATABASE kg WAIT`), then:

     ```bash
     uv run python -m kg.export load --database kg
     ```

     It checks the files' sha256s against the manifest, creates the id constraints, nodes and relationships in one transaction, and prints the counts and the snapshot. Query that database with `ask(..., database="kg")`.
6. **Check the connection and the data:**

   ```bash
   uv run python scripts/check_neo4j.py
   ```

   ```bash
   uv run python -m kg.export check
   ```

   The first prints the server version; the second compares the database (add `--database kg` for route b) with `kg_snapshot/` and must print "kg_snapshot/ matches".
7. **Ask one question:**

   ```bash
   uv run python -c "from kg.query import ask; out = ask('sowing_window', {'crop': 'crop:rice', 'state': 'state:5', 'zones': ['zone:uk_tarai_bhabhar_plain']}); print([(f['values']['window_for'], f['citation']['quote']) for s in out['slots'] for f in s['facts']])"
   ```

   It prints the Tarai nursery and transplanting windows with their quotes (for route b, pass `database="kg"` to `ask`).

### After any reload: export, then commit

Whenever the graph is reloaded (a new source, new approvals, a re-run), keep `kg_snapshot/` in step with it:

1. `uv run python -m kg.export check`. If it prints "kg_snapshot/ matches", the graph did not change: commit nothing, and never commit a routine re-export.
2. If it reports a difference, the graph changed: `uv run python -m kg.export write --dump` (it stops, dumps and restarts the database; it needs `NEO4J_HOME` and `NEO4J_JAVA_HOME`) and `uv run python -m kg.export secrets`.
3. Review `git diff kg_snapshot/` (the JSONL shows exactly which nodes and properties changed), then commit `kg_snapshot/` with the change it reflects. The dump is committed only in this case, when the graph changed, so binary history grows only with real changes.

`write` refuses, writing nothing, if a `.env` password, key, token or secret value or a key-like string turns up in the files; reviewer names and notes are expected (they are in the decisions file too).

**Community edition and AuraDB Free.** The dump's store format is `block-block-1.1` (introduced in Neo4j 5.14.0; read with `neo4j-admin database info neo4j` on 2026-10-24). Whether Neo4j Community loads it is **untested**, so teammates use Neo4j Desktop (step 2). For a Community or AuraDB Free deployment later, test first (recorded in the CLAUDE.md backlog). Three routes, none tested on Community or Aura:
- **the JSONL into the empty home database** (the route for a server with only one database, as Community and AuraDB Free have). `kg.export load` uses only Cypher over Bolt and uniqueness constraints, and on such a server the only database is the home database, which `load` refuses by default. Pass the option explicitly:

  ```bash
  uv run python -m kg.export load --database neo4j --into-empty-home
  ```

  It loads only when the home database has 0 nodes and 0 relationships, and refuses otherwise ("it is not empty (842 nodes, 1280 relationships)"), so it never overwrites a graph; without the option the home database is always refused. Then run `kg.export check` and query with `ask()` as usual (no `database=` needed). Tested on 2026-10-24 on `cropbot-test` posing as the home database: refused by default, refused with one node in it, loaded once empty, with the same snapshot hash;
- **migrate the store format:** on Enterprise, convert the database with `neo4j-admin database migrate` to a store format Community supports, dump it again, and load that dump into Community;
- **rebuild with the pipeline's loaders:** `uv run python -m kg.load.seed`, then `uv run python -m kg.load.facts <source>` for each source, from the gitignored `data/tables/`, `data/normalized/`, `data/validated/` and `data/verified/` (unzip them from the Drive backups). The snapshot hash then differs (`created_at` records the time of the load); compare counts and statuses instead.

## 3. Starting Neo4j and connecting

- **Server:** a Neo4j Desktop local DBMS, 2026.09 or newer (Enterprise, developer licence; the development machine runs 2026.09.0). Start the DBMS in Neo4j Desktop and wait until it shows **Running**. It listens for Bolt on port 7687.
- **Databases:** `neo4j` (the home database: the real graph) and, on the development machine, `cropbot-test` (live tests only; every live test empties it first).
- **Connection settings** come only from `.env` in the repo root, which is never committed. The names (see `.env.example`):
  - `NEO4J_URI`: the Bolt URL of the local server;
  - `NEO4J_USER`, `NEO4J_PASSWORD`;
  - `BEATAPI_API_KEY`: the Jev verifier, needed only to build the graph, never to query it.
- **Backup** (2026-10-24, gitignored `backups/` on the development machine; none of it is on GitHub, so copy it elsewhere). Every zip's entry count was checked against its folder's file count.

  | File | Bytes | Contents |
  |---|---|---|
  | `neo4j.dump` | 345,278 | the `neo4j` database (sha256 `edd99b47…`); restored into `cropbot-test` and checked: same snapshot hash |
  | `data_raw_2026-10-24.zip` | 7,940,863 | `data/raw/`: the 3 source PDFs |
  | `data_docling_2026-10-24.zip` | 4,900,891 | `data/docling/`: the conversions (110 files) |
  | `data_review_2026-10-24.zip` | 4,721,869 | `data/review/`: review workbooks, hand-check pages, review CSVs and the decisions file (29 files) |
  | `data_extracted_2026-10-24.zip` | 660,266 | `data/extracted/`: the hand-run prompts and answers, with history (74 files) |
  | `data_units_2026-10-24.zip` | 339,616 | `data/units/`: segmentation units (6 files) |
  | `data_tables_2026-10-24.zip` | 133,249 | `data/tables/`: stitched tables and pivoted varieties (9 files) |
  | `data_verified_2026-10-24.zip` | 102,567 | `data/verified/`: Jev claims, answers and request logs (22 files) |
  | `data_normalized_2026-10-24.zip` | 63,380 | `data/normalized/`: step 10 facts and held facts (9 files) |
  | `data_validated_2026-10-24.zip` | 46,317 | `data/validated/`: step 11 facts (6 files) |
  | `data_eval_2026-10-24.zip` | 5,449 | `data/eval/`: the step 15 report (1 file) |
  | `data_loaded_2026-10-24.zip` | 2,325 | `data/loaded/`: step 13 load reports (3 files) |
  | **total** | **19,262,070** | |

  `data/gold/` is committed, so it needs no zip.

## 4. How the agent queries: pick a template, never write raw Cypher

The only entry point is

```python
from kg.query import ask
answer = ask(template, farm_context)      # -> dict (section 5)
```

- `template` is one of the seven names below. Each has fixed Cypher in `kg/query/templates.py`; the agent never writes or edits graph queries. A question no template covers gets no answer from the graph.
- `farm_context` is a dict (or a `kg.query.FarmContext`) describing the farmer. Fill only what the farmer has told you: **a missing field means "unknown"**, and the answer then asks for it instead of guessing. An unknown field name is refused.
- `ask` opens a connection from `.env` and closes it again. To reuse one connection, pass `driver=` (a `neo4j` driver); `database=` reads another database (for example `cropbot-test`).
- `ask` raises `kg.query.AskError` for an unknown template, a bad farm context or missing `.env` settings.
- From the shell, with a JSON context file: `uv run python -m kg.query sowing_window --context ctx.json`.

### The farm context (`kg/query/context.py`)

| Field | Example | Meaning |
|---|---|---|
| `crop` (required) | `"crop:rice"` | crop id (`concepts/crops.csv`) |
| `state` | `"state:5"` | LGD state id: Uttarakhand `state:5`, Tamil Nadu `state:33` |
| `district` | | district id (none seeded with an LGD code yet) |
| `zones` | `["zone:uk_tarai_bhabhar_plain"]` | the farmer's zones in their own state's scheme (`concepts/zones.csv`): `zone:uk_tarai_bhabhar_plain`, `zone:uk_mid_hills` (900–1500 m), `zone:uk_high_hills` (1500 m and above), and the Tamil Nadu zones (`zone:tn_…`) |
| `systems` | `["system:irrigated"]` | production systems (`concepts/production_systems.csv`) |
| `purpose` | `"purpose:grain"` | `purpose:grain` or `purpose:seed` (also fodder, …) |
| `duration_group` | `"medium"` | `short`, `medium` or `long` |
| `variety`, `season`, `local_seasons`, `soil_types`, `stage` | | concept ids |
| `month`, `sowing_date`, `das` | | when (days after sowing) |
| `storage_months` | `10` | how long the produce will be stored |
| `pest` | `"pest:brown_planthopper"` | required by `threshold` |
| `observations` | `{"spider_count_per_hill": 0}` | counts and measurements: `pest_count`, `spider_count_per_hill`, `grain_moisture_pct` |
| `soil` | `{"pH": 6.5, "Zn": "low"}` | soil-test ratings N, P, K, Zn and pH |
| `forecast` | `{"rain_mm_24h": 12}` | `rain_mm_24h`, `rain_days_3d`, `tmax_c` |
| `endemic` | `{"disease:tungro": true}` | whether the area is known for a pest or disease |
| `commodity_form`, `grade`, `quality`, `present` | `"paddy"`, `{"moisture": 18}` | `quality_check` only: what is sold, its grade, measured values, substances found |

### Choosing the farmer's zone

No district has an LGD code yet and there is no district → zone mapping, so the agent cannot derive a zone from where the farmer lives. For an Uttarakhand farmer it asks instead and sets `zones` itself:

- **plains or hills?** Plains (Tarai, Bhabhar and the plains) → `["zone:uk_tarai_bhabhar_plain"]`.
- **for hills, the altitude:** 900–1500 m → `["zone:uk_mid_hills"]`; 1500 m and above → `["zone:uk_high_hills"]`. Also ask whether the field is irrigated (`"systems": ["system:irrigated"]`): the hill varieties and windows are for irrigated hills, and without a system the answer asks for it.

Without a zone, `varieties_for` and `sowing_window` answer "No local guidance available" (checked on the main database with `{"crop": "crop:rice", "state": "state:5"}`): their facts are scoped to zones, and they never fall back to the state or to another state.

### The templates, one example each

Every example below was run on the main database on 2026-10-24; the comment says what came back.

**`drying_target`**: to what moisture to dry (DryingSpec; Q15, Q16). For `purpose:grain` it also adds the procurement moisture limit.
```python
ask("drying_target", {"crop": "crop:rice", "state": "state:33", "purpose": "purpose:grain"})
# 1 fact: dry the grains to 12 % (TNAU p. 39), labelled "not yet verified by an expert"; plus the DFPD limit 17 %
```

**`storage`**: how long and at what moisture to store (StorageRule, with cautions on any protectant).
```python
ask("storage", {"crop": "crop:rice", "state": "state:33", "purpose": "purpose:seed"})
# asks "For how many months will you store it?" and branches: 8-9 months at 12-13 %, 12-15 months at 8-9 %,
# more than 15 months below 8 % (TNAU p. 75), all labelled unverified
```

**`harvest_readiness`**: when to harvest and thresh (HarvestRule; Q12, Q14).
```python
ask("harvest_readiness", {"crop": "crop:rice", "state": "state:33", "purpose": "purpose:seed",
                          "duration_group": "medium"})
# 2 facts: harvest when 90 % of the panicles are golden yellow at 20 % moisture; thresh at 16-17 % (TNAU p. 74)
```

**`threshold`**: when a pest is bad enough to act (PestThreshold; Q8). Needs `pest`.
```python
ask("threshold", {"crop": "crop:rice", "state": "state:33", "pest": "pest:brown_planthopper",
                  "observations": {"spider_count_per_hill": 0}})
# 1 fact (TNAU p. 64) with its clauses, labelled unverified
```

**`quality_check`**: will the procurement centre accept the paddy (QualitySpec; Q19). National, so it answers in any state.
```python
ask("quality_check", {"crop": "crop:rice", "state": "state:5", "commodity_form": "paddy", "quality": {"moisture": 18}})
# 18 approved DFPD limits (p. 6), each with a pass/fail/unknown check; verdict "fail" on moisture (limit 17 %)
```

**`varieties_for`**: which variety to sow (VarietyRecommendation; Q1).
```python
ask("varieties_for", {"crop": "crop:rice", "state": "state:5", "zones": ["zone:uk_tarai_bhabhar_plain"]})
# 1 approved fact (GBPUAT p. 1); values["recommends"]: 16 varieties as {"id", "name"}
```

**`sowing_window`**: when to sow the nursery, sow or transplant (SowingWindow; Q2). One answer slot per operation.
```python
ask("sowing_window", {"crop": "crop:rice", "state": "state:5", "zones": ["zone:uk_mid_hills"],
                      "systems": ["system:irrigated"]})
# 2 approved facts (GBPUAT p. 1): nursery 1-15 May, transplanting 16-30 June; never the high-hills windows
```

Varieties and sowing windows never cross state lines: a farmer outside Uttarakhand gets "No local guidance available", never another state's varieties.

### Uttarakhand farmers get Tamil Nadu advice for drying, storage, harvest and thresholds

The graph has no Uttarakhand source for these four. For `state:5`, `drying_target`, `storage`, `harvest_readiness` and `threshold` therefore fall back to the Tamil Nadu (TNAU) facts: the answer's `scope` is `fallback`, and every served fact carries the label **"From a Tamil Nadu source"** besides "not yet verified by an expert". The agent must show that label with the advice. Run on the main database on 2026-10-24, for a Tarai farmer drying grain:

```python
ask("drying_target", {"crop": "crop:rice", "state": "state:5", "zones": ["zone:uk_tarai_bhabhar_plain"],
                      "purpose": "purpose:grain"})
# scope "fallback", asks [], 1 slot:
#   DryingSpec, status extracted, values {"target_moisture_pct_max": 12.0},
#   labels ["not yet verified by an expert", "From a Tamil Nadu source"],
#   citation source:tnau_agriculture_2020, PDF p. 39 (printed p. 27)
# procurement_moisture: the DFPD paddy moisture limit 17.0 (national, approved, no label)
```

The same context with the other three templates (storage `purpose:seed`; harvest_readiness `purpose:seed`, `duration_group: "medium"`; threshold `pest:brown_planthopper` with no spiders) also returned `scope: "fallback"`, every served fact labelled "From a Tamil Nadu source": storage 3 facts (and it asks the storage months), harvest_readiness 2, threshold 1.

## 5. What an answer contains

`ask` returns a dict:

| Key | What it is |
|---|---|
| `template` | the template name |
| `scope` | `local` (the farmer's own regions), `fallback` (another state's source; only drying, storage, harvest and threshold facts) or `none` |
| `asks` | questions to put to the farmer: `{"variable", "question", "policy"}`, e.g. `{"variable": "storage_months", "question": "For how many months will you store it?"}` |
| `slots` | the answer, one slot per distinct piece of advice: `{"branch", "facts", "disagreement"}`. `branch` says which answer to an open question the slot is for (`{"storage_months": ["8 to 9 months"]}`); `disagreement` is true when equally ranked sources give different values |
| `hidden` | facts and steps that matched but are not served, each with its `quote` and `reason` ("dose not yet verified by an expert", "outranked in its answer slot", "withheld: … unknown", …) |
| `notes` | remarks the agent may pass on (e.g. a storage term the source gives without months) |
| `message` | set when nothing is served: "No local guidance available" (no fact for this place), "No verified guidance available" (facts exist but none may be served) |
| `verdict` | `quality_check` only: `result` (pass / fail / unknown), `failed`, `not_checked`, `passed`, `grade_rules` |
| `procurement_moisture` | `drying_target` for grain only: the procurement moisture limit fact |

Each served fact in `slots[].facts` has `id`, `subtype`, `summary_en`, `labels`, `values` (the stored values, with `raw_*` holding the printed words), `steps` (each with `instruction_en`, `timing_raw`, `if` conditions still open), `hidden_steps`, `clauses` (thresholds), `conflicts`, `cautions`, `check` (quality_check) and a `citation`:

```python
{"quote": "...exact text from the source...", "pdf_page": 1, "printed_page": None, "source_title": "...",
 "source_id": "source:gbpuat_kharif_advisory_2020", "status": "approved", "verifier_score": 0.98,
 "missing_in_latest_run": False, "extraction_method": "table_parse", "transcription": None}
```

**How to show it to a farmer**
- If `asks` is not empty, ask those questions first (or show every slot with its `branch`, "if you store for 8 to 9 months: …").
- Show each served fact's advice with its citation: the source title and page, and the quote when the farmer wants to check. `printed_page` is the page number printed in the book (None when the page prints none); `pdf_page` is the PDF's page.
- Show every label next to the advice: **"not yet verified by an expert"** (an unreviewed fact), "checked automatically against the source", or "From a Tamil Nadu source" (a fallback answer for another state).
- Never show what is in `hidden` as advice; it is there for logging and review. Doses (fertilizer and pesticide amounts) from unreviewed facts are always hidden, and so is any step applying a pesticide whose registration has not been checked.
- With `disagreement: true`, show both values and their sources; don't pick one.
- If `message` is set and `slots` is empty, say so; don't fill the gap from general knowledge.

## 6. Language

The graph is in English: every quote, value, label and question is English, as printed in the sources. The agent may translate the advice into the farmer's language, but:
- quotes are shown unchanged, in the source's own words, never translated or reworded (a translation may be added beside a quote, marked as a translation);
- labels keep their meaning exactly: "not yet verified by an expert" must still say that no expert has checked it, and "From a Tamil Nadu source" that the advice comes from another state; a translation may not soften, drop or merge them;
- numbers, units and dates are carried over as they are (no unit conversion, no rounding).

## 7. Adding a new source, in short

The full rules are in `CLAUDE.md` (one section per stage); the order is fixed and each stage's output is checked by a person before the next.

1. **Register** the PDF: `registry/<source>.toml` (url, sha256 of the file, state, region scope, authority tier, edition, chapters). New PDFs go in `data/raw/` and are never committed. `uv run python -m kg.registry` checks it.
2. **Concepts first:** any state, zone, variety, pest or ingredient the source names that `concepts/` lacks is drafted in `concepts/proposed/` with its page quote, approved by a person, then moved into `concepts/`. Concepts are never created automatically.
3. **Convert** (`kg.convert`), **segment** (`kg.segment`), **tables** (`kg.tables`): check the converted text against the rendered pages; a scanned page whose OCR can't be trusted gets a hand transcription (`transcriptions/`).
4. **Extract** (`kg.extract prepare`, then a hand-run or a runner answers the prompt, then `kg.extract ingest`): the latest prompt is v6.
5. **Normalise, validate, verify** (`kg.normalize`, `kg.validate`, `kg.verify`): facts that can't be linked or read are held with their reasons; the verifier (Jev) scores code-built claims.
6. **Load** (`kg.load.facts`): run it twice; the second run must create nothing and leave the snapshot hash unchanged.
7. **Review:** a person checks every fact (`kg.review sheet`, or a hand-check page) and approvals are imported through the decisions file (`kg.review import`), then reloaded twice.
8. **Fixtures:** one farm context per question in `tests/query/fixtures/`, run live on `cropbot-test`.

## 8. Known limits and backlog

See `CLAUDE.md` for the details; in short:
- **Coverage is small:** one TNAU rice chapter (four sections), the DFPD paddy schedule, and the GBPUAT rice rows (2020). No wheat facts, no other crop, no Hindi source yet. Uttarakhand farmers get Tamil Nadu advice, labelled, for drying, storage, harvest and thresholds (section 4).
- **Almost all TNAU facts are unreviewed** (`needs_review` or `extracted`): their doses are hidden and descriptive facts carry the unverified label. The agronomist's review workbook (`data/review/expert_review_tnau.xlsx`) is waiting.
- **No pesticide is served:** every active ingredient's registration status is `unknown` until the CIB&RC list is loaded, and pesticide steps fail closed.
- **No auto-verification threshold** yet (the gold set is too small to calibrate one), so nothing becomes `auto_verified`.
- **Districts have no LGD codes** and there is no district → zone mapping: the agent asks plains or hills and the altitude (section 4).
- **Community edition is untested** for the dump: use Neo4j Desktop; test a Community load before any Community deployment (section 2).
- **Held facts:** Chetki Dhan and Jethi Rice (GBPUAT; no concepts for spring rice, upland or the direct-seeding type), and 11 TNAU facts (CLAUDE.md lists each reason).
- **Backlog:** the Jev claim lead-in should read "for irrigated rice", not "for the crop under irrigated"; prompt v6 shows the model no crop, so only a hand-run can tell other crops' rows in a multi-crop table; the open schema notes (v1.4-v1.6) and the proposed items in `CLAUDE.md`.
