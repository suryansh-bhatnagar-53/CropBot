"""The step 14 templates on the loaded TNAU, DFPD and GBPUAT facts, one farm-context fixture per question.

  uv run python -m pytest tests/query/test_live_fixtures.py --neo4j-test-db cropbot-test

Skipped without --neo4j-test-db; the fixture empties that database and loads concepts/ and the TNAU facts.
Each fixture (tests/query/fixtures/*.json) gives the context and the expected answer.
"""

import json
from pathlib import Path

import pytest

from kg.load import facts as lf
from kg.query import FarmContext, answer, ask
from kg.registry import read_entry
from kg.validate import VALIDATED_DIR
from tests.conftest import reset_and_seed

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.json"))


def summarise(out: dict) -> dict:
    """The parts of an answer the fixtures compare. Facts are named by their quote, which survives
    re-extraction (rec ids change whenever fact_key or a value does)."""
    facts = [f for s in out["slots"] for f in s["facts"]]
    return {"scope": out["scope"], "asks": sorted(a["variable"] for a in out["asks"]),
            "visible": [{"quote": f["citation"]["quote"], "duration_group": f["duration_group"]} for f in facts],
            "hidden": [{"quote": h.get("quote")} for h in out["hidden"]], "message": out["message"],
            "facts": [{"quote": f["citation"]["quote"], "labels": f["labels"],
                       "clauses": [c["value"] for c in f["clauses"]],
                       "conflicts": [c.get("quote") or "" for c in f["conflicts"]],
                       "checks": (f.get("check") or {}).get("result"),          # schema v1.5 quality_check
                       "citations": {k: f["citation"].get(k) for k in ("pdf_page", "printed_page", "extraction_method",
                                                                       "transcription", "status", "source_id")},
                       # schema v1.6: a list's varieties, a window's operation and dates as stored
                       "varieties": sorted(v["id"] for v in f["values"].get("recommends") or []),
                       "windows": [f["values"].get(k) for k in ("window_for", "start_month", "start_day", "end_month",
                                                                "end_day")]} for f in facts],
            "verdict": out.get("verdict"),
            "procurement": [{"quote": f["citation"]["quote"]} for f in out.get("procurement_moisture") or []]}


def matches(entry, fact: dict) -> bool:
    """A fixture entry: a snippet of the quote, or {"quote": snippet, "duration_group": …} or
    {"quote": full quote, "exact": true} where one quote is contained in another."""
    entry = {"quote": entry} if isinstance(entry, str) else entry
    if entry.get("exact"):
        ok = fact["quote"] == entry["quote"]
    else:
        ok = entry["quote"] in (fact["quote"] or "")
    return ok and all(fact.get(k) == v for k, v in entry.items() if k not in ("quote", "exact"))


def one_to_one(entries: list, facts: list[dict]) -> bool:
    """Every entry matches a different fact, and every fact is matched."""
    if len(entries) != len(facts):
        return False
    if not entries:
        return True
    return any(matches(entries[0], f) and one_to_one(entries[1:], facts[:i] + facts[i + 1:])
               for i, f in enumerate(facts))


def check(expect: dict, got: dict) -> list[str]:
    """Differences between a fixture's expectation and the summary. `hidden` entries must each be hidden;
    `labels`, `clauses` and `conflicts` are keyed by a snippet that names exactly one served fact."""
    problems = []
    for key, want in expect.items():
        if key == "asks":
            ok, have = sorted(want) == got["asks"], got["asks"]
        elif key == "visible":
            ok, have = one_to_one(want, got["visible"]), [f["quote"] for f in got["visible"]]
        elif key == "hidden":
            ok, have = all(any(matches(e, h) for h in got["hidden"]) for e in want), got["hidden"]
        elif key in ("labels", "clauses", "conflicts", "checks", "citations", "varieties", "windows"):
            ok, have = True, {}
            for snippet, value in want.items():
                named = [f for f in got["facts"] if snippet in (f["quote"] or "")]
                have[snippet] = [f[key] for f in named]
                if key == "conflicts":
                    ok &= len(named) == 1 and all(any(s in q for q in named[0][key]) for s in value)
                elif key == "citations":                          # the keys the fixture names
                    ok &= len(named) == 1 and all(named[0][key].get(k) == v for k, v in value.items())
                else:
                    ok &= len(named) == 1 and named[0][key] == value
        elif key == "verdict":                                     # the keys the fixture names
            ok, have = got["verdict"] is not None and all(got["verdict"].get(k) == v for k, v in want.items()), \
                got["verdict"]
        elif key == "procurement":
            ok, have = one_to_one(want, got["procurement"]), [f["quote"] for f in got["procurement"]]
        else:
            ok, have = want == got[key], got[key]
        if not ok:
            problems.append("%s: expected %r, got %r" % (key, want, have))
    return problems


@pytest.fixture(scope="module")
def loaded(neo4j_test_db):
    if not (VALIDATED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists():
        pytest.skip("needs data/validated and data/verified for the TNAU guide")
    driver, name = neo4j_test_db
    concepts = reset_and_seed(driver, name)                  # the test database only
    for source in ("source:tnau_agriculture_2020", "source:dfpd_uniform_spec_kms_2026_27",
                   "source:gbpuat_kharif_advisory_2020"):
        if not (VALIDATED_DIR / source.split(":", 1)[1] / "facts.jsonl").exists():
            pytest.skip("needs data/validated and data/verified for %s" % source)
        entry = read_entry(source)
        lf.load(driver, entry, lf.build(entry, lf.read_inputs(entry), concepts), name)
    return driver, name


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_fixture(loaded, path):
    driver, name = loaded
    fx = json.loads(path.read_text(encoding="utf-8"))
    out = ask(fx["template"], fx["context"], driver=driver, database=name)       # the agent's entry point
    assert out == answer(driver, fx["template"], FarmContext.model_validate(fx["context"]), name)
    assert check(fx["expect"], summarise(out)) == []
    served = [f for s in out["slots"] for f in s["facts"]] + list(out.get("procurement_moisture") or [])
    for f in served:                                                # every served fact carries its citation
        c = f["citation"]
        assert c["quote"] and c["pdf_page"] and c["source_title"] and c["status"]
        # a printed page whenever the cited page prints one (the DFPD schedules and the GBPUAT advisory print none)
        assert c["printed_page"] == read_entry(c["source_id"]).printed_page(c["pdf_page"])
        assert "verifier_score" in c
        assert bool(c["transcription"]) == (c["extraction_method"] == "manual_transcription")
