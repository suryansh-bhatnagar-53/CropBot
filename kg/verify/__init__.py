"""Verify with Jev (step 12): code-built claims about each validated fact, asked against its unit's text.

  uv run python -m kg.verify source:tnau_agriculture_2020 --dry-run    # claims and sizes; sends nothing
  uv run python -m kg.verify source:tnau_agriculture_2020              # sends what is not answered yet

One request per unit: the unit text (as step 9 rendered it) once as the state, all its pending claims as
separate `noul` questions keyed by hash(fact_key + claim). A `noul` answer is P(yes). Answers are stored
as they arrive and cached by unit text + claim + model, so a re-run sends nothing already answered.
429, 5xx and timeouts back off and retry; after the last try the queue stays as it is.
verifier_score = the lowest P(yes) of a fact's claims (controls excluded). auto_verified needs
`auto_verified_threshold` in config/verify.toml, which has no default: without it nothing changes status.
A fact with no code-built claim is marked for human review and can never be auto_verified.
Output: data/verified/<id>/ (gitignored). The key comes from BEATAPI_API_KEY in .env and is never
printed or stored.
"""

import hashlib
import json
import re
import time
import tomllib
from collections import Counter
from datetime import datetime, timezone

from kg.extract import get_unit, load_tables, render_unit
from kg.load.seed import read_seed
from kg.registry import ROOT
from kg.schema.concepts import Label
from kg.validate import VALIDATED_DIR, step9_runs

from .claims import CONTROL_KINDS, NO_CLAIM, claim_key, claims_for, control_pair, printed_in_unit, printed_names

VERIFIED_DIR = ROOT / "data" / "verified"
CONFIG = ROOT / "config" / "verify.toml"
EXAMPLE = ROOT / "docs" / "jev_example.md"
MAX_TOKENS = 60_000                 # stay under the 64k request limit
N_CONTROLS = 60                     # step 15 (approved 2026-10-21): number, unit and pest changes
BACKOFF = (2, 4, 8, 16, 32)
KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S")
CRITERIA = {"true": "The passage states this, with these values.",
            "false": "The passage does not state this, or states different values."}


def sha(text: str, n=64) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def endpoint() -> tuple[str, str]:
    """URL and model from the reference request in docs/jev_example.md, so they cannot drift."""
    text = EXAMPLE.read_text(encoding="utf-8")
    url = re.search(r"curl\s+(https://\S+)", text).group(1)
    model = json.loads(re.search(r"-d\s+'(.*?)'", text, re.DOTALL).group(1))["model"]
    return url, model


def threshold() -> float | None:
    if not CONFIG.exists():
        return None
    return tomllib.loads(CONFIG.read_text(encoding="utf-8")).get("auto_verified_threshold")


def estimate_tokens(body: dict) -> int:
    return int(len(json.dumps(body, ensure_ascii=False)) / 4 * 1.2)


def concept_names() -> dict:
    return {n.id: n.name_en for n in read_seed().nodes if not isinstance(n, Label)}


def pest_terms() -> dict:
    """Every way the seed spells each pest: name_en, scientific_name and its labels ("BPH")."""
    out = {}
    for n in read_seed().nodes:
        if isinstance(n, Label) and n.concept_id.startswith("pest:"):
            out.setdefault(n.concept_id, set()).add(n.text)
        elif n.id and n.id.startswith("pest:"):
            out.setdefault(n.id, set()).update(t for t in (n.name_en, getattr(n, "scientific_name", None)) if t)
    return out


# --- planning ----------------------------------------------------------------------------------

def plan(entry, model: str) -> dict:
    """Every claim of every validated fact, the controls, and the requests per unit (not yet sent)."""
    records = [json.loads(line) for line in open(VALIDATED_DIR / entry.id.split(":", 1)[1] / "facts.jsonl",
                                                 encoding="utf-8")]
    names = concept_names()
    tables = load_tables(entry)
    runs = step9_runs(entry)
    printed = {rec["fact"]["id"]: printed_names(runs[rec["run"]["cache_key"]]["facts"][rec["raw_index"]]["fact"],
                                                rec["fact"]) for rec in records}
    units, claims, no_claim = {}, [], []
    for rec in records:
        fact = rec["fact"]
        texts = claims_for(fact, names, printed[fact["id"]])
        if not texts:
            no_claim.append(rec)
            continue
        if rec["unit_id"] not in units:
            units[rec["unit_id"]] = render_unit(entry, get_unit(entry, rec["unit_id"]), tables)[0]
        for t in texts:
            claims.append({"key": claim_key(fact["fact_key"], t), "claim": t, "control": False,
                           "fact_id": fact["id"], "unit_id": rec["unit_id"], "raw_index": rec["raw_index"]})
    claims += controls_for(records, no_claim, names, printed, units)
    for c in claims:
        c["unit_text_sha"] = sha(units[c["unit_id"]])
        c["cache_key"] = sha(c["unit_text_sha"] + "\n" + c["claim"] + "\n" + model)
    return {"records": records, "units": units, "claims": claims, "no_claim": no_claim}


