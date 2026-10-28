"""Seed validation runs offline: no database needed."""

import shutil
import unicodedata

import pytest

from kg.load.seed import CONCEPTS_DIR, SeedError, read_seed
from kg.schema.concepts import Fertilizer, Label
from kg.schema.ids import label_id


@pytest.fixture
def seed_dir(tmp_path):
    """A copy of concepts/ that a test can break."""
    shutil.copytree(CONCEPTS_DIR, tmp_path / "concepts")
    return tmp_path / "concepts"


def append(directory, name, line):
    with open(directory / name, "a", encoding="utf-8", newline="") as f:
        f.write(line + "\n")


def replace(directory, name, old, new):
    path = directory / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def problems(directory):
    with pytest.raises(SeedError) as e:
        read_seed(directory)
    return "\n".join(e.value.problems)


def test_committed_seed_files_validate():
    seed = read_seed()
    ids = {n.id for n in seed.nodes}
    assert {"country:in", "state:33", "crop:rice", "crop:wheat", "zone:tn_cauvery_delta"} <= ids


def test_every_seed_property_is_a_neo4j_primitive():
    from kg.load.seed import is_primitive
    for n in read_seed().nodes:
        bad = {k: v for k, v in n.props().items() if not is_primitive(v)}
        assert not bad, (n.id, bad)


def test_contains_rows_become_contains_edges_with_pct_and_raw(seed_dir):
    from kg.load.seed import load
    replace(seed_dir, "fertilizers.csv", 'fertilizer:mop,Muriate of potash (MOP),0,0,60,,',
            'fertilizer:mop,Muriate of potash (MOP),0,0,60,"[{""nutrient_id"": ""nutrient:s"", ""pct"": 1, '
            '""raw"": ""1%""}]",')
    driver = FakeDriver()
    load(driver, read_seed(seed_dir))
    assert any("[r:CONTAINS]" in q and "MATCH (b:Nutrient" in q for q in driver.queries)


def test_fertilizer_contains_must_point_at_a_loaded_nutrient(seed_dir):
    replace(seed_dir, "fertilizers.csv", 'fertilizer:mop,Muriate of potash (MOP),0,0,60,,',
            'fertilizer:mop,Muriate of potash (MOP),0,0,60,"[{""nutrient_id"": ""nutrient:cl"", ""pct"": 47, '
            '""raw"": ""47%""}]",')
    assert "contains nutrient:cl is not a loaded Nutrient" in problems(seed_dir)


class FakeDriver:
    """Records every query; MERGE creates a node or relationship only the first time it is seen."""

    def __init__(self):
        self.seen, self.queries = set(), []

    def execute_query(self, query, rows, database_=None):
        from types import SimpleNamespace
        self.queries.append(query)
        made = 0
        for row in rows:
            key = (query.split("MERGE", 1)[1].split(")", 1)[0], row["id"]) if "row.src" not in query else \
                (query, row["src"], row["dst"])
            if key not in self.seen:
                self.seen.add(key)
                made += 1
        nodes = made if "row.src" not in query else 0
        counters = SimpleNamespace(nodes_created=nodes, relationships_created=made - nodes)
        return SimpleNamespace(summary=SimpleNamespace(counters=counters))


def test_load_merges_everything_and_a_second_run_creates_nothing():
    from kg.load.seed import load
    seed, driver = read_seed(), FakeDriver()
    first, second = load(driver, seed), load(driver, seed)
    assert first["nodes"] == len(seed.nodes) and first["relationships"] > 0
    assert second == {"nodes": 0, "relationships": 0}
    assert all("MERGE" in q and "CREATE" not in q for q in driver.queries)
    assert any("[r:LABEL_OF]" in q and "SET r += row.props" in q for q in driver.queries)


def test_todo_rows_are_pending_not_loaded():
    seed = read_seed()
    assert "states.csv:3" in seed.pending                      # pilot state
    assert all(not n.id.endswith("TODO") for n in seed.nodes)
    assert sum(w.startswith("districts.csv") for w in seed.pending) == 31


