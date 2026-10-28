"""Offline tests for unit and basis conversion (kg.normalize.units)."""

import pytest

from kg.normalize.units import ACRES_PER_HA, CENTS_PER_HA, canon_basis, canon_unit, water_l_per_ha


@pytest.mark.parametrize("printed, unit, factor", [
    ("kg", "kg", 1), ("g", "g", 1), ("tonne", "t", 1), ("lit", "l", 1), ("ml", "ml", 1), ("%", "pct", 1),
    ("count", "count", 1), ("nos.", "count", 1), ("quintal", "kg", 100), ("q", "kg", 100),
])
def test_units(printed, unit, factor):
    u = canon_unit(printed)
    assert (u.unit.value, u.factor) == (unit, factor)


@pytest.mark.parametrize("printed", ["N", "µM", "part", None, "packets"])
def test_units_with_no_canonical_form(printed):
    assert canon_unit(printed) is None


def test_quintal_per_acre_to_kg_per_ha():
    u, b = canon_unit("quintal"), canon_basis("per acre")
    assert round(2 * u.factor * b.factor, 2) == 494.21                     # 2 q/acre = 494.21 kg/ha
    assert b.basis.value == "per_ha" and abs(ACRES_PER_HA - 2.47105) < 1e-5


def test_cent_of_main_field_to_per_ha():
    b = canon_basis("/cent")
    assert b.basis.value == "per_ha" and round(b.factor, 3) == round(CENTS_PER_HA, 3) and round(CENTS_PER_HA, 1) == 247.1
    assert round(100 * b.factor / 1000, 2) == 24.71                         # 100 g/cent = 24.71 kg/ha


def test_nursery_cents_keep_the_stated_area():
    b = canon_basis("20 cents nursery")
    assert (b.basis.value, 40 * b.factor, b.area_cents) == ("per_cent_nursery", 2, 20)    # 40 kg -> 2 kg per cent
    b = canon_basis("to 20 cents nursery")
    assert (b.basis.value, b.area_cents) == ("per_cent_nursery", 20)
    b = canon_basis("/cent", nursery=True)
    assert (b.basis.value, b.factor, b.area_cents) == ("per_cent_nursery", 1, 1)


@pytest.mark.parametrize("printed, kw, basis, factor, inference", [
    ("/ha", {}, "per_ha", 1, False), ("/ ha", {}, "per_ha", 1, False), ("(per ha)", {}, "per_ha", 1, False),
    ("per_ha", {}, "per_ha", 1, False), ("kernel/ha", {}, "per_ha", 1, False),
    ("for one hectare", {}, "per_ha", 1, True), ("one hectare of seeds", {}, "per_ha", 1, True),
    ("per 10 m 2", {}, "per_m2", 0.1, False), ("/m 2", {}, "per_m2", 1, False),
    ("/kg of seed", {}, "per_kg_seed", 1, False), ("/ kg of seed", {}, "per_kg_seed", 1, False),
    ("/kg", {"seed_treatment": True}, "per_kg_seed", 1, True),
    ("/l of water for 1 kg of seeds", {}, "per_l_water", 1, False),
    ("in 10 lit of water", {}, "per_l_water", 0.1, False),
    ("/ tiller", {}, "per_tiller", 1, False),
])
def test_bases(printed, kw, basis, factor, inference):
    b = canon_basis(printed, **kw)
    assert (b.basis.value, round(b.factor, 6), b.inference) == (basis, factor, inference)


@pytest.mark.parametrize("printed", ["/kg", "with 49 parts popped corn/rice/dry fish", "+ 49 parts of bait", None])
def test_bases_with_no_rule(printed):
    assert canon_basis(printed) is None


def test_water():
    assert water_l_per_ha("500 l/ha") == 500 and water_l_per_ha("1lit of water") is None
