"""Offline tests for Jev requests: size limits, the cache, backoff, safe storage and the threshold.
A fake HTTP session stands in for the API; nothing is sent."""

import json

import pytest

import kg.verify as v


class Resp:
    def __init__(self, status, body=None, headers=None, text=None):
        self.status_code, self.headers = status, headers or {}
        self.text = text if text is not None else json.dumps(body or {})
        self.content = self.text.encode("utf-8")

    def json(self):
        return json.loads(self.text)


class Session:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def post(self, url, data, headers, timeout):
        self.calls.append(json.loads(data))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def claim(key, unit="unit:x:aaa", control=False):
    return {"key": key, "claim": "Does the passage state that %s?" % key, "control": control, "fact_id": "rec:" + key,
            "unit_id": unit, "raw_index": 0, "cache_key": "ck_" + key, **({"control_kind": "number"} if control else {})}


@pytest.fixture
def entry(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "VERIFIED_DIR", tmp_path)
    from types import SimpleNamespace
    return SimpleNamespace(id="source:test")


def answer(*keys, p=0.9):
    return {"answers": {k: {"noul": p, "type": "noul"} for k in keys}, "id": "task_1", "model": "jev-1.14-free",
            "usage": {"input_tokens": 300, "output_tokens": 20}}


def test_one_request_per_unit_split_only_past_the_token_limit():
    claims = [claim("a"), claim("b"), claim("c", unit="unit:x:bbb")]
    reqs = v.requests_for({"unit:x:aaa": "state A", "unit:x:bbb": "state B"}, claims, "m")
    assert [(r["unit_id"], len(r["claims"])) for r in reqs] == [("unit:x:aaa", 2), ("unit:x:bbb", 1)]
    assert reqs[0]["body"]["state"] == "state A" and set(reqs[0]["body"]["questions"]) == {"a", "b"}
    assert reqs[0]["body"]["questions"]["a"]["type"] == "noul"
    small = v.requests_for({"unit:x:aaa": "s" * 400}, claims[:2], "m", max_tokens=200)
    assert [len(r["claims"]) for r in small] == [1, 1] and all(r["body"]["state"] == "s" * 400 for r in small)


def test_answers_are_stored_with_status_latency_and_rate_headers(entry):
    req = v.requests_for({"unit:x:aaa": "state"}, [claim("a"), claim("b")], "m")[0]
    s = Session([Resp(200, answer("a", "b"), {"X-RateLimit-Remaining": "9", "Content-Type": "json"})])
    log = v.send(entry, req, "https://api", "KEY123", s, sleep=lambda _: None)
    assert log["stored"] and log["status"] == 200 and log["headers"] == {"X-RateLimit-Remaining": "9"}
    assert "latency_ms" in log and log["usage"] == {"input_tokens": 300, "output_tokens": 20}
    assert set(v.load_answers(entry)) == {"ck_a", "ck_b"}
    (line,) = [json.loads(x) for x in open(entry_dir(entry) / "requests.jsonl", encoding="utf-8")]
    assert line["usage"] == {"input_tokens": 300, "output_tokens": 20} and line["stored"] and line["missing"] == []
    assert line["header_names"] == ["Content-Type", "X-RateLimit-Remaining"]           # names only
    assert "json" not in json.dumps(line["header_names"])


def test_a_rerun_sends_nothing_already_answered(entry):
    claims = [claim("a"), claim("b")]
    req = v.requests_for({"unit:x:aaa": "state"}, claims, "m")[0]
    v.send(entry, req, "https://api", "KEY123", Session([Resp(200, answer("a"))]), sleep=lambda _: None)
    answered = v.load_answers(entry)
    pending = [c for c in claims if c["cache_key"] not in answered]
    assert [c["key"] for c in pending] == ["b"]                             # "b" was missing: asked again
    v.send(entry, v.requests_for({"unit:x:aaa": "state"}, pending, "m")[0], "https://api", "KEY123",
           Session([Resp(200, answer("b"))]), sleep=lambda _: None)
    answered = v.load_answers(entry)
    assert v.requests_for({"unit:x:aaa": "state"}, [c for c in claims if c["cache_key"] not in answered], "m") == []


