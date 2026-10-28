"""The schema doc's worked examples as fact documents.

The doc shows them in shortened form. Quotes and PDF pages here are the real
TNAU text from converted/tnau_agriculture.index.json; ids, fact_keys and raw
strings are filled in so the examples are complete.
"""

TNAU_SOURCE = {
    "id": "source:tnau_agriculture_2020",
    "title": "Crop Production Guide: Agriculture 2020",
    "publisher": "Directorate of Agriculture, Tamil Nadu and Tamil Nadu Agricultural University",
    "edition_year": 2020,
    "language": "en",
    "url": "https://agritech.tnau.ac.in/pdf/AGRICULTURE.pdf",
    "sha256": "adbb66a8efc7bc24cb6b4afc99782519cf41d8b1ca0414c486db6627d7bc5c7f",
    "state_id": "state:33",
    "region_scope": ["state:33"],
    "authority_tier": 1,
}

TN = [{"id": "state:33", "origin": "source"}]
SEED_SECTION = "Rice > RICE - VARIETAL SEED PRODUCTION"


def span(span_id, pdf_page, section_path, quote, method="native_text"):
    return {"id": span_id, "source_id": TNAU_SOURCE["id"], "pdf_page": pdf_page,
            "section_path": section_path, "quote": quote, "extraction_method": method}


def fact(rec_id, subtype, summary, evidence, **fields):
    return {"id": rec_id, "subtype": subtype, "summary_en": summary,
            "fact_key": "%s|%s|%s" % (TNAU_SOURCE["id"], evidence["section_path"], rec_id),
            "crop_ids": ["crop:rice"], "regions": TN, "evidence": [evidence], **fields}


# --- 1. Brown planthopper threshold (p. 64 table) ------------------------------------

BPH_QUOTE = ("1 hopper/ tiller in the absence of predatory spider and 2 hoppers / tiller "
             "when spider is present at 1/hill.")


def spiders(op, raw):
    return [{"variable": "spider_count_per_hill", "op": op, "value": 1, "unit": "count",
             "any_of_group": 1, "raw": raw}]


BPH_THRESHOLD = fact(
    "rec:tnau_rice_bph_threshold", "PestThreshold",
    "BPH: act at 1/tiller, or 2/tiller if spiders >= 1/hill",
    span("span:tnau_rice_etl_bph", 64,
         "Rice > A) Pest management > ii) Main field > "
         "Economic threshold level (ETL) for important pests",
         BPH_QUOTE, method="table_parse"),
    pest_ids=["pest:brown_planthopper"],
    clauses=[
        {"observation": "hoppers", "value": 1, "unit": "count", "sampling_unit": "per_tiller",
         "raw": "1 hopper/ tiller",
         "conditions": spiders("<", "in the absence of predatory spider")},
        {"observation": "hoppers", "value": 2, "unit": "count", "sampling_unit": "per_tiller",
         "raw": "2 hoppers / tiller",
         "conditions": spiders(">=", "when spider is present at 1/hill")},
    ],
)

# --- 2. Rice seed storage, and the conflict inside the book (pp. 74-75) ------------------

DRYING_QUOTE = ("Dry the seeds to 12 - 13 % moisture content for short term storage and "
                "8-9 % moisture for long term storage.")

STORAGE_SHORT = fact(
    "rec:tnau_rice_seed_storage_short", "StorageRule",
    "Seed: gunny or cloth bags, 8-9 months, 12-13% moisture",
    span("span:tnau_rice_seed_storage_short", 75, SEED_SECTION,
         "Store the seeds in gunny or cloth bags for short term storage (8-9 months) with a "
         "seed moisture content of 12 - 13 %."),
    purpose_ids=["purpose:seed"],
    storage_months_min=8, storage_months_max=9, max_moisture_pct=13,
    structure="gunny or cloth bags",
    raw={"storage_months_min": "8-9 months", "storage_months_max": "8-9 months",
         "max_moisture_pct": "12 - 13 %"},
)

STORAGE_MEDIUM = fact(
    "rec:tnau_rice_seed_storage_medium", "StorageRule",
    "Seed: polylined gunny bag, 12-15 months, 8-9% moisture",
    span("span:tnau_rice_seed_storage_medium", 75, SEED_SECTION,
         "Store the seeds in polylined gunny bag for medium term storage (12- 15 months) with a "
         "seed moisture content of 8 - 9 %."),
    purpose_ids=["purpose:seed"],
    storage_months_min=12, storage_months_max=15, max_moisture_pct=9,
    structure="polylined gunny bag",
    raw={"storage_months_min": "12- 15 months", "storage_months_max": "12- 15 months",
         "max_moisture_pct": "8 - 9 %"},
)

