# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project rules

- docs/schema_v1.6.md is the source of truth (committed 2026-10-24; the build is in progress, see "Schema v1.6 build")
  - Schema changes go in a new versioned file in this repo (`docs/schema_v1.7.md`, ...) and are committed.
  - The Claude Doc is a superseded draft and is never exported again. `docs/schema_v1.1.md` to `docs/schema_v1.5.md` are kept for history.
- use uv add for dependencies
- always MERGE on id; nothing is auto-corrected
- every number keeps its raw text; the LLM never converts units
- every fact needs a SourceSpan and an IN_REGION edge
- secrets come only from .env
- never create concepts automatically
  - The one sanctioned exception: Variety records pivoted from a book's variety tables (`kg/tables`). They are always needs_review, and facts linked to an unapproved Variety are needs_review too.
- new PDFs are never committed (books are recorded by URL and sha256 in the source registry instead)

## What this repo is

CropBot is a farm-advice bot. This branch builds its Neo4j knowledge graph: every agronomic fact becomes a `Recommendation` node with applicability edges, ordered Steps, runtime Conditions and a `SourceSpan` quote (see `docs/schema_v1.6.md`). The stages are defined in the schema's "Build pipeline" section: register → convert → segment → tables → extract → normalise → validate → verify (Jev) → load. Product context (post-harvest focus, pilot plans) is in `CropBot_Research_Brief.md`.

## KG phase closed (2026-10-24)

The KG-building phase is closed. Start with `docs/KG_HANDOVER.md` (what is in the graph, connecting, querying).
- **Main database snapshot:** `13c96aefbc1ee99265369282f5f0746446ef6a86795e24d319337855ff5c681d` (842 nodes, 1280 relationships). Sources: TNAU 113 facts (12 extracted, 101 needs_review; 11 held), DFPD 18 QualitySpec approved, GBPUAT 8 approved (2 VarietyRecommendation, 6 SowingWindow; 4 held).
- **Backups** (`backups/`, gitignored). The shared copy is https://drive.google.com/drive/folders/1JxrvL_QkruGKKS9QinPvpJGMPF_RY-6E?usp=sharing, in its "backups" subfolder (all 12 files, sizes checked against the local copies by the user): download only; don't delete or overwrite anything there (it is the only shared copy); ask Suryansh before changing it.
  - `neo4j.dump` (sha256 `edd99b47…`, 345,278 bytes), dumped with `neo4j-admin database dump neo4j` while the database was stopped with `STOP DATABASE neo4j WAIT`. The DBMS itself was not stopped: Neo4j Desktop runs it as a console process with no service, so `neo4j stop` doesn't apply, and killing it would be an unclean shutdown.
  - Restore check: the dump loaded into `cropbot-test` (`neo4j-admin database load … --overwrite-destination=true`, the database stopped then started) gives the same snapshot hash as main. The live tests have since emptied and reloaded `cropbot-test`.
  - One zip per gitignored `data/` folder, each entry count checked against the folder: `data_{raw,docling,extracted,units,tables,normalized,validated,verified,eval,loaded,review}_2026-10-24.zip` (3, 110, 74, 6, 9, 9, 6, 22, 1, 3, 29 files). With the dump, 12 files, 19,262,070 bytes; the list with sizes is in `docs/KG_HANDOVER.md`. `data/gold/` is committed.
- **The graph in the repo** (`kg_snapshot/`, 3bd94c1; `kg/export`, d320c2e): `nodes.jsonl` and `relationships.jsonl` (deterministic, sorted, all properties, DateTime as `{"$datetime": ISO}`), `manifest.json` and `neo4j.dump` (345,615 bytes; a re-dump of the same graph is not byte-identical, the JSONL is).
  - `uv run python -m kg.export write [--dump]`, `check`, `load --database <empty, non-home>`, `secrets`. `--dump` stops, dumps and starts the database, using `NEO4J_HOME` and `NEO4J_JAVA_HOME` (`.env.example`, names only).
  - Proof (2026-10-24): `cropbot-test` emptied and rebuilt from the JSONL alone gave the same snapshot hash as main (`13c96aef…`, `created_at` included), and the same counts by label and type and facts by source and status. No `.env` secret or key-like string in the files.
  - `.gitattributes` keeps `kg_snapshot/` byte for byte (`-text`); without it, autocrlf would break the manifest's sha256s on Windows checkouts.
  - **Workflow:** after any reload, `kg.export check`; only if it reports a change, `write --dump`, `secrets`, review `git diff kg_snapshot/`, commit. Never commit a routine re-export (decided 2026-10-24).
  - `kg.export load` refuses the home database by default, so a teammate's JSONL rebuild goes into a separate database (`CREATE DATABASE kg`, then `ask(..., database="kg")`). For a server with only the home database (Community, AuraDB Free), `load --database neo4j --into-empty-home` (added 2026-10-24) loads it only when it has 0 nodes and 0 relationships and must be passed explicitly. Tested on `cropbot-test` posing as the home database (`tests/export/test_live_export.py`); untested on Community or Aura themselves.
- **The agent's entry point:** `kg.query.ask(template, farm_context)` (`kg/query/ask.py`): a template name and a FarmContext or a dict; it returns the dict `kg.query.answer` returns and raises `AskError` for an unknown template, a bad context or missing `.env` settings. The 18 live fixtures go through it. Pick a template, never write Cypher.

## Environments and commands

There are two separate uv projects:

| Project | Python | Purpose |
|---|---|---|
| repo root (`pyproject.toml`) | 3.13 | Knowledge-graph pipeline: docling pinned to 2.140.0 (same as `extraction/` and the committed `converted/`), easyocr, neo4j, pydantic, python-dotenv, requests; pytest as a dev dependency |
| `extraction/` (`extraction/pyproject.toml`) | 3.12 | PDF → Markdown extraction. On Linux it pulls CUDA 13 torch for the team's GX10 (ARM64, GB10); it also adds easyocr, rapidfuzz, pypdf |

```bash
uv sync                                   # root environment
uv run python -m pytest                   # all tests (offline; none need Neo4j)
uv run python -m pytest tests/schema/test_rejections.py::test_rejected   # one test

uv run python -m kg.load.seed --check     # validate concepts/ without a database
uv run python -m kg.load.seed --counts    # node/relationship counts, no writes
uv run python -m kg.load.seed             # id constraints + MERGE concepts/ into Neo4j
uv run python -m kg.registry              # validate registry/ and check each PDF's sha256
uv run python -m kg.load.sources          # MERGE Source nodes and SUPERSEDES edges
uv run python -m kg.convert source:tnau_agriculture_2020                # full Docling conversion (cached)
uv run python -m kg.convert source:tnau_agriculture_2020 --pages 13-76  # trial run on a page range
uv run python -m pytest -m slow           # the real 2-page conversion test (skipped by default)
uv run python -m pytest tests/load/test_live_revisions.py --neo4j-test-db cropbot-test   # live revision rules (skipped without the flag)
uv run python -m pytest tests/query/test_live_fixtures.py --neo4j-test-db cropbot-test   # step 14 fixtures on the TNAU facts
uv run python -m kg.query drying_target --context tests/query/fixtures/q15_grain_drying.json --database cropbot-test
uv run python -m kg.segment source:tnau_agriculture_2020   # section units -> data/units/<id>/ (exit 1 on scope failures)
uv run python -m kg.tables source:tnau_agriculture_2020    # rice + wheat tables -> data/tables/<id>/, data/review/tables.csv
uv run python -m kg.extract report source:tnau_agriculture_2020   # extraction checks (see "Extraction")
uv run python -m kg.normalize source:tnau_agriculture_2020        # step 10 -> data/normalized/<id>/, data/review/proposed_concepts.csv
uv run python -m kg.validate source:tnau_agriculture_2020         # step 11 -> data/validated/<id>/, data/review/validation.csv
uv run python -m kg.verify source:tnau_agriculture_2020 --dry-run # step 12: claims and request sizes, sends nothing
uv run python -m kg.verify source:tnau_agriculture_2020           # step 12: asks Jev what is not answered yet
uv run python -m kg.load.facts source:tnau_agriculture_2020 --check   # step 13: build and check every row, no database
uv run python -m kg.load.facts source:tnau_agriculture_2020           # step 13: one write transaction
uv run python -m kg.load.facts --snapshot                             # hash of the whole graph (idempotency proof)
uv run python -m kg.export check                                      # kg_snapshot/ against the database, no writes
uv run python -m kg.export write --dump                               # only when the graph changed: kg_snapshot/ + dump
uv run python -m kg.export load --database cropbot-test               # rebuild an empty, non-home database from the JSONL
uv run python -m kg.eval.gold [--check]                               # frozen gold workbook -> data/gold/*.jsonl, unchanged
uv run python -m kg.eval source:tnau_agriculture_2020                 # step 15: data/eval/<id>/report.json, data/review/gold_*.csv
uv run python -m kg.review sheet source:tnau_agriculture_2020 --out data/review/expert_review_tnau.xlsx --precheck data/review/ai_precheck_notes.csv   # step 16 workbook
uv run python -m kg.review import data/review/expert_review_tnau.xlsx --check     # check a filled workbook, write nothing
uv run python -m kg.review import data/review/expert_review_tnau.xlsx [--database cropbot-test]
uv run python -m pytest tests/review/test_live_review.py --neo4j-test-db cropbot-test   # sample review, loads, rebuild

uv run --project extraction python extraction/extract.py --list   # registry check: included, duplicate, unregistered PDFs
uv run --project extraction python extraction/extract.py --all --source tnau_agriculture
uv run --project extraction python extract.py --all               # original MVP script
```

`requirements.txt` is a leftover; dependencies go in `pyproject.toml` via `uv add`. There is no linter or formatter configured.

`.env.example` lists the variable names. Two scripts check the connections:

```bash
uv run python scripts/check_neo4j.py                                          # prints the Neo4j server version
uv run python scripts/check_jev.py --save docs/jev_response_example.json      # sends docs/jev_example.md, prints the raw reply
```

`--save` writes the reply only if it is HTTP 2xx, valid JSON, and contains neither the key nor anything key-like. Otherwise the script writes nothing and exits with an error.

### Jev notes

- `docs/jev_example.md` holds the reference request, and `docs/jev_response_example.json` holds a real reply to it. The key is `BEATAPI_API_KEY` in `.env`.
- `"type": "noul"` is a yes/no question. Its returned value is the probability of "yes", e.g. `{"safe": {"noul": 0.86, "type": "noul"}}`.
- Every question in one call is evaluated independently against the same `state`, so batching all of a section's claims into one call is valid.

### Neo4j notes

Local development runs Neo4j 2026.09.0 Enterprise. Which edition to deploy is a team decision; the research brief recommends Community. Vector-index quantisation is decided when the indexes are built.

## Existing code and how it relates to the schema

**Two versions of `extract.py`.**
- `extract.py` (root) is the original MVP. It handles 4 fixed books, downloads them into `sources/pdfs/`, and produced the committed `converted/` and `out/` folders (docling 2.140.0, run on CUDA).
- `extraction/extract.py` is the improved version. It reads every PDF in `BooksData/` using `extraction/sources.toml`. It keeps bounding boxes and footnotes, avoids false crop matches ("lime", "gram") and detects byte-identical duplicates by sha256.
- Both convert with Docling and flatten the result into an item list: `{k: h|p|li|tbl|img, lvl, t, md, img, cap, pg, ...}`. From that list they split each book by crop into `out/<crop>_<source_id>.md`.

**The committed `converted/*.index.json` files are lossy.**
- They store no bboxes, no OCR confidence and no Docling JSON. Tables are Markdown strings only, and footnotes were dropped. So they cannot supply `SourceSpan.bbox` or `table_ref` (`#/tables/N`).
- The schema's convert stage needs the lossless DoclingDocument JSON. That means a new conversion.
- `kg/convert` does that conversion (see "Conversion" below). The full book is meant to run on the GX10.

**Heading structure is not in the heading levels.**
- 96–99% of Docling headings come out at level 1, depending on the book. The section hierarchy ("1.8.3.1.Seed rate") is only in the heading text.
- Numbering spacing is inconsistent, and some headings run into body text ("1.1.1. Wet nursery Nursery area").
- Unnumbered sub-headings ("Nutrient management") belong to the previous numbered heading.

**Page numbers are PDF page numbers, not printed page numbers.** The TNAU rice chapter starts at PDF p. 13, but the book's contents table says p. 1.

**`out/` (per-crop Markdown from the old `extract.py`) is not a pipeline input.**
- Its crop segmentation and page markers are known to be wrong.
  - In `tnau_agriculture`, the rice chapter is interleaved with false `carnation`, `banana` and `fieldpea` segments (`out/segmentation_report.md`).
  - Page markers follow headings only.
  - The files append "Other mentions" from unrelated chapters.
- Use it only as a cross-check or for reading. Extraction units come from `kg/segment`.

**`extraction/sources.toml` is the existing source registry.**
- It is keyed by file name and holds title, publisher, url, doc_type, a free-text region, OCR settings, page_range and include.
- It lacks the schema's fields: `state_id`, `region_scope`, `authority_tier`, `default_scope`, section overrides and a recorded `sha256`.
- `CROPS` in `extraction/extract.py` is a hand-written alias list. It can seed reviewed crop concepts and labels, but a script must not turn it into concepts.

**PDFs.**
- 51 PDFs (about 590 MB) are already tracked: `BooksData/`, `sources/pdfs/` and `data/raw/`. Leave them as they are.
- New PDFs in any of those folders are gitignored.
- `data/raw/AGRICULTURE.pdf`, `BooksData/AGRICULTURE.pdf` and `sources/pdfs/tnau_agriculture.pdf` are the same file (TNAU Crop Production Guide 2020).

**`Graph_Rag_try.py`** is a discarded prototype. It uses unconstrained `LLMGraphTransformer` on fixed-size chunks with hard-coded Neo4j credentials. It conflicts with the schema, so don't extend it.

**Soil Health Card scrapers** (`state_retrival.py`, `district_retrival.py`, `block_retrival.py`, `village_retrival.py`, `data_scraper.py`, notes in `cheetsheet.txt`):
- **Do not run or modify them.**
- They crawl soilhealth4.dac.gov.in.
- The research brief says to stop them because of the portal's terms of service.
- Their region IDs are portal-internal, not the LGD codes the schema uses.
- Live data stays out of the graph anyway (schema design principle 8).

## Pipeline layout

New pipeline code goes in the plain `kg/` package and runs as `uv run python -m kg.<stage>`. There is no build-system section and no `src/` layout.

```
registry/            one hand-written TOML file per book: url, sha256, state_id, region_scope, authority_tier, edition_year, default_scope, section scopes
concepts/            hand-curated concept and label files (crops, regions with LGD codes, pests, ingredients); the only way concepts are created
kg/
  registry/          load and validate the registry; check each PDF's sha256 against it
  convert/           Docling → DoclingDocument JSON in data/docling/<source_id>/ (gitignored)
  segment/           heading tree from the numbering text → one unit per section (heading path, text, tables, pages, scope)
  tables/            join tables split across pages, rotate variety tables, check header and row counts against the page
  schema/            Pydantic models mirroring the schema, plus fixed vocabularies (units, basis, condition variables)
  extract/           one LLM call per unit → facts with raw text and quotes
  normalize/         units and basis, ranges, linking names to concepts (exact, alias, embedding → proposals for review)
  validate/          exact quote match, every raw number appears in its quote, vocabularies, banned list, alternative-totals check
  verify/            Jev claims built from stored fields
  load/              constraints, MERGE writers, IN_REGION edges, revision rules
  conflicts/         CONFLICTS_WITH detection
  eval/              gold set, precision/recall per subtype, the 20 competency questions
scripts/             one-off checks (e.g. Neo4j and Jev connectivity)
tests/               mirrors kg/
data/gold/           hand-annotated sections (committed)
```

## Schema models (`kg/schema`)

- **Subtypes:** all 16 are modelled. The 9 first-slice subtypes and the other 7 from the v1.2 table (SeedRate, Spacing, SeedTreatment, IrrigationRule, DoseFormula, WeatherRule, QualitySpec) are in `ALL_SUBTYPES`/`FACT`.
- **Concept models:** Pest, Disease, Weed, ActiveIngredient (`reg_status` defaults to unknown and comes only from the CIB&RC list) and OrganicInput are modelled.
  - Their rows are drafted in `concepts/proposed/` (`PROPOSED_FILES`) and are not loaded until approved.
  - Fertilizer keeps `n_pct`, `p2o5_pct` and `k2o_pct` as properties. The schema's `other{}` (Zn, Fe, S, …) is stored as `(:Fertilizer)-[:CONTAINS {pct, raw}]->(:Nutrient)` edges. In the seed CSV it's the `contains` column, a JSON list of `{nutrient_id, pct, raw}`. Rows with TODO percentages are pending and get no edges.
- **Neo4j properties are never maps**, only primitives or flat arrays.
  - Anything map-shaped becomes edges, or flat properties when that's decided: `raw{}` → `raw_<field>`, `coefficients{}` → `coef_<name>`, Variety `cells{}` → opaque `cells_json`, `excluded_regions` → `excluded_region_ids[]` + `excluded_region_raws[]` (all built in step 13, `kg/load/facts.py`).
  - A concept's `edges()` gives (relationship, target label, target id, relationship properties) for the loader.
  - The loader refuses a node whose properties aren't primitives.
  - The loader MERGEs every node and edge and reports what each run created; a second run creates nothing.
