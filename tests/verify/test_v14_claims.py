"""Schema v1.4 in step 11, 12 and 14: the new checks on durations, stated times and numbers left in text; claims
for stated times, week offsets, durations, bait strength and carrier; the endemic_area condition in answers."""

from kg.query.context import FarmContext
from kg.query.logic import FALSE, TRUE, UNKNOWN, combine
from kg.validate import check_number_in_text, check_range_narrowed, check_raw_numbers, check_value_ranges
from kg.verify.claims import duration, repeats, timing, _at

GLH = {"order": 1, "alt_group": 1, "alt_option": 1, "operation": "spraying", "anchor": "transplanting",
       "offset_min": 15, "offset_max": 15, "offset_unit": "days", "repeat_offsets": [15, 30], "repeat_count": 2,
       "repeat_raw": "twice", "timing_raw": "15 and 30 days after transplanting", "applies": [], "conditions": []}


def test_claims_render_stated_times_week_offsets_durations_and_the_mix():
    assert timing(GLH) + repeats(GLH) == " at 15 and 30 days after transplanting"
    week = {"offset_min": -1, "offset_max": -1, "offset_unit": "weeks", "anchor": "harvest"}
    assert timing(week) == " 1 week before harvest"
    assert duration({"duration_min": 12, "duration_max": 16, "duration_unit": "hours"}) == " for 12 to 16 hours"
    assert duration({"duration_min": 30, "duration_max": 30, "duration_unit": "minutes"}) == " for 30 minutes"
    assert duration({"duration_raw": "overnight"}) == " overnight"
    bait = {"ratio_part": 1, "ratio_whole": 50, "mix_conc_value": 0.005, "mix_conc_unit": "pct",
            "carrier_raw": "popped corn/rice/dry fish"}
    assert _at(bait) == " at 1 part with 49 parts at 0.005% in the prepared mix with popped corn/rice/dry fish"


def test_checks_cover_durations_stated_times_and_numbers_left_in_text():
    raw_step = {"order": 1, "timing_raw": "15 and 30 days after transplanting", "offset_min": 15, "offset_max": 15,
                "repeat_offsets": [15, 45], "repeat_raw": "twice", "duration_raw": "for 12 - 16 h",
                "duration_min": 12, "duration_max": 18, "purpose_raw": None, "applies": [], "conditions": []}
    raw_fact = {"quote": "Spray twice, 15 and 30 days after transplanting; soak for 12 - 16 h", "raw": {},
                "steps": [raw_step], "conditions": []}
    reason = check_raw_numbers(raw_fact)["reason"]
    assert "repeat offset 45 is not printed" in reason and "duration_max 18 is not printed" in reason
    long_soak = {"steps": [{"order": 1, "offset_unit": "days", "offset_min": None, "offset_max": None,
                            "duration_min": 100, "duration_max": 100, "duration_unit": "hours", "applies": []}]}
    assert "outside 1-72 hours" in check_value_ranges(long_soak)["reason"]
    narrowed = {"steps": [{"order": 1, "duration_min": 16, "duration_max": 16, "duration_raw": "for 12 - 16 h",
                           "applies": [], "conditions": []}]}
    assert "duration 16" in check_range_narrowed(narrowed)["reason"]
    hasten = {"unmapped": ["Maturity may be hastened by 3-4 days"], "steps": [
        {"order": 1, "purpose_raw": "to escape monsoon rains"}]}
    assert check_number_in_text(hasten)["status"] == "fail"
    assert check_number_in_text({"unmapped": ["especially"], "steps": []})["status"] == "pass"


def test_endemic_area_asks_then_branches():
    c = [{"variable": "endemic_area", "op": "==", "value": "disease:tungro", "any_of_group": 1, "raw": "in tungro endemic area"}]
    ctx = FarmContext(crop="crop:rice")
    assert combine(c, ctx) == (UNKNOWN, ["endemic_area"])
    assert combine(c, FarmContext(crop="crop:rice", endemic={"disease:tungro": True}))[0] == TRUE
    assert combine(c, FarmContext(crop="crop:rice", endemic={"disease:tungro": False}))[0] == FALSE
    assert combine(c, FarmContext(crop="crop:rice", endemic={"pest:brown_planthopper": True}))[0] == UNKNOWN
