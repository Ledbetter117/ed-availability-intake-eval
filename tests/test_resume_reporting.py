#!/usr/bin/env python3
"""test_resume_reporting.py (also kept as ED-R7-REPAIR-2026-10-30/tests/test_r7_recovery_reporting.py) -- focused regressions for REC-05/06/07 (resume safety) and REC-11, ACC-08, REC-13
(reporting integrity). Offline only: synthetic public calendars, a counting transport stub, simulated crashes.

    python3 -B test_r7_recovery_reporting.py <built candidate tree> [--json out.json]

Every check states the CORRECT behaviour. Run against the pinned pre-repair tree (r6) the defect checks are expected to
FAIL (that is the reproduction); against the repair (r7) every check is expected to PASS. A crash is simulated by raising
an exception at a write boundary. That is not a power-loss test: it says nothing about torn writes or fsync ordering on
a real disk. urllib.request.urlopen is patched to fail, so no check can reach a network.
"""
import contextlib, hashlib, io, json, os, shutil, sys, tempfile, urllib.request
from unittest.mock import patch

TREE = os.path.abspath(sys.argv[1])
OUT = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
sys.path.insert(0, TREE)
sys.dont_write_bytecode = True
import run_eval as e  # noqa: E402
from mmeval import casesets as CS, report as MR, runner as RN  # noqa: E402
from mmeval.transport import TransportDenied, TransportError  # noqa: E402

TMP = tempfile.mkdtemp(prefix="r7-focused-")
RESULTS = []


def check(cid, name, ok, observed):
    RESULTS.append({"id": cid, "check": name, "result": "PASS" if ok else "FAIL", "observed": observed})
    print(f"{'PASS' if ok else 'FAIL'} {cid} {name}  [{json.dumps(observed)[:220]}]")


def no_net(*a, **k):
    raise AssertionError("network call attempted")


CASES_ALL = CS.build_case_manifest(os.path.join(TREE, "data"), "published-40", 7)
GOLDS = {c["case_id"]: json.load(open(c["gold_path"], encoding="utf-8")) for c in CASES_ALL}
BY_ID = {c["case_id"]: c for c in CASES_ALL}
IMG = {hashlib.sha256(__import__("base64").b64encode(open(c["png_path"], "rb").read())).hexdigest(): c["case_id"]
       for c in CASES_ALL}


def perfect(case_id):
    g = GOLDS[case_id]
    return json.dumps({"month": g["month"], "days": {d: {"status": c["status"], "note": c["note"]} for d, c in g["days"].items()},
                       "global_notes": list(g.get("global_notes", []))})


def anth(text, stop="end_turn"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop, "model": "stub-served",
            "usage": {"input_tokens": 10, "output_tokens": 10}}


def case_of(payload):
    data = payload["messages"][0]["content"][0]["source"]["data"]
    return IMG[hashlib.sha256(data.encode()).hexdigest()]


class Stub:
    """Counts every send. `plan` is a list of callables f(case_id) -> response dict or exception; when it is empty the
    stub answers correctly if `answer_when_empty`, otherwise it refuses (fail closed) with SendForbidden."""
    name = "stub"

    def __init__(self, plan=(), answer_when_empty=False):
        self.plan, self.sends, self.answer = list(plan), [], answer_when_empty

    def send(self, arm, url, headers, payload, timeout_s):
        cid = case_of(payload)
        self.sends.append(cid)
        if self.plan:
            r = self.plan.pop(0)(cid)
        elif self.answer:
            r = anth(perfect(cid))
        else:
            raise SendForbidden(f"fail-closed stub: unexpected send for {cid}")
        if isinstance(r, Exception):
            raise r
        return {"json": r, "elapsed_ms": 1, "http_status": 200}


class SendForbidden(Exception):
    pass


class Crash(Exception):
    """A simulated process stop at a write boundary."""