def test_unknown_reference_is_rejected(seed_dir):
    append(seed_dir, "zones.csv", "zone:tn_test,Test Zone,state_book,state:99,needs_review,test")
    assert "state_id state:99 is not a loaded State" in problems(seed_dir)


def test_label_for_an_unknown_concept_is_rejected(seed_dir):
    append(seed_dir, "labels.csv", "crop:maize,maize,en,Latn,canonical,needs_review,test")
    assert "concept_id crop:maize is not a loaded Concept" in problems(seed_dir)


def test_local_season_without_state_is_rejected(seed_dir):
    append(seed_dir, "local_seasons.csv", "season_local:test,Test,,,,,needs_review,test")
    assert "local_seasons.csv:13: state_id: Field required" in problems(seed_dir)


def test_duplicate_id_is_rejected(seed_dir):
    append(seed_dir, "soil_types.csv", "soil:clay,Clay again,approved,test")
    assert "duplicate id soil:clay" in problems(seed_dir)


def test_duplicate_id_across_files_is_rejected(seed_dir):
    append(seed_dir, "crops.csv", "crop:rice,Paddy,Oryza sativa,cereal,needs_review,test")
    assert "duplicate id crop:rice" in problems(seed_dir)


def test_closed_list_must_be_complete(seed_dir):
    replace(seed_dir, "operation_types.csv", "operation:threshing,Threshing,approved,docs/schema_v1.1.md\n", "")
    assert "OperationType list is incomplete, missing: threshing" in problems(seed_dir)


def test_value_outside_closed_list_is_rejected(seed_dir):
    append(seed_dir, "operation_types.csv", "operation:puddling,Puddling,approved,test")
    assert "operation:puddling is not in the schema's OperationType list" in problems(seed_dir)


def test_wrong_id_prefix_is_rejected(seed_dir):
    append(seed_dir, "fertilizers.csv", "urea2,Urea,46,0,0,needs_review,test")
    assert "is not a fertilizer id" in problems(seed_dir)


def test_fertilizer_needs_a_source():
    with pytest.raises(ValueError, match="source"):
        Fertilizer.model_validate({"id": "fertilizer:x", "name_en": "X", "n_pct": 1, "p2o5_pct": 0,
                                   "k2o_pct": 0, "review_status": "needs_review"})


def test_seeded_fertilizers_are_all_needs_review():
    fertilizers = [n for n in read_seed().nodes if isinstance(n, Fertilizer)]
    assert {f.id for f in fertilizers} == {"fertilizer:urea", "fertilizer:dap", "fertilizer:ssp", "fertilizer:mop",
                                           "fertilizer:znso4", "fertilizer:feso4", "fertilizer:potassium_nitrate"}
    assert all(f.review_status == "needs_review" for f in fertilizers)


# --- label ids --------------------------------------------------------------------------


def test_label_id_includes_kind():
    assert label_id("crop:rice", "alias", "ta", "நெல்") != label_id("crop:rice", "vernacular", "ta", "நெல்")


def test_label_id_is_nfc_normalised():
    composed = unicodedata.normalize("NFC", "धान")
    decomposed = unicodedata.normalize("NFD", composed)
    assert label_id("crop:rice", "vernacular", "hi", composed) == \
        label_id("crop:rice", "vernacular", "hi", decomposed)


def test_label_id_is_computed_and_checked():
    data = {"concept_id": "crop:rice", "text": "paddy", "lang": "en", "script": "Latn",
            "kind": "alias", "review_status": "needs_review"}
    assert Label.model_validate(data).id == label_id("crop:rice", "alias", "en", "paddy")
    with pytest.raises(ValueError, match="does not match"):
        Label.model_validate({**data, "id": "label:0000"})


def test_scientific_names_are_not_labels():
    texts = {n.text.lower() for n in read_seed().nodes if isinstance(n, Label)}
    assert not texts & {"oryza sativa", "triticum aestivum"}