- **`per_cent_nursery`:** value is the amount per one cent of nursery, and `area_cents` is the nursery area the source stated. "40 kg DAP per 20 cents" is value 2, area_cents 20.

## IDs and loading

- Every node label has a uniqueness constraint on `id`, including Step, Condition, ThresholdClause, Label and the 16 subtype labels (`kg/load/constraints.py`). Every write is `MERGE` on `id`.
- **Step, Condition and ThresholdClause IDs** are derived from their parent Recommendation's ID (`rec:<h>`): `step:<h>:<i>`, `clause:<h>:<i>`, `cond:<h>:<r | s<i> | c<i>>:<j>` (owner: the recommendation, step i or clause i). A changed value gives a new rec id, so new children.
- **Label IDs** are `label:` plus a hash of the concept ID, kind, language and NFC-normalised text (`kg.schema.ids.label_id`). Kind is part of the key, so the same text can be both an alias and a vernacular name.
- Labels are words farmers and books actually use. Scientific names go in `Crop.scientific_name`, never in a Label.
- Every concept has `name_en`, regions included (schema Conventions: "name_en on every concept").

## Concept seeds (`concepts/`)

- **Format:**
  - One CSV per node label, UTF-8 with a header row (`concepts/<label>s.csv`; file → model map in `kg.schema.concepts.SEED_FILES`).
  - An empty cell means null. Every row has `review_status` (`approved` | `needs_review`) and a `source` saying where its values came from.
- **Unknown values:** a row containing `TODO` anywhere is skipped and reported as pending. Never invent an LGD code or a value; write TODO.
  - The pilot state and all districts are TODO for now. District names and zones come from the TNAU rice variety table, but their LGD codes are unknown.
- **Validation before any write** (`kg.load.seed`):
  - ID prefixes;
  - duplicate IDs across all files;
  - references (`state_id`, `zone_id`, `maps_to`, label `concept_id`) must point at loaded nodes;
  - a LocalSeason needs `state_id`;
  - Season, Purpose and OperationType must equal the schema's closed lists.
- **needs_review concepts are loaded,** with `review_status: needs_review`.
- **`concepts/proposed/`** is for drafted rows awaiting review. They validate against the models (`PROPOSED_FILES`) but are not loaded and not used for linking until they're approved and moved into `concepts/`.
- **Step 10 rows** (approved 2026-10-20) are now in `concepts/`, all needs_review: 18 pests, 53 active ingredients, 7 organic inputs and their labels.
  - Active ingredients keep `reg_status: unknown`, which comes only from the CIB&RC list.
  - `name_en` uses the standard spelling, and the book's spelling is a label (chlorpyriphos, Tricyclozole, bromodialone, ethopenprox). The brand label Bavistin → carbendazim and "clayey soils" → `soil:clay` are approved.
  - Dicofol is `acaricide`; Bt, Beauveria and Pseudomonas are `biopesticide` (schema v1.3, approved 2026-10-20).
  - Labels approved later the same day: "Hispa/ spiny beetle" → hispa, "Earhead bug" → earhead bug, "saline soil condition" → `soil:saline`. "saline / sodic soils" is one label text on both `soil:saline` and `soil:sodic`; for soils, systems and seasons such a shared label links to all its concepts (`link_many`). Single-valued links still treat it as ambiguous.
  - Kept held by decision: "Zinc deficient soils", "direct sowing", "ADT 46", "synthetic pyrethroids".
  - Earhead bug's `scientific_name` is the book's wording, "Leptocorisa acuta and L. oratorius", so its table cell links.
  - **Fertilizer percentages are optional** (decided 2026-10-20). ZnSO4, FeSO4 and potassium nitrate (KNO3) load with blank percentages and a source note, so they link. The alternatives check skips any fertilizer without approved percentages.
  - **Schema v1.3 concepts** (approved 2026-10-20, all needs_review):
    - 17 Inputs (`concepts/inputs.csv`). KNO3 is a Fertilizer, not an Input; KCl links to `fertilizer:mop` through its label.
    - `ai_group:synthetic_pyrethroids`, with `MEMBER_OF` from cypermethrin, deltamethrin, etofenprox, fenvalerate and permethrin. All five are in IRAC MoA Classification Scheme v11.5 (February 2026), p. 8, group 3A.
    - Labels: KCl, KNO3, NaCl, HNO3, "rodent" → `pest:rat`, and the trap and perch names as printed.
    - Not seeded: "KKM" (unidentified).
- **Review rule for linking and loading (steps 10 and 13):**
  - Linking may use needs_review concepts, but any fact linked to a needs_review concept must itself be needs_review.
  - The rice and wheat crop rows are approved; their labels are still needs_review.
  - Fertilizer percentages with `review_status: needs_review` must not be used by the alternatives check until approved. All seven seeded fertilizers are needs_review.

## Source registry (`registry/`)

- **One TOML per book,** named after its ID (`registry/tnau_agriculture_2020.toml` ↔ `source:tnau_agriculture_2020`). The model is `kg/registry/model.py`.
- **`extraction/sources.toml` stays as it is.**
  - Carried over: title, publisher, url, language, rights_note, doc_type, note, OCR settings, page_range and crop (the last four in `[extraction]`).
  - `year` became `edition_year` + `edition_label`.
  - `region`, `include` and `season` were not carried.
- **`file` is the local path** and must match `sha256`.
  - The TNAU guide points to `data/raw/AGRICULTURE.pdf`.
  - The identical copies in `BooksData/` and `sources/pdfs/` serve the two extraction scripts.
  - A missing file fails validation; the error gives the URL to download from.
- **Validation fails on:**
  - a missing field;
  - an unknown or malformed region ID, or one outside the book's state;
  - a sha256 mismatch;
  - an unregistered `supersedes`;
  - a file name that doesn't match the ID;
  - `edition_year` not being the start year of `edition_label`.
- **What reaches the graph:** Source nodes and `SUPERSEDES` edges. Extraction settings and scopes stay in the registry.
- **`default_scope` rules and `section_scope` overrides** carry `status` (`proposed` | `approved` | `rejected`); only approved ones are used.
  - Sections are keyed by heading text plus PDF page range, because heading levels are unreliable.
  - Once segmentation exists, a section that matches zero units or more than one must fail loudly. Until then, `kg.registry.heading_matches` checks each section against the committed conversion.
- **TNAU:**
  - 2 approved default-scope rules, both section-scoped: per ha unless stated, p. 63; nursery area 800 m² per ha, p. 62.
  - 11 proposed region section scopes, in integrated farming systems, agrometeorology and sorghum.
  - 1 approved purpose section scope: "RICE - VARIETAL SEED PRODUCTION" (PDF pp. 73-75), `purposes = ["purpose:seed"]`. It quotes the heading on the rendered p. 73, so its units carry `purpose:seed` with origin `section`.
- **DFPD uniform specification, KMS 2026-27** (`registry/dfpd_uniform_spec_kms_2026_27.toml`, added 2026-10-22):
  - downloaded from the Odisha Food, Supplies & Consumer Welfare Department's site (the url), sha256 `19e85992…`, 14 pages, 4,173,951 bytes; `data/raw/*.pdf` is gitignored, so the PDF is never committed;
  - national: no `state_id`, `region_scope = ["country:in"]`, `authority_tier = 3` until the regulatory tier (v1.5 item A);
  - a state forward: Odisha letter No. 14453 dated 21/08/2026 (PDF pp. 1-3) forwarding DFPD letter F. No.8-1/2022-S&I (E-381310) dated 17.08.2026 (pp. 4-5) and its enclosures (pp. 6-14). Recorded in `notes`;
  - scanned, with an unreliable scanner OCR layer, so `ocr = "force"`;
  - one chapter per enclosure by its printed heading, all proposed: paddy p. 6, rice p. 7 (notes p. 8), TPDS issue standards p. 9, jowar p. 10, bajra p. 11, maize p. 12, ragi p. 13, minor millets p. 14, plus the two letters. Only p. 5 prints a page number, so `Chapter.printed_page` is optional (None = the page prints none) and still checked when given.
  - **Conversion (2026-10-22, CPU, 266 s): not usable for extraction yet.** 9 tables, 16 units in 10 chapters. In the paddy table the six limits are right, but the "Foreign matter" label is lost, the "Damaged, discoloured, sprouted and weevilled grains" label is garbled, the S.No column is empty, the footnote "* Damaged, sprouted and weevilled grains should not exceed 4%." is missing and the paragraph and N.B. text are cut. Maize has no values; rice rows 2-6 are garbage; the rice value-cut footnote loses its middle; '%' is often read as '9/o', 'c70', '96'. Side-by-side review: `data/review/dfpd_tables_review.html` (not committed). The minor-millets chapter heading was not found.
  - **The paddy schedule comes from a verified transcription, not OCR** (decided 2026-10-22): `transcriptions/dfpd_uniform_spec_kms_2026_27/p006.md`, transcribed from the 300 dpi render, `status = "proposed"` until the user checks it. The OCR conversion in `data/docling/dfpd_uniform_spec_kms_2026_27/` is kept as it is.
  - **OCR trials (higher dpi, other engines) are deferred** to the scanned and Hindi books on the GX10.
- **Pick an entry by id, never by position:** `kg.registry.read_entry(source_id)`. `read_registry()` is sorted by file name, so `dfpd_…` comes before `tnau_…`.
- **A `section_scope` has `regions`, `purposes` (`purpose:<id>`) or both.** A purposes-only scope leaves the unit's regions alone. Units carry `purposes` with origin `section`, and the model never sets a section-level purpose.

## Conversion (`kg/convert`)

- **Setup:** Docling 2.140.0 with EasyOCR and accurate TableFormer, ported from `extraction/extract.py` (`extraction/` itself is untouched).
- **Settings come from the registry entry's `[extraction]` table,** never from `sources.toml`.
  - `ocr = "auto"` uses `OcrMode.DEFAULT`: OCR runs only on layout regions without PDF text cells.
  - `ocr = "force"` uses `OcrMode.FULL_PAGE`.
- **Output in `data/docling/<source_id>/` (gitignored):**
  - `document.json`: the lossless DoclingDocument, with pictures as PNGs in `images/`;
  - `document.md`: a readable copy, one block per page, with `<!-- PDF p. N | printed p. M -->` markers and running headers removed;
  - `meta.json`: versions, settings, sha256, cache key, timing and OCR pages;
  - `report.json`.
- **Cache:** a run is skipped if `meta.json` has the same cache key (sha256 + Docling package versions + settings). `meta.json` is written last, so an interrupted run never counts as cached. `--force` re-runs anyway.
- **Trial runs** (`--pages a-b`) write to `trial_p<a>-<b>/` and never replace the full conversion.
- **The running-header filter** applies to the Markdown copy and segmentation only; the JSON is never filtered.
- **Tables are referenced as `table_ref = "#/tables/N"`** (the Docling `self_ref`).
- **Page numbers:**
  - `pdf_page` is always set.
  - `printed_page` comes from the registry's `printed_pages` runs (printed = PDF page − offset) and is null outside them.
  - The TNAU PDF has no embedded page labels; its runs were found from the printed number at the top of every page.

## Segmentation (`kg/segment`)

No LLM. Input: the full `document.json`, with running-header headings dropped.

**Chapters**
- They come from the registry's `chapters` list (63 entries drafted from the contents table, PDF pp. 3–5).
- A chapter starts on its PDF page. Its own heading there ("1. RICE (Oryza sativa L.)") is its title, never a section number.
- Segmentation uses every chapter for boundaries; extraction uses approved chapters only. RICE and WHEAT are approved (checked against the rendered contents table and chapter pages); the rest are proposed.

**The tree is rebuilt from heading numbers,** never from Docling heading levels.
- `1.8.3.1` nests under `1.8.3`. "1.8.3.1.Seed rate" is split into number and title.
- Each scheme (`1.`, `I.`, `A)`, `ii)`/`i.`, `a)`/`a.`) nests in the order it first appears in its context, e.g. "II. NURSERY PRACTICES" > "1. NURSERY PREPARATION".
- A child that arrives before its parent creates a placeholder, which the late parent fills.
- Body text like "4.11.Disease management: …" is promoted to a heading when its parent number exists.

**Unnumbered headings are inline sub-headings** of the numbered section above. Each item records its `subheading`. ALL-CAPS headings are the exception:
- right after another heading it shares a word with, a caps heading is that heading's subtitle ("1. TRANSPLANTED PUDDLED LOWLAND RICE" → "TRANSPLANTED RICE");
- otherwise it starts a major section at chapter level;
- numbering continues across a major section ("3." goes next to "2." even with "RAINFED RICE" in between).

**Registry fixes**, applied only when `status = "approved"`. Each is checked against the rendered PDF page before approval. Its text must be found **exactly once** on its `pdf_page`; otherwise segmentation stops with every problem listed and writes nothing.
- `[[heading_fix]]` `kind = "split"` (default): the heading `match` becomes `heading`, plus an inline sub-heading or a sub-section. A numbered sub-section ("I. SEASON AND VARIETIES") is placed by the numbering rules.
- `[[heading_fix]]` `kind = "restore"`: an item whose number Docling dropped (often a list item) becomes the heading as printed, e.g. "Harvesting" → "1.5. Harvesting". The heading must be a number followed by `match`.
- `[[reading_order_fix]]`: the items `first`..`last` on `pdf_page` move to just after `after`.
- `[[acknowledged_gap]]` (no status; added after checking the page): a numbering gap the book really prints, e.g. wheat has no "1." before "2. Morphological Description of COW(W) 1". It matches only the same chapter, section heading and missing numbers. The report lists it under acknowledged gaps, not open ones, and lists any entry that matches no gap as stale.

**Units**
- One unit per leaf section, plus an "intro" unit for a section with its own text before its first child.
- Fields:
  - `id = unit:<slug>:<hash of section_path and kind>`;
  - `source_id`, `chapter`, `section_path`;
  - `items` in order (ref, label, kind, text, `pdf_page`, `printed_page`, `subheading`);
  - `table_refs`, `picture_refs`, `pdf_pages`;
  - `regions` with origin `source`, or `section` from an approved section scope;
  - `purposes` (origin `section`) from an approved section scope, empty otherwise;
  - approved `default_scope` rules;
  - `approx_tokens` = characters ÷ 4, tables included. Units over 20,000 are flagged, which leaves headroom under the 64k request limit.
- No table stitching or pivoting here; that's step 8.

**Scope check:** every `section_scope` and every `default_scope` section, proposed or approved, must match exactly one section node (heading text equal, start page in range). Its rules apply to every unit under that section. A mismatch writes the outputs, prints FAILED and exits 1.

**Output:** `data/units/<source_id>/units.jsonl` and `report.json` (gitignored). The report lists:
- the largest units and units without text;
- headings that didn't parse;
- open numbering gaps, acknowledged and stale acknowledged gaps, placeholders, late parents, duplicate numbers, promotions;
- heading-like list items;
- every caps decision;
- items before a chapter heading, and chapters whose heading wasn't found;
- the scope checks.

## Transcriptions (`kg/transcribe`)

A hand-checked copy of one scanned page whose OCR can't be trusted (2026-10-22, pending schema v1.5 items 11-13).
```bash
uv run python -m kg.transcribe check source:dfpd_uniform_spec_kms_2026_27   # which transcriptions are used
uv run python -m kg.transcribe rehash <file>    # store the body hash; resets status to proposed
```
- **File:** `transcriptions/<source slug>/p<NNN>.md`, committed. A TOML header between `+++` lines: `source_id`, `pdf_page`, `pdf_sha256`, `rendered_dpi`, `transcribed_by`, `transcribed_at`, `status`, `checked_by`, `checked_at`, `body_sha256`, `notes`.
- **Body, exactly as printed:**
  - `# ` is a heading and `### ` an inline sub-heading (it stays in its section, like "N. B.");
  - a block of `|` lines is one table: header line, `|---|` rule, then rows with equal cell counts;
  - every other block is one text item. Blank lines separate blocks, and printed line breaks inside a block are joined with one space;
  - anything unreadable is `[illegible]`, never guessed.
- **The gate:** only `status = "approved"` with `checked_by`, a valid past-or-today `checked_at` and `body_sha256` equal to the body is used. Only the user approves.
  - Editing the body breaks the hash: `rehash` stores the new one and sets the file back to proposed.
  - A broken file, or an approved one failing a check (hash, PDF sha256, source id, file name), stops segmentation and tables; nothing is written.
  - A proposed or rejected one is listed in the segmentation report and changes nothing.
- **Downstream:**
  - **Segmentation:** an approved page's converter items are all dropped and replaced, in place, by the transcription's items (refs `tr:p006#/texts/<n>`, `tr:p006#/tables/<n>`, each with `transcription` = the file). The report lists `transcribed_pages` and `transcriptions_not_used`.
  - **Tables (step 8):** a transcription table is a ready-made part (header row first). The ruling rebuild and page check don't apply; review gets one "transcription" row.
  - **Extraction (step 9):** the unit renders as usual, so quotes and coverage are checked against the transcription text.
  - **Step 10:** `evidence()` sets `extraction_method = "manual_transcription"`, `transcription` and `transcription_sha256` when the quote was found in transcription items.
  - **Step 11:** the location check reads `tr:` table rows.