def arm(**over):
    a = {"arm_id": "a1", "role": "test", "provider": "anthropic", "route": "cloud",
         "endpoint": "https://api.anthropic.com/v1/messages", "model_requested": "m", "modalities": ["text", "image"],
         "image_capability_verified": True, "credential_env": "K", "max_output_tokens": 4096, "sampling": {},
         "thinking": None, "image_detail": None, "image_preprocessing": "none", "allowed_data_classes": ["public_synthetic"],
         "status": "ready", "dispatch_enabled": True, "limits": {"max_calls": 100, "max_attempts_per_trial": 3, "timeout_s": 5}}
    a.update(over)
    return a


def cfg(arms, trials=1, caps=1000):
    return {"case_set": {"id": "published-40", "data_class": "public_synthetic"},
            "protocol": {"protocol_id": "t", "trials": trials, "order_seed": "t", "content_repair_retries": 1, "backoff_s": [0]},
            "dispatch": {"enabled": True}, "run_caps": {"max_calls_total": caps}, "arms": arms}


def manifest(c, arms, cases):
    return RN.build_manifest(c, arms, cases, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX, scorer_sha256="t",
                             renderer_sha256="t", data_class="public_synthetic")


def run(rd, transport, cases, arms=None, trials=1, caps=1000, sleep=None, crash=None):
    """crash: None, or ('append', file, predicate(rec)) / ('save_raw',) -- raise Crash at that boundary, once."""
    arms = arms or [arm()]
    c = cfg(arms, trials, caps)
    m = manifest(c, arms, cases)
    real_append, real_save = RN.RunDir.append, RN.RunDir.save_raw
    fired = {"done": False}

    def append(self, name, rec):
        if crash and crash[0] == "append" and not fired["done"] and name == crash[1] and crash[2](rec):
            fired["done"] = True
            raise Crash(f"simulated stop before appending to {name}")
        return real_append(self, name, rec)

    def save_raw(self, unit_id, n, obj):
        if crash and crash[0] == "save_raw" and not fired["done"]:
            fired["done"] = True
            raise Crash("simulated stop before the raw response was saved")
        return real_save(self, unit_id, n, obj)

    out = {"status": None, "error": None}
    with patch.object(urllib.request, "urlopen", side_effect=no_net), patch.object(RN.RunDir, "append", append), \
            patch.object(RN.RunDir, "save_raw", save_raw):
        try:
            out["status"] = RN.execute(m, c, arms, cases, GOLDS, rd, transport, e, prompt=e.TASK_PROMPT,
                                       retry_suffix=e.RETRY_SUFFIX, environ={"K": "k" * 20}, sleep=sleep or (lambda s: None))
        except Exception as ex:      # record every failure type (a pre-repair tree raises bare JSON errors)
            out["error"] = f"{type(ex).__name__}: {ex}"
    lock = os.path.join(rd, "run.lock")
    if os.path.exists(lock):        # a simulated crash leaves the lock, as a real one would; the test clears its own
        os.remove(lock)
    def lines(name):              # the test's own tolerant reader: a torn line is skipped here, never by the runner
        p_ = os.path.join(rd, name)
        got = []
        if os.path.exists(p_):
            for ln in open(p_, encoding="utf-8"):
                try:
                    got.append(json.loads(ln))
                except ValueError:
                    pass
        return got
    out["attempts"], out["results"] = lines("attempts.jsonl"), lines("results.jsonl")
    out["raw_files"] = sorted(os.listdir(os.path.join(rd, "raw"))) if os.path.isdir(os.path.join(rd, "raw")) else []
    return out


def newdir(tag):
    return tempfile.mkdtemp(prefix=tag + "-", dir=TMP)


ONE = [BY_ID["sample_02_rotated"]]
TWO = [BY_ID["sample_02_rotated"], BY_ID["sample_27_lowcontrast"]]
ok_answer = lambda cid: anth(perfect(cid))

# ------------------------------------------------------------------ Priority 1: resume safety
# REC-05: stop after the raw response is saved, before the attempt record is appended
rd = newdir("rec05")
first = run(rd, Stub([ok_answer]), ONE, crash=("append", "attempts.jsonl", lambda r: r.get("result") == "response"))
resumes = []
for _ in range(2):
    s = Stub(answer_when_empty=True)
    o = run(rd, s, ONE)
    resumes.append({"sends": len(s.sends), "error": o["error"], "attempts": len(o["attempts"]),
                    "outcomes": [r["outcome"] for r in o["results"]]})