def controls_for(records: list[dict], no_claim: list[dict], names: dict, printed: dict, units: dict,
                 n: int = N_CONTROLS) -> list[dict]:
    """Deliberately wrong claims, deterministic. The kinds take turns (number, unit, pest, number, ...);
    each kind goes round-robin over the units, and within a unit through its facts in order. A kind with
    nothing left gives its turn away, so the mix stays even while every kind has candidates. Stops at n
    or when none is left. A fact gets at most one control of each kind. A control whose changed words the
    unit prints elsewhere is not used (`printed_in_unit`): it might be true there."""
    order = sorted({r["unit_id"] for r in records})
    queues = {(uid, kind): [] for uid in order for kind in CONTROL_KINDS}
    terms = pest_terms()
    for rec in records:
        if rec in no_claim:
            continue
        text = units[rec["unit_id"]]
        for kind in CONTROL_KINDS:
            pair = control_pair(rec["fact"], names, printed[rec["fact"]["id"]], kind, text, terms)
            # a pest swap has its own line check (claims._changed_pest); the pest name itself is printed
            if pair and (kind == "pest" or not printed_in_unit(*pair, text)):
                queues[rec["unit_id"], kind].append((rec, pair[1]))
    turn = {kind: 0 for kind in CONTROL_KINDS}            # the next unit to ask, per kind
    controls = []
    while len(controls) < n and any(queues.values()):
        for kind in CONTROL_KINDS:
            for k in range(len(order)):
                uid = order[(turn[kind] + k) % len(order)]
                if queues[uid, kind] and len(controls) < n:
                    rec, text = queues[uid, kind].pop(0)
                    turn[kind] = (turn[kind] + k + 1) % len(order)
                    controls.append({"key": claim_key(rec["fact"]["fact_key"], text, control=True), "claim": text,
                                     "control": True, "control_kind": kind, "fact_id": rec["fact"]["id"],
                                     "unit_id": uid, "raw_index": rec["raw_index"]})
                    break
    return controls


def body_for(model: str, state: str, claims: list[dict]) -> dict:
    return {"model": model, "state": state,
            "questions": {c["key"]: {"type": "noul", "instructions": c["claim"], "criteria": CRITERIA} for c in claims}}


def requests_for(units: dict, claims: list[dict], model: str, max_tokens: int = MAX_TOKENS) -> list[dict]:
    """One request per unit with pending claims; split when the estimate passes max_tokens (the state
    goes in each part)."""
    out = []
    for uid, state in units.items():
        parts, current = [], []
        for c in (c for c in claims if c["unit_id"] == uid):
            if current and estimate_tokens(body_for(model, state, current + [c])) > max_tokens:
                parts.append(current)
                current = []
            current.append(c)
        if current:
            parts.append(current)
        for n, part in enumerate(parts):
            body = body_for(model, state, part)
            out.append({"unit_id": uid, "part": n, "claims": part, "body": body,
                        "estimated_tokens": estimate_tokens(body)})
    return out


# --- the cache and the queue ------------------------------------------------------------------------

def out_dir(entry):
    return VERIFIED_DIR / entry.id.split(":", 1)[1]


def load_answers(entry) -> dict:
    path = out_dir(entry) / "answers.jsonl"
    if not path.exists():
        return {}
    return {a["cache_key"]: a for a in map(json.loads, open(path, encoding="utf-8"))}


def unsafe(text: str, key: str | None) -> list[str]:
    """Why a response body must not be stored (the same rules as scripts/check_jev.py)."""
    out = []
    try:
        json.loads(text)
    except ValueError:
        out.append("body is not valid JSON")
    if key and key in text:
        out.append("body contains the API key")
    if KEY_LIKE.search(text):
        out.append("body contains a key-like string")
    return out


RATE_HEADERS = re.compile(r"ratelimit|rate-limit|retry-after|x-request-id", re.I)


