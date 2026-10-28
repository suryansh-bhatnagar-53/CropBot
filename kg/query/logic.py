"""Three-valued condition logic (schema "Missing data: three-valued logic").

A condition is TRUE, FALSE or UNKNOWN (value missing from the farm context). FALSE AND UNKNOWN = FALSE,
TRUE OR UNKNOWN = TRUE; anything else with UNKNOWN stays UNKNOWN. Conditions sharing an any_of_group are
OR'd, groups are AND'd. Each variable's on_unknown policy (kg.schema.vocab.CONDITION_VARIABLES) says what an
UNKNOWN does: ask, ask then branch, or conservative (Cautions fire, actions are withheld).
"""

from datetime import date

from kg.schema.vocab import CONDITION_VARIABLES, OnUnknown

TRUE, FALSE, UNKNOWN = "true", "false", "unknown"
QUESTIONS = {
    "purpose": "Is this crop for grain or for seed?",
    "storage_months": "For how many months will you store it?",
    "duration_group": "Is your variety short, medium or long duration?",
    "variety": "Which variety are you growing?",
    "season": "Which season is this crop in?",
    "system": "How is the crop grown (for example irrigated, rainfed, transplanted)?",
    "soil_type": "What is your soil type?",
    "stage": "What stage is the crop at?",
    "spider_count_per_hill": "How many spiders do you see per hill?",
    "pest_count": "How many pests do you count?",
    "grain_moisture_pct": "What is the grain moisture now?",
    "commodity_form": "Are you selling paddy, raw rice or parboiled rice?",     # schema v1.5 quality_check
    "grade": "Is your paddy Grade 'A' or Common?",
    "das": "How many days ago did you sow?",
    "sowing_date": "When did you sow?",
    "endemic_area": "Is your area known for this pest or disease?",
}


def policy(variable: str) -> OnUnknown:
    """Applicability variables outside the condition registry (season, system, soil type, stage,
    duration group) are asked, then branched."""
    spec = CONDITION_VARIABLES.get(variable)
    return spec.on_unknown if spec else OnUnknown.ASK_THEN_BRANCH


def question(variable: str) -> dict:
    return {"variable": variable, "question": QUESTIONS.get(variable, "What is your %s?" % variable.replace("_", " ")),
            "policy": policy(variable).value}


def _cmp(op: str, actual, value, value_max) -> bool:
    if isinstance(actual, date) and isinstance(value, str):
        value = date.fromisoformat(value)
        value_max = date.fromisoformat(value_max) if isinstance(value_max, str) else value_max
    if op == "<":
        return actual < value
    if op == "<=":
        return actual <= value
    if op == ">":
        return actual > value
    if op == ">=":
        return actual >= value
    if op == "==":
        return actual == value
    if op == "!=":
        return actual != value
    if op == "in":
        return actual in value
    if op == "between":
        return value <= actual <= value_max
    raise ValueError("unknown condition op %r" % op)


def endemic_state(c: dict, ctx) -> str:
    """Schema v1.4 endemic_area == / in a pest or disease: TRUE if the farmer said their area is known for
    one of them, FALSE if they said no to all, else UNKNOWN (ask, then branch)."""
    values = c["value"] if isinstance(c["value"], list) else [c["value"]]
    answers = [ctx.endemic.get(v) for v in values]
    state = TRUE if True in answers else FALSE if all(a is False for a in answers) else UNKNOWN
    if c["op"] == "!=" and state != UNKNOWN:
        return FALSE if state == TRUE else TRUE
    return state


def condition_state(c: dict, ctx) -> str:
    if c["variable"] == "endemic_area":
        return endemic_state(c, ctx)
    actual = ctx.value(c["variable"])
    if actual is None:
        return UNKNOWN
    return TRUE if _cmp(c["op"], actual, c["value"], c.get("value_max")) else FALSE


def combine(conditions: list[dict], ctx) -> tuple[str, list[str]]:
    """The state of a set of conditions, and the variables that left it UNKNOWN."""
    groups = {}
    for c in conditions or []:
        groups.setdefault(c.get("any_of_group") or 1, []).append((c, condition_state(c, ctx)))
    group_states, unknown = [], []
    for members in groups.values():
        states = [s for _, s in members]
        if TRUE in states:
            group_states.append(TRUE)
        elif all(s == FALSE for s in states):
            group_states.append(FALSE)
        else:
            group_states.append(UNKNOWN)
            unknown += [c["variable"] for c, s in members if s == UNKNOWN]
    if FALSE in group_states:
        return FALSE, []
    if all(s == TRUE for s in group_states):
        return TRUE, []
    return UNKNOWN, sorted(set(unknown))