final = run(rd, Stub(), ONE)
check("REC-05", "a saved raw response with no attempt record is recovered on resume: zero new sends, one justified outcome",
      first["error"] and first["raw_files"] and all(x["sends"] == 0 for x in resumes)
      and [r["outcome"] for r in final["results"]] == ["scored"] and len(final["attempts"]) == 1
      and final["attempts"][0].get("recovered") == "from_raw",
      {"first_stop": (first["error"] or "")[:60], "raw_after_stop": first["raw_files"], "resumes": resumes,
       "final_outcomes": [r["outcome"] for r in final["results"]], "final_attempt_records": len(final["attempts"])})

# REC-06: a recorded NON-transient transport error, then a stop before the outcome row
rd = newdir("rec06")
first = run(rd, Stub([lambda cid: TransportError("HTTP 401: bad key", status=401, transient=False)]), ONE,
            crash=("append", "results.jsonl", lambda r: True))
s = Stub(answer_when_empty=True)
o = run(rd, s, ONE)
check("REC-06", "a recorded non-transient transport error stays terminal after a stop: zero new sends, outcome unavailable",
      len(s.sends) == 0 and [r["outcome"] for r in o["results"]] == ["unavailable"] and len(o["attempts"]) == 1,
      {"resume_sends": len(s.sends), "outcomes": [r["outcome"] for r in o["results"]], "attempt_records": len(o["attempts"])})

# REC-07: a recorded provider-shape error, then a stop before the outcome row
rd = newdir("rec07")
first = run(rd, Stub([lambda cid: {"unexpected": "shape"}]), ONE, crash=("append", "results.jsonl", lambda r: True))
s = Stub(answer_when_empty=True)
o = run(rd, s, ONE)
check("REC-07", "a recorded provider-shape error stays terminal after a stop: zero new sends, outcome unavailable",
      len(s.sends) == 0 and [r["outcome"] for r in o["results"]] == ["unavailable"] and len(o["attempts"]) == 1,
      {"resume_sends": len(s.sends), "outcomes": [r["outcome"] for r in o["results"]], "attempt_records": len(o["attempts"])})

# Lost response: a send happened but nothing was saved. Ambiguous -> explicit refusal before any send, evidence kept.
rd = newdir("lost")
first = run(rd, Stub([ok_answer]), ONE, crash=("save_raw",))
s = Stub(answer_when_empty=True)
o = run(rd, s, ONE)
check("REC-05b", "a send with no saved response is ambiguous: resume refuses explicitly before sending, evidence preserved",
      len(s.sends) == 0 and o["error"] is not None and "RunRefused" in o["error"] and not o["results"],
      {"resume_sends": len(s.sends), "error": (o["error"] or "")[:160], "results": len(o["results"])})

# REC-05c: the same stop in a ledger written before write-ahead intents existed (r6 layout: no intents.jsonl)
rd = newdir("rec05c")
run(rd, Stub([ok_answer]), ONE, crash=("append", "attempts.jsonl", lambda r: r.get("result") == "response"))
if os.path.exists(os.path.join(rd, "intents.jsonl")):
    os.rename(os.path.join(rd, "intents.jsonl"), os.path.join(rd, "intents.jsonl.set-aside-by-test"))
s = Stub(answer_when_empty=True)
o = run(rd, s, ONE)
check("REC-05c", "an r6-layout ledger (no intents file) with a saved raw response is also recovered without a send",
      len(s.sends) == 0 and [r["outcome"] for r in o["results"]] == ["scored"],
      {"resume_sends": len(s.sends), "outcomes": [r["outcome"] for r in o["results"]], "error": o["error"]})

# REC-05d: stop between the intent record and the send itself (nothing reached the provider, but the ledger cannot tell)
rd = newdir("rec05d")


