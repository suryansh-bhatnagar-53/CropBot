import re
from pathlib import Path

from kg.load.constraints import NODE_LABELS, constraint_name, statements
from kg.schema.concepts import SEED_FILES

DOC = (Path(__file__).resolve().parents[2] / "docs" / "schema_v1.3.md").read_text(encoding="utf-8")


def test_every_concept_label_in_the_doc_has_a_constraint():
    section = DOC.split("## Concept nodes", 1)[1].split("\n## ", 1)[0]
    doc_labels = set()
    for row in re.findall(r"^\| (`[^|]+`) \|", section, re.M):
        doc_labels |= set(re.findall(r"`(\w+)`", row))
    assert doc_labels and doc_labels <= set(NODE_LABELS)


def test_fact_and_provenance_labels_have_constraints():
    for label in ("Recommendation", "Step", "Condition", "ThresholdClause", "SourceSpan",
                  "Source", "Label", "Concept", "DryingSpec", "PestThreshold"):
        assert label in NODE_LABELS


def test_every_seeded_label_has_a_constraint():
    assert {model.LABEL for model in SEED_FILES.values()} <= set(NODE_LABELS)


def test_statements_are_idempotent_uniqueness_constraints():
    stmts = statements()
    assert len(stmts) == len(set(NODE_LABELS))
    assert all("IF NOT EXISTS" in s and s.endswith("REQUIRE n.id IS UNIQUE") for s in stmts)


def test_constraint_names():
    assert constraint_name("AgroClimaticZone") == "agro_climatic_zone_id_unique"
    assert constraint_name("Crop") == "crop_id_unique"