- **Tests:** `tests/transcribe/test_transcribe.py`. Approval is always simulated on a copy in a temporary folder.

## Tables (`kg/tables`)

No LLM. Rice and wheat chapters only for now (`--chapters`). Input: the full conversion plus `units.jsonl`.

**Merged cells:** rows are built from Docling's unique `table_cells`, so a cell spanning columns appears once with its `col_span`. Genuine repeats ("Straw | Straw | Straw") are separate cells and stay. The original cells are kept per part.

**Rebuild from rulings** (`kg/tables/rebuild.py`, approved 2026-10-21), before stitching, so a page-break merge continues the corrected cells:
- **Ruled cells:** the part's ruling segments (`check.rulings`) cut its box into a grid. Neighbouring grid units join unless one segment covers the whole edge between them, so underlines don't count.
- **Assigning words:** every page word (docling-parse, the text layer Docling read) goes to the Docling cell whose row and column sit over the word's ruled cell. A row's or column's position is the median centre of its one-span cells. Inside one ruled cell, the smallest Docling box holding the word decides.
- **Editing a cell:** Docling's tokens are aligned to the words in its box (difflib), and a word moves only as a block at the start or end of the cell. The receiving cell takes the same block, so every removed token lands somewhere. A span is narrowed when a ruled cell is narrower.
- **All or nothing per part:**
  - every character is conserved exactly, or Docling's cells are kept and the part is flagged;
  - a ruled cell with no Docling row or column over it keeps Docling's boxes and is flagged ("ruled cells with no Docling row or column …").
- **Output:** changed cells keep `docling_text` (and `docling_col`); `original_cells` in `tables.jsonl` are Docling's own. Each change goes to review as "rebuilt from rulings". `python -m kg.tables.rebuild <source>` prints the before/after diff; the rice/wheat diff is pinned in `tests/tables/fixtures/table_rebuild_diff.txt`.
- **Rice/wheat:** pp. 17, 34, 66, 69, 70 and 71 are corrected (see "Known issues" below). `varieties.jsonl` is unchanged.

**Stitching**, within a unit. B continues A when:
- B is on the next page;
- only tables lie between them;
- the widths match (equal grid widths, or equal merged widths when one part splits the label column).

Then:
- a first cell "Particulars" always starts a new table;
- a repeated header is dropped;
- otherwise B's first row is data, even if Docling flagged it a header;
- a "Particulars" row *inside* a table splits it, because Docling sometimes puts the end of one variety table and the start of the next in one table.
- a row split by the page break leaves B's first row with no first-column cell, or an empty one. It is merged into A's last row cell by cell in the same column, and only when every cell has a same-column cell to continue.
  - The merged cell keeps the piece in `continued_from`; the merge is logged and written to review as "row continued across page break".
  - Extraction renders such a row as `[#/tables/A row R + #/tables/B row S]`, and a quote in it records the pages of all its pieces.
  - Rice/wheat: 10 merges, among them hispa (`#/tables/56` r4 + `#/tables/57` r0) and WBPH (`#/tables/57` r4 + `#/tables/58` r0). Nine Variety traits are completed by them, e.g. "Seed source: Seed centre, TNAU," becomes "… TNAU, Coimbatore-3".

**Page check, per part, with docling-parse** (the same text layer Docling read):
- rows must equal the bands between horizontal rulings;
- each row must show the full grid width or the merged cell count;
- a merged cell must not have a vertical ruling inside it;
- each cell's text must equal the page words inside its box. Same words in a different order (superscripts, stacked lines) is counted, not flagged.

A part without rulings is "not verifiable". Every mismatch goes to `data/review/tables.csv`; nothing is corrected.

**Ruling checks on Docling's own cells** (`rebuild.crossings`, 2026-10-21). Each goes to review marked "resolved by the rebuild" or "not resolved":
- "crosses a row ruling": one drawn segment runs across the whole cell width, with words above and below it;
- "crosses a column ruling": the same, for the cell height;
- "span wider than its ruled cell".