def stop_before_send(cid):
    raise Crash("simulated stop after the intent record, before the request left")


first = run(rd, Stub([stop_before_send]), ONE)
s = Stub(answer_when_empty=True)
o = run(rd, s, ONE)
check("REC-05d", "a stop between intent and send is indistinguishable from a lost response: refused, nothing sent",
      len(s.sends) == 0 and o["error"] is not None and "UNRESOLVED" in o["error"],
      {"first": (first["error"] or "")[:60], "resume_sends": len(s.sends), "error": (o["error"] or "")[:80]})

# REC-05e/f: a raw file that does not support one result (torn, or another unit's answer) is refused, never resent
for cid_, mangle, label in (("REC-05e", lambda raw: raw[: len(raw) // 2], "a torn (half-written) raw file"),
                            ("REC-05f", lambda raw: raw.replace('"unit_id": "a1/sample_02_rotated/t1"',
                                                                '"unit_id": "a1/sample_27_lowcontrast/t1"'),
                             "a raw file naming a different unit")):
    rd = newdir(cid_.lower())
    first = run(rd, Stub([ok_answer]), ONE, crash=("append", "attempts.jsonl", lambda r: r.get("result") == "response"))
    for f in first["raw_files"]:
        fp = os.path.join(rd, "raw", f)
        txt = open(fp, encoding="utf-8").read()
        open(fp, "w", encoding="utf-8").write(mangle(txt))
    s_ = Stub(answer_when_empty=True)
    o = run(rd, s_, ONE)
    check(cid_, f"{label} is not trusted: resume refuses (UNRESOLVED) with zero sends and keeps the file",
          len(s_.sends) == 0 and o["error"] is not None and "UNRESOLVED" in o["error"] and o["raw_files"] == first["raw_files"],
          {"resume_sends": len(s_.sends), "error": (o["error"] or "")[:100]})

# REC-S: stop after the attempt record, before the outcome row, with a usable answer: finished from storage
rd = newdir("recs")
run(rd, Stub([ok_answer]), ONE, crash=("append", "results.jsonl", lambda r: True))
s = Stub(answer_when_empty=True)
o = run(rd, s, ONE)
check("REC-S", "a recorded answer whose outcome row was not written is finished from storage: zero sends, scored",
      len(s.sends) == 0 and [r["outcome"] for r in o["results"]] == ["scored"] and len(o["attempts"]) == 1,
      {"resume_sends": len(s.sends), "outcomes": [r["outcome"] for r in o["results"]]})

# LEDGER-T: a torn last line in any ledger file is refused by name, before any send (colour review CR-01)
for fname in ("attempts.jsonl", "intents.jsonl", "results.jsonl"):
    rd = newdir("torn-" + fname.split(".")[0])
    run(rd, Stub([lambda cid: TransportError("HTTP 503", status=503, transient=True)]), TWO,
        crash=("append", "results.jsonl", lambda r: True))
    with open(os.path.join(rd, fname), "a", encoding="utf-8") as f:
        f.write('{"unit_id": "a1/sam')
    s_ = Stub(answer_when_empty=True)
    o = run(rd, s_, TWO)
    check(f"LEDGER-T-{fname.split('.')[0]}", f"a torn last line in {fname} is refused by name before any send",
          len(s_.sends) == 0 and o["error"] is not None and "RunRefused" in o["error"] and f"{fname} line" in o["error"],
          {"resume_sends": len(s_.sends), "error": (o["error"] or "")[:120]})

# Normal completion, then a complete-run resume
rd = newdir("normal")
s1 = Stub(answer_when_empty=True)
o1 = run(rd, s1, TWO)
s2 = Stub()
o2 = run(rd, s2, TWO)
check("N-1", "normal completion: one send per unit, COMPLETE; resuming a complete run sends nothing",
      len(s1.sends) == 2 and o1["status"] and o1["status"]["run_status"] == "COMPLETE" and len(s2.sends) == 0
      and o2["status"] and o2["status"]["run_status"] == "COMPLETE" and len(o2["results"]) == 2,
      {"sends": [len(s1.sends), len(s2.sends)], "status": [o1["status"] and o1["status"]["run_status"],
                                                          o2["status"] and o2["status"]["run_status"]]})

# Legitimate transient retry: a transient error is recorded, the process stops during backoff, resume retries once
rd = newdir("transient")


def stop_sleep(_):
    raise Crash("simulated stop during backoff")


first = run(rd, Stub([lambda cid: TransportError("HTTP 503", status=503, transient=True)]), ONE, sleep=stop_sleep)
s = Stub(answer_when_empty=True)
o = run(rd, s, ONE)
check("N-2", "a recorded transient error is retried after a stop: exactly one new send, both attempts kept, scored",
      len(s.sends) == 1 and [r["outcome"] for r in o["results"]] == ["scored"] and len(o["attempts"]) == 2,
      {"resume_sends": len(s.sends), "attempt_records": len(o["attempts"]), "outcomes": [r["outcome"] for r in o["results"]]})

# Retry limit kept across a stop: transient error on the last allowed attempt -> unavailable, no send
rd = newdir("limit")
lim = arm(limits={"max_calls": 100, "max_attempts_per_trial": 1, "timeout_s": 5})
first = run(rd, Stub([lambda cid: TransportError("HTTP 503", status=503, transient=True)]), ONE, arms=[lim],
            crash=("append", "results.jsonl", lambda r: True))
s = Stub(answer_when_empty=True)
o = run(rd, s, ONE, arms=[lim])
check("N-3", "the retry limit survives a stop: a transient error on the last allowed attempt ends unavailable, no send",
      len(s.sends) == 0 and [r["outcome"] for r in o["results"]] == ["unavailable"],
      {"resume_sends": len(s.sends), "outcomes": [r["outcome"] for r in o["results"]]})

# Manifest mismatch refuses before any send
rd = newdir("mismatch")
run(rd, Stub(answer_when_empty=True), ONE)
s = Stub(answer_when_empty=True)
o = run(rd, s, ONE, trials=2)
check("N-4", "a changed manifest cannot resume into the same directory, and nothing is sent",
      len(s.sends) == 0 and o["error"] and "RunRefused" in o["error"], {"sends": len(s.sends), "error": (o["error"] or "")[:90]})

# ------------------------------------------------------------------ Priority 2: reporting integrity
def report_of(dirs_arms, contrasts=()):
    """Load and report inside one guard, so a refusal at load time is observed rather than crashing the test."""
    try:
        runs = [(MR.load_run(d), a) for d, a in dirs_arms]
        return {"report": MR.build_report(runs, GOLDS, e, contrasts)}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


rd = newdir("dup")
run(rd, Stub(answer_when_empty=True), ONE)
rows = RN.RunDir(rd).results()
with open(os.path.join(rd, "results.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(rows[0]) + "\n")
st = run(rd, Stub(), ONE)
rep = report_of([(rd, "a1")])
dup_status_unrun = (st["status"] or {}).get("unrun_units")
check("REC-11", "a duplicate outcome row is refused (runner and report), never silently counted or de-duplicated",
      (st["error"] is not None and "duplicate" in st["error"].lower()) and "error" in rep and "duplicate" in rep["error"].lower(),
      {"runner": st["error"] or {"unrun_units": dup_status_unrun}, "report": rep.get("error", "report built without error")})

rd = newdir("foreign")
run(rd, Stub(answer_when_empty=True), ONE)
rows = RN.RunDir(rd).results()
alien = dict(rows[0], unit_id="a1/sample_27_lowcontrast/t1", case_id="sample_27_lowcontrast")
with open(os.path.join(rd, "results.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(alien) + "\n")
rep = report_of([(rd, "a1")])
acc = None if "error" in rep else rep["report"]["arms"]["a1"]
check("ACC-08", "an out-of-plan outcome row is refused before metrics, never added to the numerator",
      "error" in rep and ("out-of-plan" in rep["error"].lower() or "not in the plan" in rep["error"].lower()),
      {"report": rep.get("error") or {"planned": acc["planned_units"], "doc_success_itt": acc["extended"]["doc_success_rate_itt"]}})

rda, rdb = newdir("arm-a"), newdir("arm-b")
run(rda, Stub(answer_when_empty=True), ONE)
run(rdb, Stub(answer_when_empty=True), ONE, trials=2)
rep = report_of([(rda, "a1"), (rdb, "a1")])
check("REC-13", "two runs with the same arm id are refused with both run identities, never silently overwritten",
      "error" in rep and len([h for h in (json.load(open(os.path.join(rda, "manifest.json")))["manifest_hash"][:12],
                                          json.load(open(os.path.join(rdb, "manifest.json")))["manifest_hash"][:12])
                              if h in rep["error"]]) == 2,
      {"report": rep.get("error") or {"arms": list(rep["report"]["arms"]),
                                      "planned": [v["planned_units"] for v in rep["report"]["arms"].values()]}})

# Seven-outcome control (retained): 7 planned; unusable 6/7; document success ITT 1/7
SEVEN = [BY_ID[f] for f in ("sample_01_clean", "sample_02_rotated", "sample_03_lowcontrast", "sample_04_handwritten",
                            "sample_05_clean", "sample_06_rotated", "sample_07_lowcontrast")]


def schema_bad(cid):
    p = json.loads(perfect(cid)); p["days"].pop(sorted(p["days"])[0]); return anth(json.dumps(p))


behaviours = [ok_answer, schema_bad, lambda cid: anth('{"month": "2026-07"', "max_tokens"), lambda cid: anth("No.", "refusal"),
              lambda cid: TransportError("HTTP 401", status=401, transient=False),
              lambda cid: TransportDenied("route violation (stub)")]
rd = newdir("seven")
o = run(rd, Stub(behaviours), SEVEN, caps=6)
rep = report_of([(rd, "a1")])
a = None if "error" in rep else rep["report"]["arms"]["a1"]
want = {"scored": 1, "invalid": 1, "truncated": 1, "refused": 1, "unavailable": 1, "route_denied": 1, "unrun": 1}
check("CTRL-7", "seven-outcome control: 7 planned, one of each state; unusable 6/7; document success ITT 1/7",
      a is not None and {k: a["accounting"][k] for k in want} == want and abs(a["accounting"]["unusable_rate"] - 6 / 7) < 1e-12
      and abs(a["extended"]["doc_success_rate_itt"] - 1 / 7) < 1e-12,
      {"accounting": a and {k: a["accounting"][k] for k in list(want) + ["unusable_rate"]}, "doc_success_itt": a and a["extended"]["doc_success_rate_itt"],
       "error": rep.get("error")})


def all_unavail(cid):
    p = json.loads(perfect(cid))
    for c in p["days"].values():
        c["status"] = "UNAVAILABLE"
    return anth(json.dumps(p))


rd = newdir("degenerate")
run(rd, Stub([all_unavail, all_unavail]), TWO)
rep = report_of([(rd, "a1")])
a = None if "error" in rep else rep["report"]["arms"]["a1"]
check("CTRL-U", "all-UNAVAILABLE answers: critical-error rate 0 but flagged DEGENERATE; document success 0",
      a is not None and a["historic_conditional"]["critical_error_rate"] == 0 and any(f.startswith("DEGENERATE") for f in a["flags"])
      and a["extended"]["doc_success_rate_itt"] == 0.0, {"flags": a and a["flags"][:1], "error": rep.get("error")})

shutil.rmtree(TMP, ignore_errors=True)
n_fail = sum(1 for r in RESULTS if r["result"] == "FAIL")
print(f"\n{len(RESULTS) - n_fail} PASS · {n_fail} FAIL  (tree: {TREE})")
if OUT:
    json.dump({"tree": TREE, "python": sys.version.split()[0], "platform": sys.platform, "results": RESULTS},
              open(OUT, "w"), indent=1)
sys.exit(1 if n_fail else 0)
