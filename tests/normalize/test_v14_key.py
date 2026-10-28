"""Schema v1.4: alternatives are keyed at the list level. Adding, removing or renumbering an option keeps the
fact_key (so a re-extraction loads as REVISION_OF) and changes the id; value_key carries the options, sorted,
without their numbers; a step outside the group still changes the key."""

import json

from kg.load.facts import conflict_key, value_key
from kg.normalize import build, fact_key_parts
from tests.normalize.test_v13 import L, finish, raw

INTRO = {"order": 1, "operation": "irrigation", "method": "Drain water before use of insecticides"}


def option(i, target, value, order=2):
    return {"order": order, "alt_group": 1, "alt_option": i, "operation": "spraying",
            "method": "Direct spray towards the base of the plants",
            "applies": [{"target": target, "value": value, "unit": "g", "basis": "/ha", "raw": "%s %s g" % (target, value)}]}


def built(steps):
    f = raw(subtype="ControlMeasure", control_class="chemical", targets=["BPH"], steps=steps)
    d = build(f, L, "crop:rice", {})
    return json.dumps(fact_key_parts(f, d), sort_keys=True), f, d


def test_adding_removing_or_renumbering_an_option_keeps_the_fact_key():
    two = [INTRO, option(1, "acephate", 666), option(2, "zinc phosphide", 10)]
    three = two + [option(3, "acephate", 590)]                   # e63c#35 gained Pymetrozine this way
    renumbered = [INTRO, option(1, "zinc phosphide", 10), option(2, "acephate", 666)]
    keys = {k for k, _, _ in (built(two), built(three), built(two[:2]), built(renumbered))}
    assert len(keys) == 1


def test_value_key_carries_the_options_without_their_numbers():
    _, f2, d2 = built([INTRO, option(1, "acephate", 666), option(2, "zinc phosphide", 10)])
    _, fr, dr = built([INTRO, option(1, "zinc phosphide", 10), option(2, "acephate", 666)])
    _, f3, d3 = built([INTRO, option(1, "acephate", 666), option(2, "zinc phosphide", 10), option(3, "acephate", 590)])
    a, r, c = finish(f2, d2), finish(fr, dr), finish(f3, d3)
    assert value_key(a) == value_key(r)                  # renumbering alone is not a value change
    assert value_key(a) != value_key(c)                  # a new option is
    assert conflict_key(a) != conflict_key(c)            # conflict_key stays per option


def test_a_step_outside_the_group_still_changes_the_key():
    base, _, _ = built([INTRO, option(1, "acephate", 666)])
    other, _, _ = built([{**INTRO, "method": "Keep the field flooded"}, option(1, "acephate", 666)])
    later, _, _ = built([INTRO, option(1, "acephate", 666, order=3)])
    assert base != other and base != later