STORAGE_LONG = fact(
    "rec:tnau_rice_seed_storage_long", "StorageRule",
    "Seed: 700 gauge polythene bag, over 15 months, under 8% moisture",
    span("span:tnau_rice_seed_storage_long", 75, SEED_SECTION,
         "Store the seeds in 700 gauge polythene bag for long term storage (more than 15 months) "
         "with a seed moisture content less than 8 %."),
    purpose_ids=["purpose:seed"],
    storage_months_min=15, max_moisture_pct=8, structure="700 gauge polythene bag",
    storage_months_min_inclusive=False, max_moisture_pct_inclusive=False,
    raw={"storage_months_min": "more than 15 months", "max_moisture_pct": "less than 8 %"},
    status="needs_review", conflicts_with=["rec:tnau_rice_seed_drying_long"],
)

DRYING_LONG = fact(
    "rec:tnau_rice_seed_drying_long", "DryingSpec",
    "Seed for long-term storage: dry to 8-9% moisture",
    span("span:tnau_rice_seed_drying", 74, SEED_SECTION, DRYING_QUOTE),
    purpose_ids=["purpose:seed"],
    storage_term_raw="long term", target_moisture_pct_min=8, target_moisture_pct_max=9,
    raw={"target_moisture_pct_min": "8-9 %", "target_moisture_pct_max": "8-9 %"},
    status="needs_review", conflicts_with=["rec:tnau_rice_seed_storage_long"],
)

# --- 3. Grain vs seed drying (pp. 39 and 74) ------------------------------------------------

DRYING_GRAIN = fact(
    "rec:tnau_rice_grain_drying", "DryingSpec",
    "Grain for storage: dry to 12% moisture",
    span("span:tnau_rice_grain_drying", 39,
         "Rice > Non-Puddled machine Transplanted Rice (NPTR)",
         "Dry the grains to 12% moisture level for storage."),
    purpose_ids=["purpose:grain"],
    target_moisture_pct_min=12, target_moisture_pct_max=12,
    raw={"target_moisture_pct_min": "12%", "target_moisture_pct_max": "12%"},
)

DRYING_SEED_SHORT = fact(
    "rec:tnau_rice_seed_drying_short", "DryingSpec",
    "Seed for short-term storage: dry to 12-13% moisture",
    span("span:tnau_rice_seed_drying", 74, SEED_SECTION, DRYING_QUOTE),
    purpose_ids=["purpose:seed"],
    storage_term_raw="short term", target_moisture_pct_min=12, target_moisture_pct_max=13,
    raw={"target_moisture_pct_min": "12 - 13 %", "target_moisture_pct_max": "12 - 13 %"},
)

# --- extra: nursery DAP with its fallback (p. 30), used by the APPLIES tests ---------------

NURSERY_DAP = fact(
    "rec:tnau_rice_nursery_dap", "NutrientDose",
    "Wet nursery: 40 kg DAP per 20 cents before last puddling, or 16 kg urea + 120 kg SSP",
    span("span:tnau_rice_nursery_dap", 30, "Rice > 1.1.1. Wet nursery > Nutrient management",
         "For that situation, before the last puddling, apply 40 kg of DAP and if not readily "
         "available, apply straight fertilizers 16 kg of urea and 120 kg of super phosphate."),
    dose_basis="blanket",
    unmapped=["seedlings are to be pulled out in 20-25 days after sowing",
              "less fertile nursery soils"],
    steps=[
        {"order": 1, "alt_group": 1, "alt_option": 1, "alt_priority": 1,
         "operation": "fertilizer_application", "anchor": "last_puddling",
         "timing_raw": "before the last puddling", "instruction_en": "Apply 40 kg DAP",
         # per_cent_nursery: value per one cent; area_cents is the area the book stated
         "applies": [{"target_id": "fertilizer:dap", "value": 2, "unit": "kg",
                      "basis": "per_cent_nursery", "area_cents": 20, "raw": "40 kg of DAP"}]},
        {"order": 1, "alt_group": 1, "alt_option": 2, "alt_priority": 2,
         "condition_raw": "if not readily available",
         "operation": "fertilizer_application", "anchor": "last_puddling",
         "timing_raw": "before the last puddling",
         "instruction_en": "Apply 16 kg urea and 120 kg super phosphate",
         "applies": [
             {"target_id": "fertilizer:urea", "value": 0.8, "unit": "kg",
              "basis": "per_cent_nursery", "area_cents": 20, "raw": "16 kg of urea"},
             {"target_id": "fertilizer:ssp", "value": 6, "unit": "kg",
              "basis": "per_cent_nursery", "area_cents": 20, "raw": "120 kg of super phosphate"},
         ]},
    ],
)

WORKED_EXAMPLES = {
    "bph_threshold": BPH_THRESHOLD,
    "storage_short": STORAGE_SHORT,
    "storage_medium": STORAGE_MEDIUM,
    "storage_long": STORAGE_LONG,
    "drying_long": DRYING_LONG,
    "drying_grain": DRYING_GRAIN,
    "drying_seed_short": DRYING_SEED_SHORT,
    "nursery_dap": NURSERY_DAP,
}