def send(entry, req: dict, url: str, key: str, session, sleep=time.sleep, echo=None) -> dict:
    """POST one request with backoff. Logs every try (status, latency, rate-limit headers and the
    names of all response headers; usage and stored once known) to requests.jsonl and to `echo`;
    stores the answers as they arrive. Returns the log entry of the last try."""
    d = out_dir(entry)
    d.mkdir(parents=True, exist_ok=True)
    (d / "responses").mkdir(exist_ok=True)
    log_path, ans_path = d / "requests.jsonl", d / "answers.jsonl"

    def done(entry_log):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry_log) + "\n")
        if echo:
            echo(entry_log)
        return entry_log

    for attempt in range(len(BACKOFF) + 1):
        started = time.monotonic()
        entry_log = {"unit_id": req["unit_id"], "part": req["part"], "attempt": attempt + 1,
                     "questions": len(req["claims"]), "estimated_tokens": req["estimated_tokens"],
                     "at": datetime.now(timezone.utc).isoformat()}
        try:
            resp = session.post(url, data=json.dumps(req["body"], ensure_ascii=False).encode("utf-8"),
                                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                                timeout=120)
            entry_log.update(status=resp.status_code, latency_ms=round((time.monotonic() - started) * 1000),
                             headers={k: v for k, v in resp.headers.items() if RATE_HEADERS.search(k)},
                             header_names=sorted(resp.headers.keys()))      # names only, never values
        except Exception as e:                       # timeouts and connection errors are retried
            entry_log.update(status=None, latency_ms=round((time.monotonic() - started) * 1000),
                             error=type(e).__name__)
            resp = None
        retry = resp is None or resp.status_code == 429 or resp.status_code >= 500
        if retry and attempt < len(BACKOFF):
            wait = BACKOFF[attempt]
            if resp is not None and resp.headers.get("Retry-After", "").isdigit():
                wait = max(wait, int(resp.headers["Retry-After"]))
            done({**entry_log, "stored": False, "retry_in_s": wait})
            sleep(wait)
            continue
        if resp is None or not 200 <= resp.status_code < 300:
            return done({**entry_log, "stored": False})
        problems = unsafe(resp.text, key)
        if problems:
            return done({**entry_log, "stored": False, "problems": problems})
        name = "%s_%d.json" % (req["unit_id"].rsplit(":", 1)[1], req["part"])
        (d / "responses" / name).write_bytes(resp.content)
        body = resp.json()
        answers = body.get("answers", {})
        with open(ans_path, "a", encoding="utf-8") as f:
            for c in req["claims"]:
                a = answers.get(c["key"])
                if a is None or a.get("type") != "noul":
                    continue
                f.write(json.dumps({"cache_key": c["cache_key"], "key": c["key"], "p_yes": a["noul"],
                                    "model": body.get("model"), "response": name, "task_id": body.get("id")}) + "\n")
        entry_log.update(stored=True, response=name, usage=body.get("usage"), task_id=body.get("id"),
                         missing=[c["key"] for c in req["claims"] if c["key"] not in answers],
                         extra=sorted(set(answers) - {c["key"] for c in req["claims"]}))
        return done(entry_log)
    return entry_log


# --- results ---------------------------------------------------------------------------------------

def results(entry, p: dict, model: str) -> dict:
    answers = load_answers(entry)
    thr = threshold()
    by_fact = {}
    for c in p["claims"]:
        a = answers.get(c["cache_key"])
        by_fact.setdefault(c["fact_id"], []).append({**{k: c[k] for k in ("key", "claim", "control")},
                                                     **({"control_kind": c["control_kind"]} if c["control"] else {}),
                                                     "p_yes": a["p_yes"] if a else None,
                                                     "response": a["response"] if a else None})
    facts = []
    for rec in p["records"]:
        fact, cl = rec["fact"], by_fact.get(rec["fact"]["id"], [])
        scored = [c for c in cl if not c["control"]]
        score = min(c["p_yes"] for c in scored) if scored and all(c["p_yes"] is not None for c in scored) else None
        status, notes = fact["status"], []
        if not scored:
            notes.append(NO_CLAIM)
        elif thr is not None and score is not None and status == "extracted" and score >= thr:
            status = "auto_verified"
        facts.append({"fact_id": fact["id"], "unit_id": rec["unit_id"], "raw_index": rec["raw_index"],
                      "subtype": rec["subtype"], "status_before": fact["status"], "status": status,
                      "verifier": model, "verifier_score": score, "claims": cl, "notes": notes})
    return {"facts": facts, "threshold": thr}
