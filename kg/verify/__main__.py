import argparse
import json
import os
import sys
from collections import Counter

from kg.registry import ROOT, read_registry

from . import endpoint, load_answers, out_dir, plan, requests_for, results, send


def report(entry, p, res, sent_logs) -> dict:
    d = out_dir(entry)
    logs = [json.loads(line) for line in open(d / "requests.jsonl", encoding="utf-8")] if (d / "requests.jsonl").exists() else []
    usage = Counter()
    for log in logs:
        for k, v in (log.get("usage") or {}).items():
            usage[k] += v
    controls = [{"fact": "%s#%d" % (c["unit_id"].rsplit(":", 1)[1], c["raw_index"]), "kind": c["control_kind"],
                 "claim": c["claim"],
                 "p_yes": next((x["p_yes"] for f in res["facts"] for x in f["claims"] if x["key"] == c["key"]), None)}
                for c in p["claims"] if c["control"]]
    return {
        "facts": len(res["facts"]), "claims": sum(not c["control"] for c in p["claims"]),
        "controls": controls, "threshold": res["threshold"],
        "no_claim": ["%s#%d %s" % (r["unit_id"].rsplit(":", 1)[1], r["raw_index"], r["subtype"]) for r in p["no_claim"]],
        "status_after": dict(Counter(f["status"] for f in res["facts"])),
        "unanswered": sum(1 for f in res["facts"] for c in f["claims"] if c["p_yes"] is None),
        "requests_this_run": len(sent_logs), "requests_logged": len(logs), "usage_total": dict(usage),
        "scores": [{"fact": "%s#%d" % (f["unit_id"].rsplit(":", 1)[1], f["raw_index"]), "subtype": f["subtype"],
                    "verifier_score": f["verifier_score"], "notes": f["notes"]} for f in res["facts"]],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kg.verify", description="Step 12: verify with Jev")
    ap.add_argument("source_id")
    ap.add_argument("--dry-run", action="store_true", help="write claims and request sizes; send nothing")
    a = ap.parse_args(argv)
    entry = next((e for e in read_registry() if e.id == a.source_id), None)
    if entry is None:
        raise SystemExit("unknown source %s" % a.source_id)
    url, model = endpoint()
    p = plan(entry, model)
    answered = load_answers(entry)
    pending = [c for c in p["claims"] if c["cache_key"] not in answered]
    reqs = requests_for(p["units"], pending, model)
    d = out_dir(entry)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "claims.jsonl", "w", encoding="utf-8") as f:
        for c in p["claims"]:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print("model %s; claims %d (+%d controls %s); cached %d; pending %d; requests %d"
          % (model, sum(not c["control"] for c in p["claims"]), sum(c["control"] for c in p["claims"]),
             dict(Counter(c["control_kind"] for c in p["claims"] if c["control"])),
             len(p["claims"]) - len(pending), len(pending), len(reqs)))
    for r in reqs:
        print("  request %s part %d: %d questions, ~%d tokens" % (r["unit_id"].rsplit(":", 1)[1], r["part"],
                                                                  len(r["claims"]), r["estimated_tokens"]))
    print("no code-built claim (human review required):", [
        "%s#%d %s" % (r["unit_id"].rsplit(":", 1)[1], r["raw_index"], r["subtype"]) for r in p["no_claim"]])
    if a.dry_run:
        print("dry run: nothing sent; claims written to", d / "claims.jsonl")
        return 0
    from dotenv import load_dotenv
    import requests
    load_dotenv(ROOT / ".env")
    key = os.environ.get("BEATAPI_API_KEY")
    if not key:
        raise SystemExit("missing in .env: BEATAPI_API_KEY")
    def echo(log):
        retry = ", retry in %s s" % log["retry_in_s"] if "retry_in_s" in log else ""
        print("  try %d %s part %d: HTTP %s%s, %s ms, stored %s, usage %s, rate headers %s, header names %s" % (
            log["attempt"], log["unit_id"].rsplit(":", 1)[1], log["part"], log.get("status"), retry,
            log.get("latency_ms"), log.get("stored"), log.get("usage"), log.get("headers"), log.get("header_names")))

    session, logs = requests.Session(), []
    for r in reqs:
        log = send(entry, r, url, key, session, echo=echo)
        logs.append(log)
        if not log.get("stored"):
            print("stopping: the request was not answered; the queue is kept for the next run")
            break
    res = results(entry, p, model)
    with open(d / "facts.jsonl", "w", encoding="utf-8") as f:
        for row in res["facts"]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    rep = report(entry, p, res, logs)
    (d / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("facts", "claims", "status_after", "unanswered", "requests_this_run",
                                           "usage_total", "threshold")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