def test_backoff_on_429_and_timeouts_then_success(entry):
    req = v.requests_for({"unit:x:aaa": "state"}, [claim("a")], "m")[0]
    waits, echoed = [], []
    s = Session([Resp(429, {}, {"Retry-After": "7"}), TimeoutError(), Resp(503), Resp(200, answer("a"))])
    log = v.send(entry, req, "https://api", "KEY123", s, sleep=waits.append, echo=echoed.append)
    assert log["stored"] and log["attempt"] == 4 and waits == [7, 4, 8]
    tries = [json.loads(line) for line in open(entry_dir(entry) / "requests.jsonl", encoding="utf-8")]
    assert [t["status"] for t in tries] == [429, None, 503, 200] and tries[1]["error"] == "TimeoutError"
    assert [t.get("retry_in_s") for t in tries] == [7, 4, 8, None] and tries[0]["header_names"] == ["Retry-After"]
    assert [e["status"] for e in echoed] == [429, None, 503, 200]                  # every try reaches the console
    assert tries[-1]["usage"] and not any(t["stored"] for t in tries[:3])


def test_giving_up_keeps_the_queue(entry):
    req = v.requests_for({"unit:x:aaa": "state"}, [claim("a")], "m")[0]
    s = Session([Resp(429)] * 6)
    log = v.send(entry, req, "https://api", "KEY123", s, sleep=lambda _: None)
    assert not log["stored"] and v.load_answers(entry) == {}
    tries = [json.loads(line) for line in open(entry_dir(entry) / "requests.jsonl", encoding="utf-8")]
    assert len(tries) == 6 and not any(t["stored"] for t in tries)


def test_a_body_with_the_key_is_never_stored(entry):
    req = v.requests_for({"unit:x:aaa": "state"}, [claim("a")], "m")[0]
    body = answer("a")
    body["echo"] = "Bearer KEY123"
    log = v.send(entry, req, "https://api", "KEY123", Session([Resp(200, body)]), sleep=lambda _: None)
    assert not log["stored"] and "body contains the API key" in log["problems"]
    assert not list((entry_dir(entry) / "responses").iterdir())


def entry_dir(entry):
    return v.out_dir(entry)


def plan_for(claims, records):
    return {"claims": claims, "records": records, "units": {}, "no_claim": []}


def record(key, status="extracted"):
    return {"unit_id": "unit:x:aaa", "raw_index": 0, "subtype": "DryingSpec",
            "fact": {"id": "rec:" + key, "status": status, "fact_key": "fk:" + key}}


def test_scores_controls_no_claim_and_no_threshold(entry, monkeypatch):
    entry_dir(entry).mkdir(parents=True)
    with open(entry_dir(entry) / "answers.jsonl", "w", encoding="utf-8") as f:
        for ck, p in (("ck_a", 0.95), ("ck_a2", 0.6), ("ck_xa", 0.05)):
            f.write(json.dumps({"cache_key": ck, "key": ck, "p_yes": p, "response": "r"}) + "\n")
    claims = [claim("a"), {**claim("a2"), "fact_id": "rec:a"}, {**claim("xa", control=True), "fact_id": "rec:a"}]
    p = plan_for(claims, [record("a"), record("b")])
    monkeypatch.setattr(v, "CONFIG", entry_dir(entry) / "missing.toml")
    res = v.results(entry, p, "jev-1.14-free")
    a, b = res["facts"]
    assert res["threshold"] is None and a["verifier_score"] == 0.6 and a["status"] == "extracted"   # controls excluded
    assert b["notes"] == ["human review required: no code-built claim"] and b["verifier_score"] is None
    cfg = entry_dir(entry) / "verify.toml"
    cfg.write_text("auto_verified_threshold = 0.5\n", encoding="utf-8")
    monkeypatch.setattr(v, "CONFIG", cfg)
    a, b = v.results(entry, p, "jev-1.14-free")["facts"]
    assert a["status"] == "auto_verified" and b["status"] == "extracted"          # no claim: never auto_verified


def test_endpoint_comes_from_the_reference_request():
    url, model = v.endpoint()
    assert url == "https://api.beatapi.io/v1/systemone" and model == "jev-1.14-free"
