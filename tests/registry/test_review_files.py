"""One review file per source (2026-10-23): a run for one book never overwrites another's review rows."""

from kg.registry import ROOT, read_entry, review_csv


def test_review_files_are_named_per_source():
    tnau, dfpd = (read_entry(i) for i in ("source:tnau_agriculture_2020", "source:dfpd_uniform_spec_kms_2026_27"))
    assert review_csv("tables", tnau) == ROOT / "data" / "review" / "tables_tnau_agriculture_2020.csv"
    assert len({review_csv(name, e) for name in ("tables", "validation", "proposed_concepts")
                for e in (tnau, dfpd)}) == 6