Rice/wheat:
- 6 row crossings: #57, #60 (×2), #61 and #8 are resolved; #7 p. 16 is not resolved;
- 4 column crossings (#32): all resolved;
- 1 span (#8): resolved.

**Variety pivot:** a table headed "Particulars" gives one Variety per column. Values are aligned to the last N columns of each part.
- Mapped rows fill typed fields, with numbers keeping their `raw` text.
- Known descriptive rows become traits "Label: value".
- "Grain size (mm)" prefixes Length, Breadth and Thickness.
- Unmapped, empty, straddling or spanning cells go to review, and a spanning value is never copied to several varieties.
- IDs are `variety:<slug of the name as written>`. Possible duplicates are reported, never merged; merging and aliases are a human review decision.
- `kind = hybrid` only when the name says so.
- `duration_group` comes from the section heading. Varieties whose duration is nearer another group's reference are reported; the reference values come from the book's "Stages | Short (105) | Medium (135) | Long (150)" table.
- `crop_id` comes from the chapter entry, and only once the chapter is approved.

**COW(W)1 block (PDF p. 134):**
- The printed page has it inside "I. SEASON AND VARIETY", after the "3. WHEAT" heading. Docling read it before the heading.
- An approved `[[reading_order_fix]]` restores the order. Its table is pivoted (COW (W) 1, COW (W) 2), and each is flagged "Docling reading order: …" for review.
- Its text lines are listed in the report as context for step 9.

**Damaged by conversion (rice, pp. 23–26):**
- "Imp. White Ponni ADT (R) 46" is one name cell holding two varieties;
- `#/tables/23` merges two varieties' values into one cell across a ruling;
- CO 52's morphology rows straddle columns.

All of these are in review. Re-entering them by hand, or reconverting, is a review decision.

## Extraction (`kg/extract`)

No model is called from this repo. `prepare` writes the filled prompt, a runner answers it, and `ingest` checks and stores the answer:

```bash
uv run python -m kg.extract find    source:tnau_agriculture_2020 "Wet nursery"          # unit ids
uv run python -m kg.extract prepare source:tnau_agriculture_2020 --unit <unit_id> --model <name> [--prompt v2]
uv run python -m kg.extract ingest  source:tnau_agriculture_2020 --unit <unit_id> --model <name> --response <file>
uv run python -m kg.extract report  source:tnau_agriculture_2020 [--prompt v2]
uv run python -m kg.extract compare source:tnau_agriculture_2020 --unit <unit_id> --from v1 --to v2
```

`--prompt` defaults to the latest version, v4 (schema v1.4), since 2026-10-22 (v3 from 2026-10-21; see "Schema v1.4 build").
- The four units (8e1d, b879, e63c, f5b0) were hand-run under v3 by revising the v2 answers fact by fact; every changed value was written from the unit text and the v3 rules.
- C2#10/#11 now quote the printed order that the approved p. 74 reading-order fix restored, without `line_order_pairing`.
- **C2#4 (PDF p. 73) prints "80 µM" with U+00B5.** The PDF text layer, the conversion and the v2 answer all have µ. The first v3 answer had U+FFFD there: a typo made in the hand-run, because the PowerShell console showed µ as "�". It was re-run on 2026-10-21. Check text by code point (`python -X utf8`, `hex(ord(c))`), never by what the console shows.
  - The wrong run is kept in `v3/history/f5b06c9fd3f8.e33b29d52cdc.json`. Its `previous_run` points at itself.
  - The run before it, the first failed v3 f5b0 run (the old C2#10/#11 quotes), was lost. A `--force` re-run with the same cache key wrote its history copy over it, and no other copy exists. History names now include the run time (below).
  - The p. 73 `[[review_note]]` proposing to read "�M" as micromolar is rejected and kept, with its reason.
- **e63c re-run after the step 8 rebuild** (2026-10-21). The unit text changed: "Pymetrozine 50% WG 300g" moved from the WBPH row to the end of the BPH row. The v3 answer was revised in two places, and the previous run is kept in `v3/history/`:
  - e63c#35 (BPH) gains option 19, Pymetrozine 300 g per ha, and its quote ends with that line;
  - the WBPH Pymetrozine fact (old e63c#36, held for no operation) is removed.

  So **e63c facts after #35 are one lower than before**: the WBPH spray list is now #36, and the BPH resurgence caution #67 (was #68). 71 facts.
- "a week before harvest" and "second a week later" keep their words in `timing_raw`, with no offset: turning "a week" into 7 days would be a unit conversion.

- **Raw model** (`kg/extract/model.py`), separate from `kg/schema`:
  - all 16 subtypes with the v1.2 fields;
  - names, units and bases as printed ("DAP", "kg", "per 20 cents"), never IDs or canonical units, and numbers parsed with their printed text. Step 10 normalises and links.
  - Extra fields: `basis_inferred`, `basis_rule`, `quantity_ref`, `alt_*`, `condition_raw`, `unmapped`, `excluded_regions` {name, raw}, and one `quote` per fact.
  - A step's `operation` may be empty when no type fits.
  - A quantity's `basis` may be empty when none is printed and the section gives none.
  - Crop and the book's regions come from code, never the model.
- **Prompts** `kg/extract/prompts/v1.md` and `v2.md`, model-agnostic. `kg/extract/versions.py` says what each version's answer looks like, so stored v1 answers still check as v1.
  - Code fills `{{subtypes}}`, `{{vocabularies}}` (from `kg/schema/vocab.py`), `{{default_scope}}` (approved rules with their quotes) and `{{unit}}`.
  - Units are rendered as `[p.N] text`, `[p.N] ## Sub-heading`, and stitched tables as `[#/tables/N row R] cell | cell`. A row merged across a page break is `[#/tables/A row R + #/tables/B row S]`.
  - A test fails if a prompt's field reference and its version's fields disagree.
  - Never edit a prompt that has been used: make a new version.
- **v1:** a JSON list of facts; every step has `instruction_en`.
- **v2:**
  - **Envelope:** `{"facts": [...], "not_extracted": [{quote, reason}]}`, and every text line and table row must be quoted by a fact or listed (the coverage check).
  - **Flags:** `extraction_flags` from a fixed list: line_order_pairing, spans_table_rows, split_from_shared_line, shared_amount, target_from_heading, anchor_from_context.
  - **Table quotes:** a quote may be a passage within one cell.
  - **Purpose:** `purposes` only when the quote states what the produce is for. Seed before sowing is planting material, not a purpose, and a section's purpose comes from the registry.
  - **Numbers and units:** unit "count" for organisms, eggs or items with no printed unit; Indian digit grouping ("1,00,000" = 100000, `kg/extract/numbers.py`) with `raw` as printed.
  - **instruction_en:** no longer written by the model; code writes it later.
- **v3** (schema v1.3), same envelope and coverage as v2:
  - **Strength, mixing and share** on a quantity, as printed: `conc_value`/`conc_min`/`conc_max` + `conc_unit` ("%", "N", "µM") + `conc_raw`; `ratio_part` and `ratio_rest` (1 and 49, never added up; code computes the whole); `share_pct` + `share_raw`.
  - **Repeats:** `repeat_raw` holds the printed repeat words; code reads count and interval from the word table. Stated times ("15 and 30 DAT") are separate steps.
  - **New fields:** `min_moisture_pct` on StorageRule; `seedlings_per_hill_min`/`_max` on Spacing; `about` on Caution (the pest it names). `concerns` may name a class.
  - **Sampling** stays as printed in `sampling_unit` ("/25 net sweeps"); code parses count and object.
  - **Soil-test scope** ("Zinc deficient soils") is a condition `soil_Zn_rating == low`.
  - **Operations:** the seven new values. A list's introducing verb applies to all its options. A mixed "Dust/ spray" list takes each option's operation from its formulation code (D/DP dusting, G/GR/CG application, EC/WP/SC/WG/SL spraying, none → empty), flagged `operation_from_formulation`.
  - **Flags:** `scope_from_heading` and `operation_from_formulation`.
  - `kg/extract/versions.py` keeps each version's fields and flags apart: a v2 answer with a v3 field or flag fails.
- **Output** `data/extracted/<source>/<prompt version>/<hash>.json`, plus `prompts/` and `responses/` there (all gitignored). Unit IDs contain ':', so files are named by the hash.
  - Each file records the prompt version and sha256, `extraction_model`, the unit text sha256, the time, the raw answer, every fact and its check results.
  - Cache key: unit text + prompt version + prompt hash + model.
  - `ingest` refuses to replace an answer with the same key unless given `--force`.
  - Runs under different versions sit side by side. A new run of the same unit and version moves the earlier answer to `<version>/history/<hash>.<cache key[:12]>.<run time, UTC>.json`, recorded as `previous_run`.
    - The run time is in the name because a `--force` re-run keeps the cache key.
    - An existing history file is never overwritten: `ingest` refuses and writes nothing.
    - Files kept before 2026-10-21 have the old name without the time.
  - `prepare` does the same for an earlier prompt with a different key (`history/<hash>.<key[:12]>.md`; the key sits in `prompts/<hash>.key`). A kept prompt is rewritten only with identical bytes; anything else is refused.
  - **Prompt v4 candidates:**
    - the "Seed rate" target ("seed", from the sub-heading) should carry `target_from_heading`;
    - `method`, `observation` and maturity signs are copied verbatim from the quote (see step 11 check 9).
  - `compare --from/--to` takes a version (its latest run) or a run file. It matches facts by subtype and quote (then by one quote containing the other) and ignores `instruction_en`. Runs are labelled `<version>@<cache key[:8]>`.
- **Hand-runs:** the JSON answer is written directly from the rendered prompt; no template generates any field.
- **Checks here only:**
  - the answer parses into the raw model under its version, fact by fact;
  - each fact and not-extracted quote is found in the unit text after both are normalised (NFKC, soft hyphens, dashes, whitespace);
  - (v2) no text line or table row is left uncovered. Sentences outside every quote are listed as a warning only.
  - Code, not the model, finds the quote's page.
  - Failures are saved and reported, never fixed, and `ingest`/`report` exit 1.
  - Everything else is step 11.
- **Step 11 (validate, not built yet) must also:**
  - send every fact with `extraction_flags` to needs_review;
  - flag a quote found in more than one place in its unit. "Narrow bund maintenance (45 x 30 cms)" appears in both the rat row and the IPM module, so the location can't be told apart.
  - check a fact's `table_ref`/`table_row` against where its quote was found;
  - check numbers in quotes with `kg.extract.numbers` (Indian grouping included), plus vocabularies, alternatives and the banned list.

## Normalisation and linking (`kg/normalize`)

No model. Input: the latest run of every unit under the latest prompt version, `kg.extract.versions.LATEST` (v4); a run that failed step 9 stops it. Each raw fact either validates against `kg.schema.FACT` and goes to `data/normalized/<id>/facts.jsonl`, or is held in `held.jsonl` with every blocking reason. Nothing is forced or dropped.

- **Scope:**
  - **Crop:** the chapter's crop_id, only if the chapter is approved.
  - **Regions:** the unit's, with their origin. Text regions are linked; "other than X" is expanded by code into the state's other zones (`text_exclusion`).
  - **Purposes:** from the quote (origin text), merged with the section's (origin section). The origins are kept beside the fact (`purpose_origins`), because v1.2's FOR_PURPOSE has none.
- **Units and bases:** `kg/normalize/units.py`, code only. Every conversion is logged with its rule.
  - acre = 0.404686 ha, cent = 1/100 acre, quintal = 100 kg.
  - Nursery cents give `per_cent_nursery`: value per cent, `area_cents` as stated.
  - A bare "/kg" in a seed treatment, and "for one hectare", are read from context and send the fact to review.
  - `basis_rule` must be one of the unit's approved default-scope rules.
- **`quantity_ref`:** copied from the one earlier fact of the unit that gives the same target an amount, with `inherited: true`; zero or several such facts hold it. A fact inheriting from a held fact is held too (chains included) until its source validates.
- **Schema v1.3 fields, read by code** (`kg/normalize/units.py`; every reading is logged, anything unreadable holds the fact):
  - strength units: "%", "w/w" → pct; "N" → normal; "µM" → micromolar. Any other unit holds the fact;
  - `ratio_whole` = printed part + rest;
  - repeat words via the fixed word table in `kg.schema.vocab` (once/twice/thrice; daily/weekly/fortnightly) or printed digits ("4 times", "at 10 days interval"). "second a week later" holds;
  - sample sizes in `sampling_unit` ("/25 net sweeps", "/100 ear heads", "in 12 passes") → `sampling_count` + `sampling_object`.
- **Linking (v1.3):** APPLIES may link to `input:`; Caution `concerns` to `ai:` or `ai_group:`; Caution `about` (the pest it names) to a pest or disease. `extraction_flags` are kept on the fact. A v1/v2 raw `seedlings_per_hill` becomes equal min/max bounds.
- **Linking** (`kg/normalize/link.py`): exact canonical label, then an alias label, then a normalised match on name, slug and labels.
  - Last, for concepts with a `scientific_name`: a table cell that is exactly a known name (`name_en` or a label) followed by that scientific name, both normalised ("Stem borer Scirpophaga incertulas"). Anything else in the cell goes to review.
  - Nutrient symbols match exactly; "P" and "K" follow the NPK convention (p2o5, k2o) and go to review.
  - Generic targets ("Pest", "weeds", "rodent") don't link.
  - No embeddings yet (BGE-M3 isn't set up).
  - Unlinked names are listed in `data/review/proposed_concepts.csv`; no concept is ever created.
- **Held:** a fact is held for:
  - an unlinked required name or applicability (variety, season, system, soil, purpose, stage), since dropping the edge would widen the fact's scope;
  - a step with no operation;
  - a unit or basis with no canonical form;
  - a threshold sampling unit outside `Basis`;
  - a `fact_key` collision within the unit.

  An unlinked *step* or *clause* stage keeps its words in `timing_raw`/`raw`, and the fact goes to review.
- **`fact_key`:** a hash of the source, section path, subtype, linked applicability, identity (incl. Caution `about_ids`), step slots (order, alt group, option, operation, method, anchor, target IDs; method and anchor added for v1.3) and the quote's first passage ref. Values are excluded. With the v3 runs and the v1.3 concepts: 123 facts in, **100 validated, 23 held** (68 held under v1.2; 2026-10-21, after the step 8 rebuild's e63c re-run; 124/100/24 before it). Still held (a fact can have several reasons):
- 14 for a generic target ("Pest", "weeds", "disease");
- 12 for a step with no operation (advice like "avoid close planting", owl perches, options with no verb or formulation code);
- KKM (unidentified);
- the GLH resurgence caution: "GLH, Nephotettix virescens" doesn't match the seeded three-species scientific name;
- "direct sowing";
- ADT 46.
- **Generic words:** a generic target links only through an approved label ("rodent" → `pest:rat`); without one it holds.
  - Identity covers pests, targets, kind, concerns, control class, dose basis, DryingSpec `storage_term_raw`, and every condition of the fact (variable, op, raw).
  - There is no sentence position; facts that still collide stay held. `id` is `rec:` plus a hash of the key and the values.
- **Status:** needs_review for any of:
  - an extraction flag;
  - basis_inferred, or a basis read from context;
  - an inherited amount;
  - an exclusion;
  - a needs_review concept or label;
  - the NPK convention;
  - an unlinked stage.

  Otherwise `extracted`; never approved.
- **Code-written fields:** `instruction_en` is written by code. `SourceSpan.extraction_method` is `table_parse` for table facts, `ocr` on OCR pages, else `native_text`; `bbox` is not filled yet.

## Validation (`kg/validate`)

No model. Input: the facts step 10 validated (`data/normalized/<id>/facts.jsonl`) and the step 9 runs they came from. Each check returns pass, fail or skip with a reason.
- **Rules:** a failure only adds a review reason. `extracted` becomes `needs_review`; nothing is fixed and nothing becomes approved (step 12, Jev, decides `auto_verified`).
- **The checks:**
  1. **quote_location:** the quote is found exactly once in its unit, and `table_ref`/`table_row` is where it was found. Either piece of a merged row counts.
  2. **raw_numbers:** on the step 9 fact (printed values, before conversion), every raw text is in the quote and every number is printed in its raw text. Indian grouping and number words up to twelve count; interpretations such as "a week" = 7 fail.
  3. **value_ranges** (approved 2026-10-20):

     | Field | Range |
     |---|---|
     | Harvest moisture | 10–30 % |
     | Threshing moisture | 10–25 % |
     | Drying target, storage max moisture | 5–20 % |
     | Storage months | 0–60 |
     | Offsets | ±180 days, ±72 hours |
     | depth_cm | 0–20 |
     | Nutrients `per_ha` | ≤ 500 kg |
     | Fertilizers `per_ha` | ≤ 1000 kg |
     | Organic inputs `per_ha` | ≤ 25 t |
     | `per_kg_seed` | ≤ 20 g or ml |
     | `per_cent_nursery` | ≤ 50 kg (organic inputs ≤ 100 kg) |
     | Active ingredient per ha | ≤ 3 kg a.i. (dose × formulation %, ml read as g) |

     A dose with no formulation % is skipped with that reason.
  4. **alternatives:** fertilizer-only alternatives agree within 15 % on N, P2O5 and K2O, using **approved** Fertilizer percentages only. Without them it skips with a review reason.
  5. **ingredients:** every applied active ingredient must be `registered`; unknown, restricted, banned and not seeded all fail (fail closed). A Caution's `concerns` aren't checked.
  6. **review_kept:** a fact with flags, an inferred or context basis, an inherited amount, an exclusion or any step 10 review reason must be `needs_review`.
  7. **range_narrowed:** a value stored as one bound (or equal bounds) that is an end of a range printed in its raw text fails with "printed range stored as a single bound". It covers every raw field, quantity, step offset and condition, and the value is never changed.
     - A pair is `X_min`/`X_max` or, since 2026-10-21, `min_X`/`max_X` (StorageRule `min_`/`max_moisture_pct`). Before that fix the check failed C2#22/#23 under v3 although both bounds were stored.
     - TNAU: nothing fails. Rice seed storage "12 - 13 %" and "8 - 9 %" (C2#22, #23) keep both bounds.
  8. **lost_glyph:** any stored text on the fact or its step 9 fact containing U+FFFD fails. TNAU: none. Run by hand over the kept history run, it catches the v3 C2#4 typo; step 11 itself reads only the latest runs.
  9. **printed_text:** on the step 9 fact, every text the extraction copies from the book appears in its quote (normalised, not inside a longer word or number).
     - **Fields checked** (extended 2026-10-21; first only quantities):
       - applicability lists and excluded regions;
       - recommends, pests, targets, concerns, about and `unmapped` phrases;
       - structure, storage term, coefficients, criterion;
       - step stage and method;
       - each quantity's target, unit (not prompt v2's placeholder "count"), strength unit, formulation, water and printed basis (not a rule's or an inferred one);
       - clause observation, unit, sampling unit and stage;
       - maturity signs.
     - **Also accepted:** the fact's own table row (a table fact quotes a passage of one cell; its pest is the row's first cell), and the sub-heading for a fact flagged `scope_from_heading` or `target_from_heading`.
     - **Case:** a difference only in case ("Soak"/"soak") passes and is counted in `case_only`.
     - **Prompt v3 asks** for `method`, `maturity_signs` and `criterion` only as "a short phrase"; a failure there says so.
     - **TNAU, all 124 step 9 facts (held included):** 37 fail and 63 texts pass on case only. No validated fact changes status; all were already needs_review.
       - 23 reworded methods ("treat and soak", "release Trichogramma japonicum", "pre-storage seed treatment");
       - 1 paraphrased maturity sign (8e1d#1 "dehusked rice is clear and firm (hard dough stage)"; p. 39 prints "If the rice is clear and firm, it is in hard dough stage.");
       - 11 generic "Pest" targets the book doesn't print (all held);
       - 5 observations ("leafhoppers" in e63c#17's four clauses; e63c#15 "seedlings with rolling of the first and second leaves");
       - the earlier 9: b879#0–3 "seed" (from the "Seed rate" heading), f5b0#9–11 N/P/K (from "NPK"), e63c#43 Notchi/Ipomoea, e63c#53 Pseudomonas (now e63c#42 and #52).
       - These counts are from before the e63c re-run. After it, the validated facts fail printed_text 20 times, the same facts as before: e63c's reworded methods are now #37, #43, #57 and #58.
     - **Prompt v4 candidates:**
       - copy `method`, `observation` and maturity sign text verbatim from the quote (decided 2026-10-21);
       - never write a generic "Pest" target.
  10. **scope_in_unmapped** (approved 2026-10-21): an `unmapped` phrase of the step 10 fact that looks like scope means the fact as stored applies more widely than the book says.
     - **Patterns:** `kg.schema.vocab.SCOPE_IN_UNMAPPED`, case-insensitive regexes:
       - variety: "for (word) hybrids/variety/varieties", "short/medium/long duration";
       - area: area(s), endemic, prone, region(s), zone(s), delta, tract(s), district(s);
       - condition: when, if, unless, "depending on", only, soil(s);
       - moisture: a number + % or "per cent" + moisture.
     - **Never scope:** a phrase starting with "especially" (e63c#5 "especially in BPH and leaffolder prone areas/seasons" applies everywhere).
     - **A failure:**
       - adds the review reason "scope in unmapped: served scope would be wider than printed" (exactly this text; the phrase and its kind are in the check's detail);
       - stores the phrases on the fact as `scope_in_unmapped` (a list; outside `value_key`);
       - makes the fact needs_review.
     - **TNAU:** 6 validated facts fail:
       - b879#3 "for hybrids";
       - b879#14 "depending on the height of the seedlings" (kept blocked by decision);
       - b879#19 "when the seedlings are to be pulled out in 20-25 days …";
       - e63c#9 "In BPH prone areas/seasons";
       - e63c#17 "in tungro endemic area";
       - e63c#56 "submergence of recommended level during critical periods only" (was extracted).

       f5b0#21 "at 10 per cent moisture content" would fail too, but it is held at step 10. The rule covers all six gold rows judged "gold" (A5, A38, B35, C13b, C14, C15).
- **Review notes:** `[[review_note]]` in the registry is printed text on a PDF page plus a note, with a status.
  - Step 11 attaches an approved note to every fact whose quote contains that text on that page, as a review reason; the value never changes.
  - An approved note that matches no fact is reported as stale.
  - TNAU: the Fipronil note (p. 64) is approved. The two Imidacloprid notes (pp. 66, 67) are approved: "inconsistent units for the same product in the source: g/ha on pp. 287–288, kg/ha on pp. 66, 67 and once on p. 288".
  - A quote in a row merged across pages records every piece's page (step 9), so the WBPH row (pp. 66–67) matches both Imidacloprid notes. Identical note text is listed once per fact.
  - A rejected note keeps its entry and gets a `reason`. TNAU p. 73 "80 �M" is rejected: it was based on a U+FFFD typo in the hand-run answer, and the PDF text layer prints µ.
- **Known source typos** (checked on the rendered pages 2026-10-20): "Fipronil 80%WG 50- 62.5 kg" (PDF p. 64) and "Imidacloprid 70% WG 30-35 kg" (pp. 66, 67) are printed in kg. The same Fipronil product is printed as "50-62.5 g" on p. 65. Extraction and normalisation keep the book's kg, check 3 fails them, and they go to review as suspected typos.

## Verification with Jev (`kg/verify`)

Input: the step 11 facts (`data/validated/<id>/facts.jsonl`). The URL and model are read from `docs/jev_example.md`; the key comes from `BEATAPI_API_KEY` in `.env` and is never printed or stored.
- **Claims** (`kg/verify/claims.py`) are built by code from the stored fields; no model writes them.
  - One yes/no claim per step and value, per threshold clause, per moisture, months or depth field, and per ingredient a Caution concerns.
  - Amounts are restated in the book's terms: `per_cent_nursery` becomes value × `area_cents` "per 20 cents of nursery".
  - Wording follows the book:
    - names are as printed, read from the step 9 fact ("super phosphate", "chlorpyriphos", "N"), never `name_en`. Applicability lead-ins (purpose, soil, variety) still use concept names.
    - a condition with raw text is rendered by that text ("in the absence of predatory spider").
    - "at most", "below", "at least" and "more than" appear only when the field's printed raw has a bound word, and the inclusive flag picks which. "12%" is "to 12%".
    - a step's `condition_raw` covering several products, or a fallback option, stays with the whole step: "the alternative to DAP, if not readily available, is urea 16 kg and super phosphate 120 kg per 20 cents of nursery".
  - Timing comes from anchor and offsets, else the stored `timing_raw`. Applicability is a lead-in ("for medium duration varieties grown for seed").
  - Untimed steps fall back to "the advice includes <operation>: <method>".
  - Schema v1.3 claims:
    - a strength joins the name ("KCl 1% is applied");
    - a ratio or share stands in for the amount ("at 1 part with 49 parts", "at 50% of the dose");
    - repeats use the word table's words ("thrice at weekly interval");
    - fact-level conditions join each step claim;
    - StorageRule gives "12 to 13%" when both moisture bounds are stored;
    - Spacing claims seedlings per hill, row x plant spacing and hills per m²;
    - thresholds use "per 25 net sweeps";
    - a Caution names its ABOUT pest ("… for BPH").
  - A fact with no claim (the two cautions with no `concerns`, and the saline Spacing with no values) is marked "human review required: no code-built claim" and can never be auto_verified.
  - The key is `c_` + hash(fact_key + claim).
- **Controls:** 60 deliberately wrong claims (approved 2026-10-21 for step 15; there were 5 before). Keys are `x_…`; they're excluded from scores and reported separately, with their `control_kind`.
  - **Kinds:**
    - `number`: one number ×2, or +10 points for a percentage;
    - `unit`: kg↔g, l↔ml, t→kg on the first quantity;
    - `pest`: the fact's pest, target or ABOUT is swapped for the first seeded pest that no line of the unit pairs with the fact's products, concerns or observations (names, labels and scientific names compared with spaces ignored).
  - **Selection:** the kinds take turns, each going round-robin over the units, so TNAU has 20 of each, sent in 3 requests.
  - **Never used:** a number or unit control whose changed words (with a neighbouring word, "60 kg") the unit prints, because it could be true there. Every seeded pest is printed somewhere in unit e63c, which is why pest swaps use the line check.
  - **TNAU P(yes):** number at most 0.10 and pest at most 0.09. Unit swaps go up to 0.66: 4 of 20 are ≥ 0.5, all ml → litres on sprays.
  - After the e63c re-run (all 199 e63c claims asked again, since the unit text is part of the key): number at most 0.14, pest 0.09, unit 0.60, with 2 unit swaps ≥ 0.5.
  - The new BPH Pymetrozine claim: P(yes) 0.98.
  - **Backlog** (recorded 2026-10-21, not done): `_changed` changes `max_moisture_pct` but never `min_moisture_pct`, so a StorageRule with only a lower moisture bound gets no number control. No TNAU fact has only a lower bound.
- **Requests:** one per unit, with the unit text exactly as step 9 rendered it as the state and all pending claims as `noul` questions (P(yes)).
  - A request is split only past an estimated 60k tokens (characters ÷ 4 × 1.2).
  - `--dry-run` writes `claims.jsonl` and sizes and sends nothing.
- **Queue and cache** (`data/verified/<id>/`, gitignored):
  - Answers are appended to `answers.jsonl` as they arrive, keyed sha256(unit text + claim + model). A re-run sends only unanswered claims.
  - 429, 5xx and timeouts back off (2, 4, 8, 16, 32 s, or `Retry-After` if longer), then stop with the queue kept.
  - The free tier (`jev-1.14-free`) answers 429 with `retry-after: 60` to a request sent soon after the previous one (first real run, 2026-10-20). Plan for about 1 request per minute.
  - Every try, 429s included, is logged in `requests.jsonl` and printed: HTTP status, latency, rate-limit headers, the names (never the values) of all response headers, and, once known, stored, usage, missing and extra keys.
  - Raw responses are stored only if they're valid JSON with no key or key-like string.
- **Per fact:** `verifier`, `verifier_score` (the lowest P(yes) of its non-control claims), and its claims with P(yes) and the response file.
- **Threshold:** `auto_verified_threshold` in `config/verify.toml` has **no default**. Without it nothing becomes auto_verified; calibration is step 15. With it, only an `extracted` fact with claims can become auto_verified; needs_review stays needs_review.

## Loading facts (`kg/load/facts.py`)

Step 13. Input: step 12's facts (status, verifier), step 11's (the fact, review reasons), step 10's (purpose origins) and step 8's `varieties.jsonl`. Held facts are never loaded. `--check` needs no database; a load is one write transaction, so a refusal writes nothing. Report: `data/loaded/<id>/report.json` (gitignored).
- **Writes:**
  - `(:Recommendation:<Subtype>)` with the core and subtype fields, `raw_<field>`, `review_reasons[]`, `verifier`, `verifier_score`, `verifier_claims[]` + `verifier_claim_p_yes[]` (controls excluded), `verifier_notes[]`, `conflict_key`, `value_key`, and `created_at` set on create only;
  - Steps, APPLIES, ThresholdClauses and Conditions (WHEN);
  - FOR_CROP, `IN_REGION {origin}`, `FOR_PURPOSE {origin}` and the other applicability and identity edges (FOR_PEST, TARGETS, CONCERNS);
  - `EVIDENCED_BY` → SourceSpan → `IN_SOURCE` → Source (Source nodes are MERGEd from the registry first);
  - Variety records (`:Concept:Variety`, needs_review) with VARIETY_OF and EVIDENCED_BY.
- **Refused before writing:** a fact with no IN_REGION, SourceSpan or FOR_CROP (or failing the schema model); an edge to a concept not in `concepts/`; any non-primitive property, or a mixed-type array; one span id with different properties; a duplicate id; `approved` from code; an unanswered claim. During the write, any edge whose ends don't match aborts the transaction.
- **Revisions** (matched on `fact_key`):
  - same id: the node is kept, and a human status (approved, rejected) or `reviewed_by` is never overwritten; code statuses are refreshed;
  - a new id for a known fact_key: a needs_review node with `(new)-[:REVISION_OF]->(old)`, and the old node is left untouched (an approved one keeps serving);
  - every fact of the source not in this load gets `missing_in_latest_run = true`, never deleted. `superseded_by` stays reserved for a newer edition.
- **Conflicts:**
  - `conflict_key` = subtype + applicability + identity + step slots (order, alt group/option, operation, method, anchor, targets with formulation) + storage window; `value_key` = the values.
  - Same conflict_key and a different value_key (not on one REVISION_OF chain) → one `CONFLICTS_WITH {origin: "detected"}` per pair, smaller id → larger, and both needs_review. Detection runs over the whole graph, so other books compare.
  - Registry `[[conflict]]` (sides: subtype, pdf_page, quote) is for what detection can't find, e.g. across subtypes. Each side must match exactly one loaded fact, proposed or not; approved ones add `{origin: "review"}`.
  - TNAU: 0 detected. One approved entry (2026-10-20), the rice seed long-term storage conflict: DryingSpec 8-9 % (p. 74, C2#18) vs StorageRule more than 15 months at less than 8 % (p. 75, C2#24). It is one `{origin: "review"}` link, and C2#24 is needs_review.
- **Idempotency:** the first TNAU load created 336 nodes and 664 relationships. The second created none, and the `--snapshot` hash was identical before and after it. After the conflict approval it was the same: one relationship created, then a third load changed nothing.
- **Schema v1.3 reload of the main database** (2026-10-21):
  - no fact was approved, rejected or reviewed;
  - the seed load added the v1.3 concepts;
  - `--reset-source` deleted 56 facts, 149 Steps/Clauses/Conditions and 55 spans;
  - load 1 created 412 nodes and 872 relationships; load 2 created none, with the snapshot identical (`8fbf4e4d…`, 704 nodes, 1030 relationships);
  - 99 facts (10 extracted, 89 needs_review); one `CONFLICTS_WITH {origin: "review"}`, none detected.
- **C2#4 reload** (2026-10-21, no reset):
  - C2#4 (sodium nitroprusside 80 µM, P(yes) 0.95) is the only new fact; load 1 created 3 nodes and 9 relationships. Load 2 created none, with the snapshot identical (`c59e3e47…`, 707 nodes, 1039 relationships).
  - 100 facts: 12 extracted, 88 needs_review. C2#22/#23 became extracted with the check 7 fix. C2#24 is needs_review through the review conflict.
  - No property in the graph contains U+FFFD.
- **Step 8 rebuild reload** (2026-10-21, no reset):
  - The BPH fact e63c#35 has a new id (`rec:24266ffe…`) and a new fact_key, because option 19 is a new step slot. So there is no REVISION_OF.
  - The old BPH node `rec:2ddbd464…` is kept with `missing_in_latest_run = true`. It is needs_review, so it is never fetched.
  - Load 1 created 22 nodes (the fact, 20 steps, 1 span) and 44 relationships. Load 2 created none, with the snapshot identical (`aa9f3971…`, 729 nodes, 1083 relationships).
  - 101 Recommendations: 100 current (12 extracted, 88 needs_review), plus the missing one. No other status changed.
  - No U+FFFD anywhere; the 10 query fixtures still match.
- **scope_in_unmapped reload** (2026-10-21, no reset):
  - Load 1 created no nodes or relationships. It set `scope_in_unmapped` and the review reason on 6 facts, and e63c#56 became needs_review. The snapshot went from `aa9f3971…` to `e2b45a25…` (729 nodes, 1083 relationships).
  - Load 2 changed nothing, and the snapshot was identical.
  - 100 current facts: 11 extracted, 89 needs_review, plus the missing old BPH node. The 10 fixtures still match.
- **`value_key` excludes a Caution's `text_en`:** its wording, not a value. Two cautions against synthetic pyrethroids in other words don't conflict.
- **Schema v1.3 in the loader:**
  - `ABOUT` edges (Caution → pest);
  - `CONCERNS` may point at an AIGroup and APPLIES at an Input (both are `:Concept`);
  - `extraction_flags` and `review_notes` are fact properties;
  - `value_key` includes strengths, ratios, shares, repeats and sample sizes.
- **`--reset-source <id>`** (one-time, for v1.3's new fact_key, which changes every id):
  - deletes the source's Recommendations with their Steps, ThresholdClauses and Conditions, and the source's spans nothing cites any more. Varieties, concepts and the Source stay;
  - refused, deleting nothing, if any of its facts is approved, rejected or has `reviewed_by`;
  - tested live on `cropbot-test` (`tests/load/test_live_reset.py`); run once on the main database on 2026-10-21 for the v1.3 reload.
- **Live test database:** `cropbot-test` on the local Enterprise server. Neo4j database names allow no underscores. `--database` on `kg.load.facts` targets it. The live tests (`neo4j_test_db` in `tests/conftest.py`) refuse the home database (`neo4j`) and any name without "test", and empty the test database before they run.
- **Review queue** `data/review/missing_approved.csv` (gitignored): approved facts flagged `missing_in_latest_run`. They are still served, with the flag in their citation. It is rewritten by every load of the home database, never by `--database` loads.

## Query templates (`kg/query`, step 14)

Approved 2026-10-20. The agent calls `kg.query.ask(template, farm_context)` (2026-10-24), a thin wrapper over `kg.query.answer(driver, template, FarmContext)`, which returns a structured answer: scope (local | fallback | none), the questions to ask, answer slots with their facts, hidden facts and steps with reasons, notes, and a message. Writing the farmer-facing text is a later step. The Cypher is fixed per template (`kg/query/templates.py`, no LIMIT); everything else is in `kg/query/answer.py`.
- **Templates:**
  - `drying_target`: DryingSpec (Q15, Q16).
  - `storage`: StorageRule, with Cautions on its ingredients (Q17).
  - `harvest_readiness`: HarvestRule (Q12, Q14).
  - `threshold`: PestThreshold for `context.pest` (Q8).
  - `quality_check` (Q19, schema v1.5), `varieties_for` (Q1) and `sowing_window` (Q2, schema v1.6); see those builds.
- **Applicability:** a missing optional edge matches anything. A value the farmer hasn't given (purpose, variety, season, system, soil type, stage, duration group, storage months) is UNKNOWN: the answer asks and branches on the facts' values.
  - Storage terms without months ("short term") are never mapped to months.
  - A storage period between the source's windows (10 months between 8–9 and 12–15) gets a question back, not a guess.
- **Conditions:** three-valued, top-down (`kg/query/logic.py`), with each variable's `on_unknown` policy. Conservative unknowns withhold actions (Cautions still fire).
- **Ranking per answer slot:** a slot is subtype + identity + storage window or term + which values the fact gives + the branch. Within a slot, rank by region level, variety match, explicit season/system/soil/purpose matches, authority_tier, edition_year. The whole top-ranked group is kept; differing values are flagged as a disagreement, and CONFLICTS_WITH links are shown.
- **Visibility:**
  - approved is served;
  - auto_verified is labelled "checked automatically against the source";
  - extracted is treated exactly like needs_review (unreviewed). DryingSpec, StorageRule, HarvestRule, PestThreshold and Caution are shown labelled "not yet verified by an expert". Doses (any APPLIES), inferred bases and inherited amounts are hidden, and dose subtypes are hidden entirely;
  - a fact with `scope_in_unmapped` phrases (step 11 check 10) is hidden until a person approves it; auto_verified is not enough. It is listed as hidden with the reason and the phrases. **Cautions are never hidden by this rule** (approved 2026-10-21: a wider caution only warns more); they keep the review reason and the unverified label.
    - TNAU: a GLH threshold question now returns "No verified guidance available" with e63c#17 hidden.
    - The whole fact is hidden, although only its last clause ("2/hill in tungro endemic area") is narrowed; the extraction kept that clause's scope in the fact's `unmapped`.
  - rejected and superseded facts are never fetched, nor non-approved facts flagged missing.
- **Active ingredients fail closed:** a step applying an ingredient whose `reg_status` isn't `registered` is dropped, whatever the fact's status (approved 2026-10-20; stricter than v1.2, see the v1.3 list).
- **Cross-state:** only when the farmer's own regions return nothing, only for DryingSpec, StorageRule, PestThreshold and HarvestRule (labelled "From a <state> source"), plus QualitySpec and Caution (unlabelled). Others: "No local guidance available".
- **Citations:** every served fact carries quote, PDF and printed page, source title, status, verifier_score and `missing_in_latest_run`. Hidden facts and conflict partners carry their quote too.
- **Schema v1.3 in answers:**
  - StorageRule serves `min_moisture_pct` beside `max_moisture_pct`;
  - threshold clauses carry `sampling_count`/`sampling_object`;
  - the farm context has a `Zn` soil rating (`soil_Zn_rating`);
  - safety joins also reach Cautions that concern an AI group the step's ingredient is a `MEMBER_OF`.
- **Fixtures:** `tests/query/fixtures/*.json` hold a context and the expected answer: Q8 (spiders unknown / none), Q12 (seed medium / grain), Q14, Q15, Q16, storage months unknown, 10 months, outside Tamil Nadu (`state:test_other` is a placeholder, not an LGD code).
  - Facts are named by a quote snippet (plus `duration_group`, or `"exact": true`, where one quote contains another), never by rec id, so re-extraction doesn't break them.
  - All 10 match the v3 data (2026-10-21).
  - Q12 for grain changed with the data: the NaCl harvest-hastening spray (8e1d#3) now validates and applies to grain. It is an unreviewed dose, so the answer is "No verified guidance available" instead of "No local guidance available".
  - Rice seed storage C2#22/#23 are served with both bounds, 12–13 % and 8–9 % (`min_moisture_pct` beside `max_moisture_pct`), labelled unverified.

## Gold set (`data/gold`, step 15)

- **The frozen gold set** is `data/gold/gold_set_annotations_final.xlsx` (sha256 `e4214ccd…`, 2026-10-21). It is fixed outside the repo, and its Changelog sheet records every change from v3. **Never edit it.**
  - The first committed version (`d40725a2…`) had 11 rows shifted one column left (A25–A28, A30, A37, A44, B37, B42, C7, C8).
  - The current version moves them back, with 11 Changelog entries; no other cell changed (checked cell by cell).
- `uv run python -m kg.eval.gold` converts it to `data/gold/gold_{A,B,C,changelog}.jsonl` plus `gold_manifest.json`; `--check` compares the committed files and writes nothing.
  - **Nothing is changed:** one record per non-empty row with `_sheet`, `_row` (the Excel row) and every cell as stored. Strings are unstripped, numbers stay numbers, and empty cells are null.
  - **Refused:** a workbook with another sha256 (the hash is pinned in `kg/eval/gold.py`), any formula, and a value outside the header's columns.
  - **Reported, never fixed:** duplicate ids, rows with no quote, rows that look shifted, and columns with mixed types. The current version has none, apart from `step`.
  - **One output-only conversion** (approved 2026-10-21): `step` is stored as text in some rows and as a number in others. The jsonl files hold it as an integer, and each of the 28 conversions is logged in `gold_manifest.json`. A step that isn't plain digits is refused.
- **Contents:** A (wet nursery, 47 rows), B (main-field pest management, 35 rows; only the BPH rows are scored), C (harvest p. 39 and varietal seed production pp. 74–75, 19 rows). 8 rows are `Other`.

## Evaluation (`kg/eval`, step 15)

No model. Input: the latest step 9 run of each unit (held facts included), the step 10 and 12 outputs, and the gold jsonl. Output: `data/eval/<id>/report.json`, `data/review/gold_disagreements.csv` and `data/review/gold_unmatched.csv` (all gitignored). Approved 2026-10-21.
- **Atoms:** one gold row is one value, so each step 9 fact is split into atoms:
  - one per applied quantity;
  - one per field value (moisture, depth, spacing);
  - one per threshold clause, Caution concern and maturity sign;
  - one per step with no quantity;
  - the whole fact, when none of these apply.

  Atom ids use the step's position (`b879#4/q2.1`), because options share an order.
- **Matching:**
  - A candidate's quote contains the gold quote, or the reverse, or the two share 80 % of the shorter one's words. It must be on the gold row's page; another page is allowed only for a containing quote, which is listed as a page disagreement.
  - A candidate must also share a number or a name word (`input` + `action`) with the gold row.
  - Score = quote + 2 × numbers + name + other_values numbers + condition words + page. Pairs are taken greedily, one to one.
  - A BPH row never matches an atom that names a specific other seeded pest (the WBPH row's products).
- **Granularity**, listed and never counted as a miss or an extra:
  - a gold row naming two values ("FYM or compost");
  - one value split across facts ("short and medium duration");
  - a second value in `other_values` ("moisture: 20%");
  - a maturity sign inside the row's quote;
  - one atom holding several rows;
  - a row that is the method every step shares (B6, "Direct spray towards the base of the plants").
- **Context steps:** a step without a value, in a fact the gold set annotated, is that fact's context ("soak the seeds in water") unless a gold row names it. It is listed, not counted.
- **Scored rows:**
  - all rows of A and C, and only B's rows with the BPH pest marker;
  - `Other` rows and B's non-BPH rows (B38b, B39–B41) are scored apart;
  - a row matching a step 9 not-extracted entry gets strict and lenient recall.
- **Precision scope:**
  - A: unit b879;
  - B: e63c atoms naming BPH (whole words, so "WBPH" doesn't count), plus p. 63 Cautions whose quote names BPH;
  - C: 8e1d, plus f5b0's Harvesting, Threshing, Drying, Pre-storage seed treatment and Storage sub-headings.
- **Disagreements** are value, unit, basis, condition, alternative (row label and group structure), purpose, subtype, timing, page and granularity.
  - Equality uses only step 10's unit and basis tables (gold `per` is read with "per" in front; "not stated" = no printed basis) and exact normalised text.
  - Nothing is decided in code. Verdicts come back only from `data/gold/adjudications.csv`, decided by a person (committed).
    - **Columns:** gold_id, field, verdict (extraction | gold | both | unclear), note, atom, name, quote.
    - **A disagreement** is keyed by gold_id + field.
    - **An extracted atom with no gold row** is a row with field `extra`, no gold_id, and its name and quote. It is keyed by name and quote, not the atom id, which shifts on re-extraction. Judged extraction or both, it counts as correct: the gold set lacks it.
    - **Decided 2026-10-21:**
      - C16 page → extraction: extraction correct, gold page wrong (quote on p. 75);
      - the 16 concerns of the BPH resurgence list (e63c#68, now #67, p. 69) → extraction; gold incomplete.

      With these, precision found is 108/109 (B 43/43).
    - **All 127 adjudicated 2026-10-21** (`f1cbe33`). The categories from `data/review/gold_adjudication_prep.md` were applied to the current rows; each note names its rule.
      - **both:** list-intro-vs-alternatives, condition-same-words, advice-as-condition, the three timing categories, option-label-only, and the evidence items E1, E2, E3, E5, E6 and E7.
      - **gold:** condition-in-unmapped (A5, A38, B35, C13b, C14, C15).
      - **unclear:** biofertilizer-grouping (A15–A21, A45–A47), "ambiguous punctuation on p. 29; agronomist to decide".
      - **The extra 8e1d#1/m2** → gold: "paraphrase of printed text".
  - "Agree" stays a range while any verdict is "unclear": the lower bound counts unclear as not agreeing, the upper as agreeing. This holds for precision as well as recall.
  - **A granularity-covered atom takes the status of the gold row it is covered by** (fixed 2026-10-21, `0d0c6be`). Before, `precision_agree_lower` left these atoms out and printed 86/110.
- **Calibration:** facts matched to gold rows, by `verifier_score` cut-off (0.5–0.99), for three populations:
  - (a) all with a score;
  - (b) `extracted` facts only;
  - (c) their claims, each carrying its fact's label.

  The proposed threshold is the lowest cut-off whose Wilson 95 % lower bound on (b)'s precision (open disagreements counted wrong) is ≥ 0.90. If none qualifies, the report says "no threshold yet" with the gold rows needed. Nothing is written to `config/verify.toml`.
- **TNAU, first run (2026-10-21, nothing adjudicated):**
  - **Rows:** 101 gold rows, 90 scored.
  - **Recall:** found 89/90 (Wilson 95 % 94–100 %); pipeline 76/90 (13 found rows sit in facts held at step 10).
  - **Missed:** only B23 (Pymetrozine 50% WG 300 g, PDF p. 66). The unit's BPH row (`#/tables/57 row 3`) prints no Pymetrozine; the WBPH row does. Adjudicate against the PDF.
  - **Precision found:** 92/109 (76–90 %). A 41/41, B 27/43, C 24/25.
  - **Extras:** the 16 concerns of the BPH resurgence caution (e63c#68, "BPH, Nilaparvata lugens : acephate, carbofuran, …"), which have no gold rows, and one maturity sign of 8e1d#1.
  - **Disagreements:** 126 on 80 rows, mostly timing (44) and condition (40), e.g. the B list intro "spray any one of the following insecticides per ha" kept as a gold condition (18 rows).
  - **Threshold:** no threshold yet. Population (b) has 10 facts (1 correct, 9 open). Even if every open disagreement goes to the extraction, a lower bound ≥ 0.90 needs 35 facts above the cut-off, about 250 scored gold rows at today's 1.9 rows per fact and 26 % `extracted`.
  - **Controls:** none of the 60 at ≥ 0.7 (Wilson upper 6 %); 4 unit swaps at ≥ 0.5.
- **TNAU, after the step 8 rebuild** (2026-10-21; 2 verdicts recorded):
  - **Recall:** found 90/90 (96–100 %); pipeline 77/90.
  - **B23** (Pymetrozine 50% WG 300 g) now matches the BPH fact e63c#35. Its one disagreement is the list-intro condition, the same as the other 18 B rows.
  - **Precision found:** 109/110 (95–100 %). A 41/41, B 44/44, C 24/25.
  - **Disagreements:** 127 on 81 rows; 1 adjudicated.
  - **Threshold:** still no threshold. Population (b): 10 facts, 1 correct.
  - **Controls:** 2 unit swaps at ≥ 0.5, none at ≥ 0.7.
- **TNAU, all adjudicated** (2026-10-21; unchanged by the scope_in_unmapped rule):

  | Metric | A | B | C | All |
  |---|---|---|---|---|
  | Recall found | 40/40 [91–100] | 31/31 [89–100] | 19/19 [83–100] | 90/90 = 100 % [96–100] |
  | Recall agreeing | 28–38/40 | 30/31 | 16/19 | 74/90 = 82 % [73–89] .. 84/90 = 93 % [86–97] |
  | Pipeline recall | 37/40 | 27/31 | 13/19 | 77/90 = 86 % [77–91] |
  | Precision found | 41/41 | 44/44 | 24/25 | 109/110 = 99 % [95–100] |
  | Precision agreeing | 29–39/41 | 42/44 | 21/25 | 92/110 = 84 % [76–89] .. 102/110 = 93 % [86–96] |

  - **Wrong:** the six condition-in-unmapped rows (atoms b879#3, b879#19, e63c#9 k1 + k2, f5b0#21 q1.1–q1.3) and the extra 8e1d#1/m2.
  - **Unclear:** the 10 biofertilizer rows.
  - **Threshold:** none yet. Population (b) is 10/10 correct (Wilson lower bound 72 %); 0.90 needs 35 facts above the cut-off, about 255 scored gold rows.
  - **Controls:** 2/60 accepted at 0.5, both unit swaps.

## Expert review (`kg/review`, step 16)

Approved 2026-10-21. Only a person approves or rejects a fact, through the workbook below; code never does.
- **Workbook** (`kg.review.sheet`, `data/review/expert_review_<…>.xlsx`, not committed):
  - **Rows:** one per current fact. They are built from step 13's inputs (`kg.load.facts.build`); status, review reasons and Jev score come from the database. A fact not yet loaded, or flagged missing, stops the sheet.
  - **Order:** DryingSpec, StorageRule, HarvestRule, NutrientDose, SeedRate, Spacing, SeedTreatment, IrrigationRule, PestThreshold, ControlMeasure, Caution; then by PDF page.
  - **Instruction column:** the fact's code-built Jev claims as statements. Cautions without a claim show their extracted text, marked as such.
  - **Other columns:**
    - crop and scope (concept names);
    - values with their printed raw text;
    - the exact quote;
    - PDF page / printed page;
    - source, status and review reasons;
    - Jev score and unmapped phrases;
    - a hidden `row_hash`.
  - **Highlight:** the Unmapped cell is orange (`F4B183`) for a fact flagged "scope in unmapped". TNAU: the 6 facts of check 10.
  - **Reviewer columns:** the only unlocked cells (the sheet is protected, no password). They are decision (approve / reject / needs change), reason or correction, applies in Uttarakhand? (yes / no / not sure), reviewer name and date, with dropdowns and a date check.
  - **Guide:** "How to review" holds the approved guide text, including the two lines on unmapped conditions and on pesticide rows.
  - **Meta:** a hidden `meta` sheet names the source.
  - **AI pre-check (`--precheck <csv>`, 2026-10-22):** two locked columns, "AI pre-check" (OK / CHECK / FIX) and "AI note", just before the reviewer columns. FIX is red (`F8696B`), CHECK yellow (`FFEB84`), OK unfilled.
    - Notes are matched by fact_id. The sheet is refused if a note names no row, a fact_id repeats, a result isn't OK / CHECK / FIX or blank, or a note has neither a result nor a text; a differing review_no is only reported.
    - Since 2026-10-22 a row without a note keeps blank cells, and a note may have a blank result (an earlier note that no longer applies; no fill). The output counts both.
    - The guide has a line saying the column is a hint, not a decision.
    - The import never reads these columns, and a workbook without them still imports.
    - **TNAU:** `data/review/ai_precheck_notes.csv` (external AI pre-check of the v1.3 facts, not committed): 64 OK, 29 CHECK, 7 FIX. No fact or status was changed from it.
    - **v1.4 notes** `data/review/ai_precheck_notes_v14.csv` (not committed), from the mapping and the user's decisions of 2026-10-22: the 13 notes whose concern v1.4 fixed have a blank result and "Earlier AI note no longer applies (fixed in v1.4); not re-checked."; #9 and #40 are CHECK, "Purpose is now in the values but not in the instruction."; the other 85 keep their result and note. Result: 64 OK, 19 CHECK, 4 FIX, 13 blank with a note, 13 facts without a note.
  - **Scope column** (2026-10-22): starts with the fact's pests, targets and ABOUT pest; a ControlMeasure without a target shows "target: none (general practice)".
- **`row_hash`** (`kg.load.facts.row_hash`): fact id + quotes + `value_key` + applicability (regions, exclusions, duration group). The status is not part of it.
- **Import** (`kg.review.importer`; `--check` writes nothing).
  - **A row is refused, with its reason, when:**
    - its fact isn't current, or its hash changed (quote, values or scope);
    - the decision or the Uttarakhand answer isn't allowed;
    - a reject or needs change has no reason;
    - the reviewer name or date is missing or invalid, or the date is in the future;
    - the fact appears twice;
    - the fact already has a different decision. A re-review is a deliberate edit of the decisions file.
  - **No-ops:** a row identical to a recorded decision is "already imported", and rows without a decision are "not reviewed".
  - **Accepted rows** are applied in one transaction, then appended to `data/review/expert_decisions.csv`:
    - approve → `approved`;
    - reject → `rejected`;
    - needs change → `needs_review`, plus "expert: <note>" in `review_reasons`;
    - every decision also sets `reviewed_by`, `reviewed_at`, `expert_decision`, `expert_note` and `applies_uttarakhand`.

    The file is committed: `.gitignore` has `data/review/*` and `!data/review/expert_decisions.csv`.
  - **Never:** a correction never changes a value, and the Uttarakhand answer is only a property, never an IN_REGION edge (Uttarakhand has no seeded region).
  - **Report:** counts per decision and per subtype, and every refused row.
- **The loader re-applies the decisions file on every load** (`--decisions`, default the committed file), right after the MERGE. The MERGE rewrites `review_reasons`, so a needs-change note is added back each time.
  - A decision whose fact isn't in the load, or whose hash changed, is stale: not applied, listed in the report and, for the home database, in `data/review/stale_decisions.csv`.
  - A re-extracted fact with a new id is a needs_review REVISION_OF the approved one, as before.
- **Serving:** approval never bypasses fail-closed. A step applying an ingredient that isn't `registered` is dropped from an approved fact too (tested).
- **Live test** (`tests/review/test_live_review.py`, cropbot-test only). The sample sheet is filled by the test (reviewer "TEST SAMPLE") into a temporary decisions file; the test checks that the committed file is untouched.
  - Decisions: 8e1d#2 approve, f5b0#20 reject, b879#19 needs change (e63c#17 until v4 held it), e63c#35 approve.
  - Import, then a re-import (no-op), then two loads: nothing created, snapshot `16a61bad…` unchanged (704 nodes, 1038 relationships; v4 data, 2026-10-22).
  - Emptied and reloaded, the database gets the 4 decisions back; a second load changes nothing.
  - The approved grain-drying fact is served without the unverified label.
- **TNAU workbook:** `data/review/expert_review_tnau.xlsx`, regenerated from the main database on 2026-10-22 after the v1.4 reload: 113 rows, 4 orange Unmapped cells, the v1.4 notes. `import --check` on it: 113 not reviewed, 0 refused. No TNAU decision has been imported; the committed decisions file holds only the 18 DFPD paddy approvals (see "Schema v1.5 build").

## Scope rules for extraction and normalisation

- **The p. 63 per-ha rule applies only to its section.** Elsewhere, a dose with no stated basis gets `basis_inferred: true` and goes to review.
- **Exclusions ("other than Cauvery Delta", p. 34)** are recorded by the extractor as `excluded_regions` with their raw text.
  - Code, never the LLM, expands them into `IN_REGION` edges to the state's remaining zones, with `origin: text_exclusion`.
  - Such facts are needs_review.
- **Sub-zones with no concept** (old delta, new delta, "Western region") are not mapped. Scope the fact at the state level, put the phrase in `unmapped`, and set it to needs_review.

## Schema v1.2

The eleven changes that were pending here (two page numbers, raw text for every number, condition-only units, strict bounds, hour offsets, editions, prefixed lowercase IDs, the worked-example fix, `default_scope` as a list, exclusions, table cells in provenance) are now in `docs/schema_v1.2.md` (see its "Changes from v1.1").

Decisions on gaps that don't change the doc:
- `sowing_date`, `variety` and `purpose` are in the condition-variable registry only for their `on_unknown` policy. Applicability to a variety or purpose is always an edge.
- `soil_pH` is the only soil value variable; add others when a source needs them.
- Every NutrientDose step has `APPLIES` quantities, and a ControlMeasure has at least one Step.
- `CONFLICTS_WITH` is recorded on both facts. Conflict detection must never create duplicate links: one link per pair of facts, however often detection runs.

**Schema v1.3** (`docs/schema_v1.3.md`, committed 2026-10-20) now covers every item below, and it is built (2026-10-21). The lists below record why each change was made.

Found in the step 9 hand-run; until v1.3 is built, extraction keeps the phrases in `unmapped`:
- StorageRule needs `min_moisture_pct` (+ `_inclusive`), so "12 - 13 %" keeps its lower bound (it has only `max_moisture_pct` now).
- Repeat schedules ("thrice (at weekly interval from 37 DAT)", "twice, 15 and 30 days after transplanting") have no fields.
- A Caution cannot name the pest it is about (the resurgence lists, p. 69: "BPH, Nilaparvata lugens : acephate, …").
- `Spacing.seedlings_per_hill` needs a range (min/max), for "Shallow planting at 3 - 4 seedlings / hill" (p. 74).

Found in step 10; until v1.3, normalisation holds the affected facts with the reason:
- OperationType has no values for release (parasitoids), trapping, baiting, dusting or bund work, and Step `operation` is required.
- APPLIES has no target type for inputs that aren't nutrients, fertilizers, organic inputs or active ingredients: seed, biocontrol agents (Trichogramma), traps, salts, chemicals (HNO3, KCl, NaCl).
- No concentration or ratio quantities: "%" with no basis, "0.1 N", "80 µM", "1 part … with 49 parts".
- ThresholdClause sampling units outside `Basis`: "/25 net sweeps", "/100 earheads", "in 12 passes".
- `FOR_PURPOSE` needs `{origin}` (text or section). **Built ahead of v1.3** (approved 2026-10-20): step 13 writes `FOR_PURPOSE {origin}`, a list, since the quote and the section can both give the purpose (`["section", "text"]`).
- ActiveIngredient `use_class` needs an `acaricide` value (Dicofol, PDF p. 67); until then `use_class` is empty.
- **Active ingredients fail closed** (approved 2026-10-20, built in step 14): any step applying an ingredient whose `reg_status` isn't `registered` (unknown, restricted, banned, or not seeded) is dropped from answers. v1.2's "Safety joins" only drops banned and attaches a caution to restricted; v1.3 should adopt the stricter rule.
- Soil-test conditions as applicability: "Zinc deficient soils" (PDF p. 74) is a soil condition, not a soil type. The fact stays held.
- ActiveIngredient groups: "synthetic pyrethroids" (PDF pp. 63, 68) names a class of ingredients, not one. The cautions concerning it stay held.
- GrowthStage seeds for rice, needed for stage timing: "flowering", "tillering stage", "boot leaf stage", "vegetative phase", "from milky stage to grain maturity". Today these stay only in `timing_raw`/`raw`, and the fact needs review.
- Properties are never maps: Neo4j rejects them, which the 2026-10-20 seed load showed.
  - `Fertilizer.other{}` is now `CONTAINS {pct, raw}` edges to Nutrient.
  - Decided 2026-10-20 and built in step 13 (`kg/load/facts.py`):
    - `raw{}` on subtypes and Variety → flat properties `raw_<field>`;
    - DoseFormula `coefficients{}` → flat properties `coef_<name>`;
    - Variety `cells{}` → one JSON string property `cells_json`, opaque provenance that is never queried in Cypher.
  - The loader's primitive-property check stays, and each mapping gets a test.

Candidate for prompt v3: a flag `scope_from_heading` for applicability taken from a sub-heading rather than the quote. For example, the soil "saline soil condition" comes from the p. 74 sub-heading "Recommendation for planting under saline soil condition", and "Zinc deficient soils" comes the same way. v2 has no flag for this.

## Schema v1.4 build

`docs/schema_v1.4.md` (committed 2026-10-22) covers all 11 items below. Decisions taken with it:
- duration ranges for check 3: minutes 1–240, hours 1–72, days 1–60;
- word table: "in equal volume" → ratio 1:1, and "a week" → 1 with unit weeks (no conversion to days);
- `endemic_area` is a concept-valued condition, ask then branch. `disease:tungro` is drafted in `concepts/proposed/` for approval;
- "avoid …" advice becomes a prohibition Caution (prompt v4);
- the expert review waits for the v1.4 reload; afterwards the AI pre-check notes are re-mapped by quote, and the mapping is shown before the sheet is regenerated;
- step 15 reports stale adjudications.

Open notes on the doc (2026-10-22, not blocking):
- the Units row doesn't list minutes, hours or weeks (they appear only in the Step comments);
- `endemic_area` is missing from the on_unknown table, and its example `pest:bph` is not a real id;
- a three-part ratio ("5:4:1") stays in `unmapped`, since the model needs part and whole with `ratio_raw`;
- the doc says renumbering options changes `value_key`. The code follows the original proposal (item 6): options are sorted without their numbers, so renumbering alone changes neither key; it changes the id only when a value changes.

### Built (2026-10-22)

Commits c9bbb42 (models, vocab), 9579f15 (prompt v4), f94f93b (list-level fact_key), ff6d916 (steps 10–14), 880846f (v4 hand-runs, `LATEST = "v4"`).
- **Step 9, prompt v4:** the four units were hand-run by revising the v3 answers fact by fact; 124 facts (8e1d 4, b879 23, e63c 72, f5b0 25), no parse, quote or coverage failure.
  - e63c#33 ("avoid excessive use of nitrogen") is now a prohibition Caution; the split-off part is appended as **e63c#71**, so no other fact is renumbered. The first e63c v4 run is in `v4/history/`.
- **Step 10:** 124 in, **103 validated, 21 held** (v3: 123 / 100 / 23).
  - Now validating: e63c#4, #5, #33 (avoid advice as Cautions; no generic "Pest" target).
  - Newly held: e63c#17, `endemic_area` "tungro" unlinked, because `disease:tungro` is only proposed.
  - Still held: 13 ControlMeasures with **no specific target** (prompt v4 writes no generic target, and the schema keeps `target_ids` min 1; a decision for the user), 8 with a step without operation (4 of them have both), KKM, the GLH caution pest, "direct sowing", ADT 46.
- **Step 11:** 13 extracted, 90 needs_review. printed_text fails only f5b0#9–11 (N, P, K from "NPK"). scope_in_unmapped: b879#3, #14, #19 and e63c#56; e63c#9 ("In BPH prone areas/seasons") is now an `endemic_area` condition on `pest:brown_planthopper`.
- **Step 12:** 35 new claims in 4 requests, all answered. The four prohibition Cautions (b879#12, e63c#4, #5, #33) name no chemical, so they have no code-built claim and can never be auto_verified (6 such facts now).
- **Step 13, main database:** `--reset-source` (rehearsed on cropbot-test first) deleted 101 Recommendations, 237 Steps/Clauses/Conditions and 99 spans. Load 1 created 412 nodes and 880 relationships; load 2 created none, snapshot identical (`aa106220…`, 704 nodes, 1038 relationships). 103 facts: 12 extracted, 91 needs_review; no U+FFFD. The 10 query fixtures match.
- **Step 15** (v3 → v4): recall found 90/90 both; recall agreeing 74–84 → **73–85**/90; pipeline recall 77 → **81**/90 (90 % [82–95]); precision found 109 → **110/110**; precision agreeing 92–102 → **92–105**/110 (84 % [76–89] .. 95 % [90–98]).
  - 125 disagreements on 78 rows, 123 adjudicated. Not adjudicated: B3 subtype (e63c#33 is now a Caution) and C3 granularity (the maturity sign is now verbatim).
  - **Stale adjudications** (in `adjudications.csv`, meeting nothing now): A30, B35, B36, B37 and the extra 8e1d#1/m2.
  - Threshold: none; population (b) 9/9 correct (Wilson lower 70 %). Controls: 3/60 unit swaps at ≥ 0.5.
  - The stale list and the data tests' v4 numbers are in c791765.

### Decisions after the build (2026-10-22)

- **`disease:tungro` approved** (needs_review, as drafted): moved from `concepts/proposed/` into `concepts/diseases.csv` and `labels.csv`; `concepts/proposed/` is empty again. e63c#17's `endemic_area` condition now links, so it validates; its tungro scope is a clause condition, so check 10 no longer flags it.
- **ControlMeasures without a target** (v1.5 item 1 below): `kg.normalize.general_practice`. A ControlMeasure with no printed target validates only when no pest, disease, weed or disorder concept is named in its section path, sub-heading or quote (`Linker.names_in`, whole words, plurals count) and it is not in a table row. It gets the code-set flag `general_practice` (no prompt version may use it) and is needs_review. Otherwise it holds: "no target printed in a table row …" or "no target printed in a pest-specific place (… names …)".
  - TNAU: 9 validate as general practices: b879#16, #17 (nursery pre-emergence herbicides under the sub-heading "Weed Management", "to control weeds": no weed concept is named; approved as general practices 2026-10-22), e63c#0, #1, #2, #3, #7 (general pest-management list, p. 63), e63c#52, #60 (IPM module, p. 68). e63c#6, #53, #55 and #59 are general too but still held for a step with no operation.
- **B3 and C3 adjudicated "both"**: all 125 disagreements are adjudicated.
- **Results:**
  - step 10: 124 in, **113 validated, 11 held** (was 103 / 21). Still held: 8 for a step with no operation (8e1d#1, e63c#6, #20, #42, #48, #53, #55, #59), KKM (e63c#42), the GLH caution pest (e63c#68), "direct sowing" (f5b0#2), ADT 46 (f5b0#21);
  - step 11: 13 extracted, 100 needs_review. printed_text also fails e63c#52 (IPM Pseudomonas dip, split from a shared line whose product name is before the quote);
  - step 12: 19 new claims in 2 requests, all answered;
  - seed load: `disease:tungro` and its label (2 nodes, 1 relationship);
  - step 13, main database (no reset): load 1 created 39 nodes and 67 relationships; load 2 created none, snapshot identical (`c28bd3b9…`, 745 nodes, 1106 relationships). 113 facts: 12 extracted, 101 needs_review (C2#24 through the review conflict); none missing; no U+FFFD. The 10 query fixtures and the live review test pass (its snapshot `e840f7c1…`, 745 nodes, 1106 relationships);
  - step 15: recall agreeing **75–85**/90 (83 % [74–90] .. 94 % [88–98]), pipeline recall **84**/90 (93 % [86–97]), precision found 110/110, precision agreeing **95–105**/110 (86 % [79–92] .. 95 % [90–98]). Threshold: none. Stale adjudications unchanged (A30, B35, B36, B37, extra 8e1d#1/m2).
- **AI pre-check notes re-mapped by quote** (`data/review/precheck_mapping.csv`, not committed): all 100 notes map one-to-one to current facts (quote + PDF page, then subtype, scope and values; the two IPM Trichogramma releases, whose v1.4 methods are both the verbatim "Release of biocontrol agents", by target). 61 unchanged, 39 whose fact changed; 13 current facts have no note.
- **Review sheet gap (fixed the same day):** the sheet showed no pest or target. A step without a quantity gets the claim "the advice includes …", which names no pest, so e63c#57 (stem borer) and e63c#58 (leaffolder) read identically. The Scope column now names them. The Jev claim still names no pest for such a step.

## Schema v1.5 build

`docs/schema_v1.5.md` (committed 2026-10-23) covers items 1-14 below. Decisions taken with it: `limit_type = absent` for the "free from …" substances; the L:B grade rule is a `length_breadth_ratio` limit; N.B. 1-2 (BIS method and sampling standards) are not extracted; DFPD is authority tier 0; DFPD chapter 1 (paddy, `crop:rice`) is approved; the grades section scope is drafted as proposed for the user to approve.

Open notes on the doc (2026-10-23, not blocking):
- `SourceSpan.transcription` is one field ("the file path and its sha256") in the doc; the code stores `transcription` and `transcription_sha256`;
- the sentence "A section that matches no section, or more than one, fails loudly." moved to the end of the Seasons paragraph;
- the registry table names neither `section_scope.grades` (the paddy grades from the chapter heading) nor where `marketing_season` and `season_label` come from (built as optional registry fields);
- the absent-substance parameters are open-ended in the doc; the vocab lists the six printed on PDF p. 6;
- `quality_check`'s farm-context inputs are not defined; "purpose selling grain" is `purpose:grain`;
- `length_breadth_ratio` has no unit (null); an `absent` limit has no `limit_value`;
- the per-source prompt version (`[extraction] prompt_version`; TNAU pins v4) is a pipeline setting the doc doesn't mention.

### Built (2026-10-23/24)

Commits 081b1cf (models, vocab, registry model), 8878faa (DFPD registry), a701df4 (prompt v5), 719569e (per-source review CSVs), 08a26dc (steps 10-14), 3562bc7 (control fix).
- **Models:** `AuthorityTier.REGULATORY = 0`; `CommodityForm`, `Grade`, `LimitType`, `QualityParameter` (the eleven measured parameters plus the six absent substances of PDF p. 6). QualitySpec has `commodity_form`, `grades` + `grades_origin` (text | section) + `grades_evidence`, `parameter` + `parameter_raw`, `limit_type`, `limit_value`, `limit_inclusive`, `unit` (pct, or none for a ratio or an absent limit), `part_of`, and `authority`, `season_label`, `marketing_season`, `season_start_year` from the registry.
- **Registry:** `season_label`, `marketing_season` (must name `edition_year`); `section_scope.grades` (a scope may match a chapter's own heading; units then carry `grades` with origin section and the heading as evidence); `[extraction] prompt_version` (`kg.extract.versions.source_version`). DFPD: tier 0, chapter 1 approved, the grades scope **proposed**.
- **Prompt v5** = v4 + rule 17 (regulatory limits), the `tr:` ref form, method/sampling references and signature lines not extracted, value cuts in `unmapped`; the QualitySpec lists are in the vocabulary slot for v5 only, so earlier prompts render unchanged. `LATEST = "v5"`; TNAU pins v4.
- **Per-source review files:** `data/review/{tables,validation,proposed_concepts}_<source slug>.csv` (`kg.registry.review_csv`). The old shared files stay where they were, unused. `kg.tables` defaults to the source's approved chapters.
- **Step 10:** `kg.normalize.quality_spec`. Vocabulary values checked; grades from the quote, else the unit's section grades, else held ("no grade"); a value-cut phrase in `unmapped` holds; a v1-v4 QualitySpec holds. QualitySpec identity (commodity_form, grades, parameter, limit_type, part_of) joins `fact_key` and `conflict_key` only for QualitySpec, so no TNAU key changed.
- **Step 11:** check 3 ranges (moisture 5-25 %, length/breadth ratio 1-5, any other refraction 0-100 %); check 9 checks `parameter_raw` (not the list value) and the unit, and accepts the table's header line (the "(%)" of "Maximum Limit (%)").
- **Step 12:** claims "for paddy (Grade 'A' and Common), Moisture content is at most 17%", "… is free from moulds", "… within the limit for poisonous seeds". A number control halves a maximum and doubles a minimum, so it is stricter than printed (a looser limit would be implied by the true one).
- **Step 13:** `value_key` leaves out QualitySpec wording and provenance (printed name, grade evidence, season, authority); a source with `supersedes` sets `superseded_by` on the older source's facts; conflict detection skips superseded facts.
- **Step 14:** `quality_check` (Q19): commodity form and grade applicability (no grade question when a limit covers both grades), one answer slot per limit, `check` (pass | fail | unknown) per limit, and a `verdict` (fail if any limit fails; pass only when every limit was checked). The farm context has `commodity_form`, `grade`, `quality` (moisture falls back to `grain_moisture_pct`) and `present`. `drying_target` with purpose grain adds `procurement_moisture`. QualitySpec is shown labelled "not yet verified by an expert" while unreviewed (it is not a dose).
- **Review sheet:** QualitySpec after HarvestRule; Values shows the limit as stored and as printed; Scope shows commodity, grades with their origin and the season.
- **DFPD paddy, prompt v5 hand-runs** (2026-10-24, model claude-opus-5-5): 18 facts, no parse, quote or coverage failure. Intro unit: six absent substances and the two L:B grade rules. Schedule unit: the six table limits, the 4 % footnote and the three N.B. 3 sub-limits. Not extracted: the general requirements and the grade definition sentence, the "Foreign matter" group row, N.B. 1-2 (method and sampling references) and the signature line.
  - Step 10: 2 validated (the L:B rules, needs_review for `split_from_shared_line`), 16 held with "no grade" until the grades scope is approved. Steps 11-12: all checks pass; both claims P(yes) 0.98, both controls 0.02.
  - Hand-check page: `data/review/dfpd_quality_check.html` (not committed), every fact beside its transcription line and printed region.
- **Grades scope approved** (2026-10-24, 0f0c2df). Re-run: units carry both grades (origin section); the rendered unit text is unchanged, so the v5 runs stand.
  - Step 10: **18 validated, 0 held** (5 extracted, 13 needs_review for their extraction flags). Step 11: every check passes.
  - Step 12: 16 new claims and 10 more controls in 2 requests. P(yes): the six absent substances 0.95-0.96, the L:B rules 0.98, the table limits lower (inorganic 0.78, organic 0.77, damaged/discoloured/sprouted/weevilled **0.51**, immature 0.76, admixture 0.72, moisture 0.66), the 4 % footnote 0.69, the N.B. 3 sub-limits 0.73-0.80. All 12 controls 0.02-0.05.
  - Step 13, main database: load 1 created 29 nodes (18 facts, 11 spans) and 65 relationships; load 2 created none, snapshot identical (`6a52090b…`, 775 nodes, 1171 relationships). No conflict detected; TNAU unchanged (12 extracted, 101 needs_review); every DFPD span is `manual_transcription` naming p006.md; no U+FFFD.
- **Step 14 after the fixtures (2026-10-24):** a grade rule (`length_breadth_ratio`) decides the grade, not acceptance: it never asks the grade and stays out of the verdict, which lists it under `grade_rules`. `quality_check` asks for `grain_moisture_pct` when moisture is unknown; other refractions are listed as `not_checked`, not asked. Citations carry `extraction_method` and `transcription`.
- **Fixtures** (cropbot-test, both sources loaded): `q19_paddy_18_moisture` (verdict fail on moisture, cited PDF p. 6, no printed page, transcription p006.md; status approved, no label since the approvals below), `q19_paddy_16_moisture` (moisture passes; the verdict stays unknown because the other refractions were not given), `q19_paddy_moisture_unknown` (asks `grain_moisture_pct`), `q15_grain_drying_selling` (TNAU's 12 % drying target with the 17.0 procurement limit). With the 10 TNAU fixtures: 14 pass. The fixture summary compares the citation's `status` too.
- **Hand-check approvals** go through the expert decisions file (reviewer and note as the user names them), never by editing statuses.
- **DFPD paddy approved** (2026-10-24, d0f61e7): all 18 facts hand-checked by Suryansh Bhatnagar against p006.md and the printed page, note "hand-checked against approved transcription p. 6", applies in Uttarakhand: yes; none rejected.
  - Workbook `data/review/expert_review_dfpd.xlsx` (not committed; 18 rows), `import --check` 18 accepted, 0 refused, then imported: 18 rows appended to `data/review/expert_decisions.csv`.
  - Main database: two reloads created nothing, decisions applied 18, stale 0; snapshot `3bc9a2c3…` (775 nodes, 1171 relationships) identical before and after both (the import changed it from `6a52090b…`). TNAU unchanged (12 extracted, 101 needs_review).
  - Checked on the main database (read only): 18 DFPD facts approved, `reviewed_by` set, none missing. The 18 % quality_check answers verdict fail on moisture, the limit approved with no "not yet verified" label, and it matches the fixture.
  - cropbot-test: the 14 fixtures and the live review test pass (15).

## Schema v1.6 build

`docs/schema_v1.6.md` (committed 2026-10-24) adds `SowingWindow.window_for` (`nursery_sowing | direct_seeding | transplanting | sowing`, default `sowing`), a calendar word table (1st fortnight 1–15; 2nd fortnight 16 to month end; 1st week 1–7; last week and "end" 25 to month end; "mid" 15) and hand-curated Variety seeds, for the first Uttarakhand source, the GBPUAT kharif advisory 2020 (rice rows only). Not built yet.

Decisions taken with it (2026-10-24):
- Variety records named outside variety tables are drafted by hand in `concepts/proposed/` (needs_review, page quote); a shared printed prefix ("Pant Dhan- 10,12, 19, 24 & 26") gives full names, with the printed text and the source's spelling "Bansmati" kept as labels.
- Transplanting windows are extracted with `window_for = transplanting`.
- Unreviewed VarietyRecommendation and SowingWindow stay hidden (not descriptive); they are served after a hand-check through the decisions file.
- Q1 `varieties_for` and Q2 `sowing_window` are built for the Tarai fixture; neither falls back across states (schema: "Never").
- Zones as printed on PDF p. 1, `scheme: state_book`: Tarai, Bhabhar & Plain (one zone), mid hills 900–1500 m, high hills 1500 m and above. "Irrigated Hills" is both hill zones plus `system:irrigated`, not a zone.
- One chapter, crop rice; only the four rice rows are extracted, every other row is listed as not extracted.
- Chetki Dhan (spring rice, rain-fed upland) and Jethi Rice (direct seeded, type unspecified) are held with their reasons.

Open notes on the doc (2026-10-24, not blocking; the build follows the choice in brackets):
- `window_for` is in no key [it joins `fact_key` and `conflict_key` for SowingWindow only, so a zone's nursery and transplanting windows neither collide nor conflict, and no other key changes];
- which day a range word gives at the start and at the end of a window is not stated [first day of the word's range as a start, last day as an end: "June end to 1st week of July" = 25 June – 7 July];
- a single printed period with no "to" ("1st Fortnight May") [both bounds from the word: 1–15 May];
- word order varies on the page ("April 2nd fortnight", "2nd fortnight May") [both orders are read];
- only the 1st and last week are in the table; "2nd"/"3rd week" (other crops' rows) stay unread;
- "mid" is one day, so "Mid June to Mid July" is 15 June – 15 July;
- the Q2 `sowing_window` row doesn't say which windows it returns [one answer slot per `window_for`].

### Built (2026-10-24)

Commits 0ee7c14 (doc), d449358/824d26f/d0cef43 (seeds; 824d26f by mistake holds only the removal of `concepts/proposed/`, d0cef43 adds the rows), 5e9cf9f (label), 3beb914 (registry), 87a521b (prompt v6), fc0578e (registry test), 4760f32 (steps 10-13).
- **Seeds:** `state:5` Uttarakhand (approved; LGD code confirmed by the user on lgdirectory.gov.in), `zone:uk_tarai_bhabhar_plain`, `zone:uk_mid_hills`, `zone:uk_high_hills` (`state_book`), 22 hand-seeded rice varieties in `concepts/varieties.csv` (`Variety` with `quote`, `pdf_page`, `source_id` instead of table evidence; stored like pivoted ones) and 24 labels, all needs_review apart from the state. Shared printed groups and "Bansmati" are labels; "Pant Sugandha Dhan- 15,17 & 27" is also a label as converted (a line-break hyphen then a space).
- **Registry:** `source:gbpuat_kharif_advisory_2020`, tier 1, edition 2020, one approved chapter (the title heading, `crop:rice`, rice rows only); the PDF renamed to `data/raw/gbpuat_kharif_advisory_2020.pdf` (sha256 `d24de1ac…`, of the local copy). It prints neither publisher nor date (from the url and the PDF metadata) nor any page number.
- **Conversion:** native text, no OCR, no non-ASCII character (the en dash of "900 – 1500msl" became "-"; superscript ordinals are spaced: "2 nd"). Docling dropped one cell, "Sarika" (okra, p. 2). 1 unit, 3 tables (`#/tables/0` + `#/tables/1` stitched). Step 8: `#/tables/0` row 2 col 3 holds the mid hills and high hills lines across a ruling (not resolved; kept as one cell by decision). Review pages: `data/review/gbpuat_rice_rows.html`, `data/review/gbpuat_rice_check.html` (not committed).
- **Prompt v6** = v5 + rule 18 (one SowingWindow per operation and place, `window_for`, `start_raw`/`end_raw` copied verbatim, no numbers; two places in one cell are separate facts, each quoting its own lines), rule 19 (`recommends` as printed groups), and other crops' rows of a multi-crop table listed as "another crop". `LATEST = "v6"`; DFPD pins v5, GBPUAT v6, TNAU v4. **Gap:** the prompt shows no crop, so a runner other than a hand-run can't tell which rows are "another crop"; the hand-run followed the chapter's `crop:rice`.
- **Steps 10-13 code:** `kg.normalize.calendar_words` (the v1.6 table; February has 28 days); `link_many` for regions and `recommends` (an exact label of several concepts links to all); `window_for` in `fact_key` and `conflict_key` for SowingWindow only; check 9 covers `start_raw`/`end_raw`; claims for both subtypes (a window's control moves it three months).
- **Hand-run** (2026-10-24, claude-opus-5-5): 12 facts, 51 not extracted, no failure. The first run left the one-word rows "st" and "Fisheries" uncovered (their quotes matched other rows); kept in `v6/history/`, the re-run quotes them with their neighbouring rows.
- **Step 10:** 8 validated (all needs_review: needs_review varieties and zones, `split_from_shared_line` on the 6 windows, the calendar readings), 4 held: Chetki Dhan (season "Spring Rice", system "Rain-fed Upland", variety "VL Dhan 207, 208, 209" unlinked) and Jethi Rice (system "Direct seeded"/"Direct Seeded", varieties VL Dhan 154 and 157 unlinked). Step 11: every check passes.
- **Step 12:** 20 claims + 5 controls in 1 request. Variety claims P(yes) 0.96-0.99; windows lower: Tarai nursery 0.68, Tarai transplanting 0.46, mid hills nursery 0.84 and transplanting 0.60, high hills nursery 0.48 and transplanting 0.82. Controls 0.02.
- **Step 13, main database:** after the seed loads (47 + 3 nodes) the snapshot was `2720f561…` (825 nodes, 1218 relationships). Load 1 created 16 nodes and 62 relationships (24 RECOMMENDS, 9 IN_REGION, 5 UNDER_SYSTEM); load 2 created none, snapshot identical (`7e579b5b…`, 842 nodes, 1280 relationships). No conflict; DFPD 18 approved and TNAU unchanged; no U+FFFD.
- **Review sheet** (c3d806c): VarietyRecommendation and SowingWindow follow QualitySpec in `ORDER`; Scope shows `window_for`, Values the linked varieties and a window's dates beside the printed words. The guide's "Applies in Uttarakhand?" line names where the source is from (it said Tamil Nadu for every source); the TNAU guide is unchanged.
- **Approved** (2026-10-24, 3564672): facts 1-8 of `data/review/gbpuat_rice_check.html` (the 2 variety lists and 6 windows), reviewer Suryansh Bhatnagar, note "checked by AI (Claude) against GBPUAT advisory p. 1; approved by Suryansh Bhatnagar", applies in Uttarakhand: yes. Facts 9-12 (Chetki Dhan, Jethi Rice) stay held. Workbook `data/review/expert_review_gbpuat.xlsx` (not committed): `import --check` 8 accepted, 0 refused, then imported. Two reloads of the main database created nothing and applied 8, stale 0; snapshot `13c96aef…` (842 nodes, 1280 relationships) identical after the import and both loads.
- **Step 14:** Q1 `varieties_for` (VarietyRecommendation; the varieties are RECOMMENDS edges, served as `values.recommends` with id and name) and Q2 `sowing_window` (SowingWindow; one answer slot per `window_for`, values with the printed words). Neither crosses state lines (schema: "Never"). Citations carry `source_id`.
- **Fixtures** (cropbot-test, all three sources loaded): `q01_tarai_varieties` (fact 1, its 16 varieties) and `q02_tarai_sowing` (facts 2-3: nursery 16 May - 7 June, transplanting 25 June - 7 July), both approved, no label, PDF p. 1, no printed page, scope local from the GBPUAT source; `q01_mid_hills_varieties` (fact 4, its 8 varieties) and `q02_mid_hills_sowing` (facts 5-6, exactly these two: the high-hills windows are never served), for an irrigated farm in the mid hills. With the 14 earlier fixtures: 18 pass. The harness asserts a printed page exactly when the cited page prints one.
- **Backlog** (recorded 2026-10-24): the Jev claim lead-in for a system reads "for the crop under irrigated"; it should read "for irrigated rice" (`kg.verify.claims.lead`). Changing it changes every such claim's text and key, so their answers are asked again.
- **Backlog** (recorded 2026-10-24): **test a Community load before any Community deployment.** The dump (`backups/neo4j.dump`) is store format `block-block-1.1` and was loaded only on 2026.09.0 Enterprise (Neo4j Desktop's local DBMS, developer licence); teammates use Neo4j Desktop 2026.09 or newer. Two routes, both untested: `neo4j-admin database migrate` to a format Community supports, then dump again; or rebuild with `kg.load.seed` and `kg.load.facts` per source from the repo plus `data/tables/`, `data/normalized/`, `data/validated/` and `data/verified/` (zipped in `backups/`). A rebuilt graph's snapshot hash differs (`created_at` is the load time); compare counts and statuses.

### Items (decided 2026-10-22, now in v1.5)

1. **`ControlMeasure.targets` is optional for general practices** (decided 2026-10-22, built): no target only with the code-set flag `general_practice`, when nothing around the fact names a pest; inside a pest-specific row or section the target stays required. The v1.4 doc says `TARGETS` 1..n.

Decided 2026-10-22 for QualitySpec, from the DFPD uniform specification KMS 2026-27 (`source:dfpd_uniform_spec_kms_2026_27`). **Not built yet**; paddy first, rice and coarse grains after approval:

2. **(A) A "regulatory" authority tier** that outranks books for QualitySpec. The source is tier 3 ("other") until then.
3. **(B) QualitySpec `grade`** (`grade_a | common`) **and `commodity_form`** (`paddy | raw_rice | parboiled_rice`).
4. **(C) `limit_type`** (`max | min`) **and an inclusive flag.**
5. **(D) A fixed `parameter` list**, with the printed name kept in raw.
6. **(E) Value-cut rules** (e.g. rice moisture, PDF p. 7: no value cut up to 14 %, procurement up to 15 % with a value cut between 14 % and 15 %) stay in `unmapped` and the fact is held for now; their design comes after the table is seen.
7. **(F) Seasons are linked by `supersedes`**, and queries use the latest season. The DFPD letter (PDF p. 4) says the specifications continue to apply unless otherwise communicated.
8. **(G) A `quality_check` template (Q19)**, and `drying_target` shows the procurement moisture limit when the purpose is selling grain.
9. **(H) QualitySpec value ranges (check 3), code-built claims (step 12) and a review-sheet order** (today `ORDER` has no QualitySpec, so a sheet with one stops).
10. **(I) A full hand-check of every fact against the rendered page**, instead of a gold set, for this source.

Verified page transcriptions (decided 2026-10-22; the code is built, see "Transcriptions (`kg/transcribe`)"):

11. **`SourceSpan.extraction_method = "manual_transcription"`**, with `SourceSpan.transcription` (the file) and `transcription_sha256` (its approved body hash). Such a span names both; no other span does.
12. **Transcription status:** proposed | approved | rejected. Only an approved one, checked by a person (`checked_by`, `checked_at`) and with an unchanged body, replaces the converter's text for its page.
13. **`table_ref` may be `tr:p<NNN>#/tables/<n>`**, a table of a page transcription. The v1.4 pattern is `#/tables/<n>` only. A `tr:` ref needs `manual_transcription`.
14. **QualitySpec grade from the heading:** a paddy limit applies to both grades (`grade_a` and `common`), because the schedule's heading says "UNIFORM SPECIFICATION OF ALL VARIETIES OF PADDY". The heading is recorded as the evidence for the grade (decided 2026-10-22, with B).

### Items (recorded 2026-10-20 to 2026-10-22, now in v1.4)

The code does these; the v1.3 doc doesn't say them, or says them differently (recorded 2026-10-20):
1. **KNO3 is a Fertilizer** (potassium nitrate), not an `Input`: v1.3's Input example list is wrong. Identity follows the substance.
2. **fact_key** also hashes identity (pests, targets, kind, concerns, control class, dose basis, storage term, ABOUT), the alternative group/option and the quote's first passage ref. The doc lists source, section, subtype, applicability, conditions and step slot.
3. **Formulation → operation for mixed lists:** D/DP → dusting, G/GR/CG → application, EC/WP/SC/WG/SL → spraying, no code → no operation (held). The doc names only D and EC/WP/SC.
4. **An APPLIES may have no dose:** a strength, ratio or share alone ("1% KCl solution", "basal (50%)"). The doc says these sit "beside the dose".
5. **Fertilizer percentages are optional** (blank = no sourced grade); the alternatives check uses approved percentages only.

Proposed, not built (recorded 2026-10-21; the code does not do this yet):

6. **fact_key should not change when an option is added to or removed from an alternative list.**
   - **Today:** `kg.normalize.fact_key_parts` keys every step slot as `[order, alt_group, alt_option, operation, method, anchor, sorted targets]`. Adding Pymetrozine to the BPH list (e63c#35, after the step 8 rebuild) added a slot, so the fact got a new fact_key. The old fact was left `missing_in_latest_run`, with no REVISION_OF link to the new one. Removing an option, or renumbering options, does the same.
   - **Proposed key:** identity stays at the list level.
     - A step outside any alternative group keeps its full slot `[order, operation, method, anchor, sorted targets]`. Changing it is a different instruction.
     - An alternative group becomes one slot, `[order, alt_group, "options"]`. Option numbers, the operation, method and anchor of each option, and its targets are left out.
     - Source, section, subtype, applicability, identity (pests, targets, kind, concerns, control class, dose basis, storage term, ABOUT, conditions) and the quote's first passage ref stay as they are.
   - **The options move to `value_key`** and to the id (`rec:` + hash of key and values). Each option contributes its operation, method, anchor, target with formulation, and amounts, sorted so that renumbering alone changes nothing. A changed list then gives a new id with the same fact_key. The loader already turns that into a needs_review node with `(new)-[:REVISION_OF]->(old)`, and an approved old node keeps serving.
   - **conflict_key stays per option:** two books recommending the same product for the same pest should still compare amounts. A list-level conflict_key would make every pair of different insecticide lists a conflict.
   - **Risk:** two facts in one unit that differ only in their option lists would now share a fact_key. Today's rule already holds both at step 10 (a `fact_key` collision), so the change fails safe. In TNAU the passage ref and the pest separate the BPH and WBPH lists.
   - **Migration:** every fact with an alternative group gets a new fact_key and id, so the change needs a one-time `--reset-source` (refused if any fact is approved, rejected or reviewed), like the v1.3 reload.
   - **Tests when built:** the old and new e63c#35 share a fact_key and load as REVISION_OF; removing, adding or renumbering an option keeps the key; changing a step outside the group changes it; a collision within a unit still holds both facts.

Built, not yet in the doc (2026-10-21):

7. **`Recommendation.scope_in_unmapped`** (a list of the unmapped phrases that look like scope, set by step 11 check 10). Step 14 hides such a fact, unless it is a Caution, until a person approves it.
   - Candidate for prompt v4 or the schema: scope that belongs to one threshold clause ("2/hill in tungro endemic area", e63c#17) should sit on that clause, as a condition or a clause-level scope, not in the fact's `unmapped`. Today the rule hides the whole GLH threshold.

Proposed, not built (recorded 2026-10-22, from the AI pre-check of the review workbook):

8. **Formulation → operation for every product list,** not only mixed "Dust/ spray" lists: G/GR/CG → application, D/DP → dusting, with a flag (as `operation_from_formulation`).
   - Today a list introduced by "Spray any one of" stores every option as spraying, granules and dusts included.
   - TNAU examples (AI pre-check "CHECK" or "FIX"): e63c#21, #27, #28, #30, #36, #37.
9. **Real fields for durations, soaking ratios and bait strengths.** Today these stay in `unmapped`:
   - "for 12 - 16 h", "for 16 h", "in equal volume" (f5b0#0, #3, #4);
   - "at the ratio of 1 : 1" (f5b0#3);
   - "at 0.005%", the bromadiolone bait (e63c#45).
10. **"twice, 15 and 30 days after transplanting" must become two steps**, one per stated time; prompt v3's rule "Stated times are separate steps" already says so.
    - e63c#37 (GLH, PDF p. 67) does not do it today. Every option is one step with `timing_raw` "15 and 30 days after transplanting", offsets 15–15 from transplanting and no repeat count.
    - So the 30-day application exists only in the text.
11. **Farmer-facing instruction text keeps the printed purpose:**
    - seed grading in salt water (f5b0#1: dissolve, discard floaters, sow the sinkers);
    - straw treatment (e63c#43: the 25 kg/ha of chlorpyriphos treats chopped straw; it is not applied directly).

    Today the code-built text reads as a plain application.

## Known issues for segmentation and tables (steps 6–7)

These were found in the committed TNAU conversion while building the schema tests.

- **Fixed: rice seed sub-headings missing on pp. 74–75.**
  - The old conversion's filter had deleted them.
  - The new conversion keeps "Harvesting", "Threshing", "Drying", "Pre-storage seed treatment" and "Storage", and segmentation records them as each item's `subheading`.
  - The schema test examples still use the chapter heading as `section_path`.
- **Fixed: the grain-drying sentence on p. 39.**
  - The printed page (printed 27) has "1.3. Insect management:", "1.4. Disease management:" and "1.5. Harvesting". Docling turned them into list items without numbers.
  - Approved restore fixes bring the headings back, so "Dry the grains to 12% moisture level for storage." sits in "… > 1. TRANSPLANTED PUDDLED LOWLAND RICE > 1.5. Harvesting".
- **Fixed: the same pattern on pp. 46, 49 and 51** (3.9 and 3.10, 4.10, 5.12). Approved restore fixes; rice has no open numbering gaps.
- **Fixed: wheat "I. SEASON AND VARIETY" sat under "CLIMATE REQUIREMENT".**
  - PDF p. 134 prints "CROP IMPROVEMENT" (centred), then "CLIMATE REQUIREMENT" (left) with its table and paragraph, then "I. SEASON AND VARIETY" (centred). Rice p. 13 has the climate block first.
  - An approved `[[reading_order_fix]]` moves "CROP IMPROVEMENT" after the climate paragraph, giving "WHEAT > CROP IMPROVEMENT > I. SEASON AND VARIETY". The caps-heading rule is not changed for one book.
- **Fixed: rice seed fertilizer lines on p. 74.**
  - The page prints "Medium duration : NPK @ 150:50:60 kg / ha" and "Long duration : NPK @ 150:50:80 kg / ha", one bullet per line. Docling read both labels before both values.
  - An approved `[[reading_order_fix]]` moves ": NPK @ 150:50:60 kg / ha" after "Medium duration", so the unit now has the printed order.
- **Fixed: `table_ref`.** The new conversion gives every table a `#/tables/N` ref. The ETL table is two parts (p. 63 and p. 64), to be stitched in step 8.
- **Fixed by the step 8 rebuild (2026-10-21), except p. 16: Docling put text in the wrong cell, and step 8 didn't see it.**
  - **Why the old check missed it:** it compared a cell with the words inside Docling's own box, and the box included the misplaced text. The ruling checks (step 8) now catch it.
  - **Not fixed:**
    - #/tables/7 p. 16: the Nilgiris row has no Docling row of its own, so the part keeps Docling's cells and is flagged;
    - the p. 25 ADT (R) 46 column;
    - words Docling never read ("-" p. 70, "oryzicola" p. 72);
    - the pp. 71–72 parts flagged "words follow Docling's boxes".

    All are in review.
  - **Found** by scanning every ruled part of the rice/wheat tables, checked on the rendered pages; all real:
    - **#/tables/57, p. 66:** "Pymetrozine 50% WG 300g" is printed as the BPH cell's last line. It sits in the WBPH cell r4 c1, whose box crosses the ruling at y 215.1. The WBPH fact e63c#36 is held (no operation), so the graph never had it, but the BPH fact e63c#35 lacks it (gold B23).
    - **#/tables/7, p. 16:** the full-width row "a. The Nilgiris" sits in r1 c0 with "Samba".
    - **#/tables/8, p. 17:** the continuation line "Ponni, ADT (R) 46, TRY 1, TNAU Rice Hybrid CO 4" is split. "…TNAU Rice" is r0 c1, a span-2 cell whose box covers only column 2; the page-break merge then added it to the previous row's period column. "Hybrid CO 4" sits in the Semi dry row's r1 c2.
    - **#/tables/60, p. 69:** the full-width notes row ("❖ Biocontrol agents are compatible …") is merged into the "Seedling dip" row r2.
    - **#/tables/61, p. 70:** the Blast row's last bullet ("Foliar spray with P. fluorescens TNAU liquid formulation @ 5 ml/l") sits in the Brown spot cell r2 c1.
    - **#/tables/32, p. 34:** the second words of "Old delta", "New delta", "General" and "Annamalai block" are in the P2O5 column (r3, r4, r6, r7 c2: "delta 35").
  - **#/tables/62, p. 71:** the same as p. 70 ("Foliar spray … @ 5ml/l").
  - **Affected facts:** only #/tables/57 is in a unit extracted so far (e63c). Pymetrozine is now in the BPH row, and e63c was re-run.
