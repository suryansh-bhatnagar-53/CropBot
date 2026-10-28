"""Seed rows approved in step 10 (pests, active ingredients, organic inputs, labels), and any rows
still drafted in concepts/proposed/, which validate but are never loaded."""

import csv

import pytest
from pydantic import ValidationError

from kg.load.seed import CONCEPTS_DIR, is_primitive, read_seed
from kg.schema.concepts import PROPOSED_FILES, ActiveIngredient, Label, Pest, Variety

PROPOSED = CONCEPTS_DIR / "proposed"


@pytest.fixture(scope="module")
def seed():
    return read_seed()


def by_id(seed):
    return {n.id: n for n in seed.nodes if not isinstance(n, Label)}


def test_approved_rows_are_seeded_needs_review(seed):
    nodes = by_id(seed)
    pests = [n for n in nodes.values() if isinstance(n, Pest)]
    ais = [n for n in nodes.values() if isinstance(n, ActiveIngredient)]
    assert len(pests) == 18 and len(ais) == 53
    assert all(n.review_status.value == "needs_review" for n in pests + ais)
    assert {"organic_input:fym", "organic_input:azospirillum"} <= set(nodes)


def test_active_ingredients_never_take_reg_status_from_the_book(seed):
    ais = [n for n in by_id(seed).values() if isinstance(n, ActiveIngredient)]
    assert all(a.reg_status.value == "unknown" and "CIB&RC" in a.source for a in ais)
    dicofol = by_id(seed)["ai:dicofol"]
    assert dicofol.use_class.value == "acaricide"                         # schema v1.3, approved 2026-10-20


def test_pyrethroid_members_come_from_irac(seed):
    members = sorted(n.id for n in by_id(seed).values()
                     if isinstance(n, ActiveIngredient) and "ai_group:synthetic_pyrethroids" in n.member_of)
    assert members == ["ai:cypermethrin", "ai:deltamethrin", "ai:etofenprox", "ai:fenvalerate", "ai:permethrin"]
    assert all("IRAC MoA Classification Scheme v11.5" in by_id(seed)[m].source for m in members)


def test_standard_names_with_book_spellings_as_labels(seed):
    nodes, labels = by_id(seed), {(lb.text, lb.concept_id) for lb in seed.nodes if isinstance(lb, Label)}
    for ai, name, book in (("ai:chlorpyrifos", "Chlorpyrifos", "chlorpyriphos"),
                           ("ai:tricyclazole", "Tricyclazole", "Tricyclozole"),
                           ("ai:bromadiolone", "Bromadiolone", "bromodialone"),
                           ("ai:etofenprox", "Etofenprox", "ethopenprox")):
        assert nodes[ai].name_en == name and (book, ai) in labels
    assert ("Bavistin", "ai:carbendazim") in labels and ("clayey soils", "soil:clay") in labels


def test_fertilizers_with_unknown_percentages_load_with_blank_percentages(seed):
    nodes = by_id(seed)
    for f in ("fertilizer:znso4", "fertilizer:feso4", "fertilizer:potassium_nitrate"):
        assert (nodes[f].n_pct, nodes[f].p2o5_pct, nodes[f].k2o_pct) == (None, None, None)
        assert "blank" in nodes[f].source
    labels = {(lb.text, lb.concept_id) for lb in seed.nodes if isinstance(lb, Label)}
    assert {("ZnSO4", "fertilizer:znso4"), ("KNO3", "fertilizer:potassium_nitrate"), ("KCl", "fertilizer:mop"),
            ("rodent", "pest:rat")} <= labels
    assert not any(p.startswith(("fertilizers.csv", "labels.csv")) for p in seed.pending)


def test_uttarakhand_rows_approved_2026_10_24(seed):
    nodes = by_id(seed)
    assert nodes["state:5"].review_status.value == "approved" and "lgdirectory.gov.in" in nodes["state:5"].source
    assert sorted(i for i in nodes if i.startswith("zone:uk_")) == [
        "zone:uk_high_hills", "zone:uk_mid_hills", "zone:uk_tarai_bhabhar_plain"]
    varieties = [n for n in nodes.values() if isinstance(n, Variety)]
    assert len(varieties) == 22 and all(v.review_status.value == "needs_review" and v.crop_id == "crop:rice"
                                        and v.source_id == "source:gbpuat_kharif_advisory_2020" for v in varieties)
    assert all(is_primitive(x) for v in varieties for x in v.props().values())   # the seed loader's check
    shared = {lb.concept_id for lb in seed.nodes if isinstance(lb, Label) and lb.text == "Pant Dhan- 10,12, 19, 24 & 26"}
    assert shared == {"variety:pant_dhan_%d" % n for n in (10, 12, 19, 24, 26)}


def test_a_variety_has_table_evidence_or_a_hand_seeded_quote():
    base = {"id": "variety:x_1", "name_en": "X 1", "name": "X 1", "review_status": "needs_review"}
    seeded = {"quote": "X 1", "pdf_page": 1, "source_id": "source:test"}
    assert Variety.model_validate(base | seeded).quote == "X 1"            # schema v1.6
    with pytest.raises(ValidationError, match="table evidence, or a quote"):
        Variety.model_validate(base)
    with pytest.raises(ValidationError, match="table evidence, or a quote"):
        Variety.model_validate(base | {"quote": "X 1", "pdf_page": 1})
    span = {"id": "span:x", "source_id": "source:test", "pdf_page": 1, "section_path": "X", "quote": "X 1",
            "extraction_method": "table_parse", "table_ref": "#/tables/0"}
    with pytest.raises(ValidationError, match="not both"):
        Variety.model_validate(base | seeded | {"evidence": [span]})


def test_drafts_in_proposed_validate_but_are_not_loaded(seed):
    seeded = set(by_id(seed))
    for name, model in PROPOSED_FILES.items():
        path = PROPOSED / name
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if not any("TODO" in (v or "") for v in row.values()):
                    node = model.model_validate({k: v for k, v in row.items() if v})
                    assert getattr(node, "id", None) not in seeded
