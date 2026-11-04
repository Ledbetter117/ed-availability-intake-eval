#!/usr/bin/env python3
"""test_r71.py -- focused regressions for the r7.1 successor (ORCA-ED-MAX-PROGRESS-20261030). Each check states the CORRECT
behaviour; run against the r7 edition-2 tree the r7.1 checks are expected to FAIL (failing-first evidence).

    python3 -B test_r71.py <built tree> [--json out.json]

Offline except LOOPBACK sockets: the redirect, proxy and kill checks start local HTTP servers on 127.0.0.1 and one real child
process that is killed during a send (Windows TerminateProcess / POSIX SIGKILL). That is a real process termination, not a
power-loss or torn-disk test. No provider, model or external host is contacted; any other network use fails the check.
"""
import contextlib, hashlib, http.server, io, json, os, shutil, socketserver, subprocess, sys, tempfile, textwrap, threading, time
import urllib.request
from unittest.mock import patch

TREE = os.path.abspath(sys.argv[1])
OUT = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
sys.path.insert(0, TREE)
sys.dont_write_bytecode = True
import run_eval as e  # noqa: E402
from mmeval import casesets as CS, report as MR, runner as RN  # noqa: E402
from mmeval.transport import HttpTransport, TransportError  # noqa: E402

TMP = tempfile.mkdtemp(prefix="r71-")
RES = []


def check(cid, name, ok, observed):
    RES.append({"id": cid, "check": name, "result": "PASS" if ok else "FAIL", "observed": observed})
    print(f"{'PASS' if ok else 'FAIL'} {cid} {name}  [{json.dumps(observed, default=str)[:220]}]")


def no_net(*a, **k):
    raise AssertionError("network call attempted")


CASES_ALL = CS.build_case_manifest(os.path.join(TREE, "data"), "published-40", 7)
GOLDS = {c["case_id"]: json.load(open(c["gold_path"], encoding="utf-8")) for c in CASES_ALL}
IMG = {hashlib.sha256(__import__("base64").b64encode(open(c["png_path"], "rb").read())).hexdigest(): c["case_id"] for c in CASES_ALL}
ONE = [c for c in CASES_ALL if c["case_id"] == "sample_02_rotated"]


def perfect(cid):
    g = GOLDS[cid]
    return json.dumps({"month": g["month"], "days": {d: {"status": c["status"], "note": c["note"]} for d, c in g["days"].items()},
                       "global_notes": list(g.get("global_notes", []))})


def anth(text):
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "model": "stub-served",
            "usage": {"input_tokens": 10, "output_tokens": 10}}


class SendForbidden(Exception):
    pass


class Crash(Exception):
    pass


class Stub:
    name = "stub"

    def __init__(self, answer=False):
        self.sends, self.answer = [], answer

    def send(self, arm, url, headers, payload, timeout_s):
        data = payload["messages"][0]["content"][0]["source"]["data"]
        cid = IMG[hashlib.sha256(data.encode()).hexdigest()]
        self.sends.append(cid)
        if not self.answer:
            raise SendForbidden("fail-closed stub: unexpected send for " + cid)
        return {"json": anth(perfect(cid)), "elapsed_ms": 1, "http_status": 200}


def arm(**over):
    a = {"arm_id": "a1", "role": "test", "provider": "anthropic", "route": "cloud", "endpoint": "https://api.anthropic.com/v1/messages",
         "model_requested": "m", "modalities": ["text", "image"], "image_capability_verified": True, "credential_env": "K",
         "max_output_tokens": 4096, "sampling": {}, "thinking": None, "image_detail": None, "image_preprocessing": "none",
         "allowed_data_classes": ["public_synthetic"], "status": "ready", "dispatch_enabled": True,
         "limits": {"max_calls": 100, "max_attempts_per_trial": 3, "timeout_s": 5}}
    a.update(over)
    return a


def cfg(arms):
    return {"case_set": {"id": "published-40", "data_class": "public_synthetic"},
            "protocol": {"protocol_id": "t", "trials": 1, "order_seed": "t", "content_repair_retries": 1, "backoff_s": [0]},
            "dispatch": {"enabled": True}, "run_caps": {"max_calls_total": 1000}, "arms": arms}


def run(rd, transport, arms=None, crash=None):
    arms = arms or [arm()]
    c = cfg(arms)
    m = RN.build_manifest(c, arms, ONE, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX, scorer_sha256="t", renderer_sha256="t",
                          data_class="public_synthetic")
    real_save = RN.RunDir.save_raw
    fired = {"done": False}

    def save_raw(self, unit_id, n, obj):
        if crash == "save_raw" and not fired["done"]:
            fired["done"] = True
            raise Crash("simulated stop before the raw response was saved")
        return real_save(self, unit_id, n, obj)

    out = {"status": None, "error": None}
    with patch.object(urllib.request, "urlopen", side_effect=no_net), patch.object(urllib.request.OpenerDirector, "open", side_effect=no_net), \
            patch.object(RN.RunDir, "save_raw", save_raw):
        try:
            out["status"] = RN.execute(m, c, arms, ONE, GOLDS, rd, transport, e, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX,
                                       environ={"K": "k" * 20}, sleep=lambda s: None)
        except Exception as ex:          # noqa: BLE001 -- the check records the exact refusal
            out["error"] = "%s: %s" % (type(ex).__name__, ex)
    out["results"] = [json.loads(l) for l in open(os.path.join(rd, "results.jsonl"), encoding="utf-8")] \
        if os.path.exists(os.path.join(rd, "results.jsonl")) else []
    return out


def unresolved_run(name, arms=None):
    """A send whose answer was never saved: the stub answers, then the process 'stops' before save_raw."""
    rd = os.path.join(TMP, name)
    first = run(rd, Stub(answer=True), arms=arms, crash="save_raw")
    if os.path.exists(os.path.join(rd, "run.lock")):
        os.remove(os.path.join(rd, "run.lock"))   # the crashed in-process run cannot release; this scaffolding removes it
    return rd, first


UID = "a1/sample_02_rotated/t1"
HAS_SETTLE = hasattr(RN.RunDir, "settle")

# ---- O-1 owner settlement of an UNRESOLVED send
rd, first = unresolved_run("settle-unavailable")
s0 = Stub()
before = run(rd, s0)
check("SETTLE-0", "an unresolved send refuses the run before any send (r7 behaviour kept)",
      s0.sends == [] and "UNRESOLVED" in (before["error"] or ""), {"first": first["error"], "resume": (before["error"] or "")[:90]})
if HAS_SETTLE:
    RN.RunDir(rd).settle(UID, 1, "count_unavailable", "owner-test", "no response was ever returned; count it as unavailable")
    s1 = Stub()
    after = run(rd, s1)
    rows = after["results"]
    check("SETTLE-U", "settled 'count_unavailable': resume sends nothing and the unit ends unavailable naming the settlement",
          s1.sends == [] and after["error"] is None and [r["outcome"] for r in rows] == ["unavailable"]
          and "owner settlement" in (rows[0].get("error") or ""), {"sends": s1.sends, "rows": [(r["outcome"], r.get("error")) for r in rows]})
else:
    check("SETTLE-U", "settled 'count_unavailable': resume sends nothing and the unit ends unavailable naming the settlement",
          False, "RunDir.settle is missing (r7 has no settlement tool)")
rd, _ = unresolved_run("settle-resend")
if HAS_SETTLE:
    RN.RunDir(rd).settle(UID, 1, "resend_authorized", "owner-test", "the provider log shows no request; resend once")
    s2 = Stub(answer=True)
    after = run(rd, s2)
    att = [json.loads(l) for l in open(os.path.join(rd, "attempts.jsonl"), encoding="utf-8")]
    check("SETTLE-R", "settled 'resend_authorized': exactly one new send (attempt 2); both attempts kept; scored",
          s2.sends == ["sample_02_rotated"] and [a["attempt"] for a in att] == [1, 2] and att[0]["result"] == "owner_settled"
          and [r["outcome"] for r in after["results"]] == ["scored"], {"sends": s2.sends, "attempts": [(a["attempt"], a["result"]) for a in att]})
    rd3, _ = unresolved_run("settle-at-limit", arms=[arm(limits={"max_calls": 100, "max_attempts_per_trial": 1, "timeout_s": 5})])
    RN.RunDir(rd3).settle(UID, 1, "resend_authorized", "owner-test", "resend if allowed")
    s3 = Stub()
    after3 = run(rd3, s3, arms=[arm(limits={"max_calls": 100, "max_attempts_per_trial": 1, "timeout_s": 5})])
    check("SETTLE-LIMIT", "a resend authorization never exceeds the arm's attempt limit: unavailable, no send",
          s3.sends == [] and [r["outcome"] for r in after3["results"]] == ["unavailable"], [(r["outcome"], r.get("error")) for r in after3["results"]])
    refusals = {}
    for label, args in (("no-intent", ("a1/sample_02_rotated/t9", 1, "count_unavailable", "o", "r")),
                        ("no-reason", (UID, 1, "count_unavailable", "o", "")),
                        ("bad-decision", (UID, 1, "retry", "o", "r")),
                        ("already-final", (UID, 1, "count_unavailable", "o", "r"))):
        try:
            RN.RunDir(rd).settle(*args)
            refusals[label] = "accepted"
        except RN.RunRefused as ex:
            refusals[label] = "refused"
    check("SETTLE-REFUSE", "a settlement is refused without an unresolved intent, without who/why, with an unknown decision, or "
          "for a unit that already ended", set(refusals.values()) == {"refused"}, refusals)
else:
    for cid in ("SETTLE-R", "SETTLE-LIMIT", "SETTLE-REFUSE"):
        check(cid, "settlement behaviour", False, "RunDir.settle is missing (r7 has no settlement tool)")

# ---- REC-04b the outcome row records a decision from a stored answer
rd = os.path.join(TMP, "rec04b")
real_append = RN.RunDir.append
fired = {"n": 0}


def crash_results(self, name, rec):
    if name == "results.jsonl" and not fired["n"]:
        fired["n"] = 1
        raise Crash("simulated stop before the outcome row")
    return real_append(self, name, rec)


with patch.object(RN.RunDir, "append", crash_results):
    run(rd, Stub(answer=True))
if os.path.exists(os.path.join(rd, "run.lock")):
    os.remove(os.path.join(rd, "run.lock"))
r = run(rd, Stub())
check("REC-04b", "an outcome decided from a stored answer after a stop says so in its row",
      [x.get("resumed_from_stored_answer") for x in r["results"]] == [True], [{k: x.get(k) for k in ("outcome", "resumed_from_stored_answer")} for x in r["results"]])

# ---- ACC-02b every rate key names its denominator
rd = os.path.join(TMP, "acc02b")
run(rd, Stub(answer=True))
rep = MR.build_report([(MR.load_run(rd), "a1")], GOLDS, e, [])
ext = rep["arms"]["a1"]["extended"] if "arms" in rep and "a1" in rep["arms"] else {}
den = ext.get("rate_denominators") or {}
check("ACC-02b", "the extended JSON block names the denominator of every rate key",
      {"status_error_rate", "false_unavailable_rate", "doc_status_exact_rate_conditional", "doc_success_rate_itt"} <= set(den), sorted(den))

# ---- A8 interpreter-independent mean
import csv  # noqa: E402
vals = [float(row["day_accuracy"]) for row in csv.DictReader(open(os.path.join(TREE, "results_haiku", "per_case.csv"), newline="", encoding="utf-8"))]
pub = json.load(open(os.path.join(TREE, "results_haiku", "metrics.json"), encoding="utf-8"))["overall"]["day_accuracy"]
check("A8-mean", "run_eval.mean reproduces the published results_haiku day_accuracy bit for bit on this interpreter (%s)" % sys.version.split()[0],
      e.mean(vals) == pub, {"mean": repr(e.mean(vals)), "published": repr(pub)})


# ---- REC-14 an interrupted legacy import completes (append-only) or refuses by name
from mmeval.replay import import_legacy  # noqa: E402
raw_src = os.path.join(TMP, "legacy-raw")
os.makedirs(raw_src)
three = [c for c in CASES_ALL if c["case_id"] in ("sample_01_clean", "sample_02_rotated", "sample_03_lowcontrast")]
for c in three:
    open(os.path.join(raw_src, c["case_id"] + ".txt"), "w", encoding="utf-8").write(perfect(c["case_id"]))
lrd = os.path.join(TMP, "legacy-run")
fired = {"n": 0}


def crash_second_row(self, name, rec):
    if name == "results.jsonl":
        fired["n"] += 1
        if fired["n"] == 2:
            raise Crash("simulated stop before the second outcome row")
    return real_append(self, name, rec)


with patch.object(RN.RunDir, "append", crash_second_row):
    try:
        import_legacy(raw_src, None, lrd, arm_id="hist", model_label="hist", scorer=e, cases=three)
    except Crash:
        pass
if os.path.exists(os.path.join(lrd, "run.lock")):
    os.remove(os.path.join(lrd, "run.lock"))
again = None
try:
    import_legacy(raw_src, None, lrd, arm_id="hist", model_label="hist", scorer=e, cases=three)
except RN.RunRefused as ex:
    again = str(ex)
rows = [json.loads(l) for l in open(os.path.join(lrd, "results.jsonl"), encoding="utf-8")]
st = json.load(open(os.path.join(lrd, "run_status.json"), encoding="utf-8")) if os.path.exists(os.path.join(lrd, "run_status.json")) else {}
check("REC-14", "a second import after an interruption completes every case once and writes run_status COMPLETE",
      again is None and sorted(r["case_id"] for r in rows) == sorted(c["case_id"] for c in three) and st.get("run_status") == "COMPLETE",
      {"rows": len(rows), "status": st.get("run_status"), "refused": again})
lrd2 = os.path.join(TMP, "legacy-run-tampered")
fired = {"n": 0}
with patch.object(RN.RunDir, "append", crash_second_row):
    try:
        import_legacy(raw_src, None, lrd2, arm_id="hist", model_label="hist", scorer=e, cases=three)
    except Crash:
        pass
if os.path.exists(os.path.join(lrd2, "run.lock")):
    os.remove(os.path.join(lrd2, "run.lock"))
raws = sorted(os.listdir(os.path.join(lrd2, "raw")))
tampered = [p for p in raws if "sample_02" in p]
if tampered:
    pth = os.path.join(lrd2, "raw", tampered[0])
    d = json.load(open(pth, encoding="utf-8")); d["text"] = "edited"; json.dump(d, open(pth, "w", encoding="utf-8"))
ref = None
try:
    import_legacy(raw_src, None, lrd2, arm_id="hist", model_label="hist", scorer=e, cases=three)
except RN.RunRefused as ex:
    ref = str(ex)
check("REC-14b", "a raw file left by the interrupted import that differs from the source refuses the import by name",
      bool(tampered) and ref is not None and "sample_02" in ref, {"tampered": tampered, "refusal": (ref or "")[:120]})


# ---- loopback servers for transport and kill checks
class Counter:
    def __init__(self):
        self.hits, self.lines, self.event = 0, [], threading.Event()


def serve(behaviour):
    counter = Counter()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            counter.hits += 1
            counter.lines.append(self.requestline)
            counter.event.set()
            n = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(n)
            behaviour(self)

        do_GET = do_POST

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, counter


def ok_json(h):
    body = json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "model": "loop"}).encode()
    h.send_response(200); h.send_header("Content-Type", "application/json"); h.send_header("Content-Length", str(len(body)))
    h.end_headers(); h.wfile.write(body)


local = {"arm_id": "loc", "provider": "openai_compatible_local", "route": "local"}
b_srv, b_cnt = serve(ok_json)
b_url = "http://127.0.0.1:%d/v1/chat/completions" % b_srv.server_address[1]


def redirect_to_b(h):
    h.send_response(302); h.send_header("Location", b_url); h.send_header("Content-Length", "0"); h.end_headers()


a_srv, a_cnt = serve(redirect_to_b)
a_url = "http://127.0.0.1:%d/v1/chat/completions" % a_srv.server_address[1]
err = None
try:
    HttpTransport().send(local, a_url, {"Content-Type": "application/json", "Authorization": "Bearer LOOPBACK-TEST-TOKEN"}, {"x": 1}, 5)
except TransportError as ex:
    err = (ex.status, ex.transient, str(ex)[:80])
check("NET-REDIRECT", "a 302 from a local endpoint is not followed: the redirect target receives nothing; the send ends as a "
      "non-transient transport error", a_cnt.hits == 1 and b_cnt.hits == 0 and err is not None and err[1] is False,
      {"first_server": a_cnt.hits, "redirect_target": b_cnt.hits, "error": err})

p_srv, p_cnt = serve(lambda h: (h.send_response(502), h.send_header("Content-Length", "0"), h.end_headers()))
d_srv, d_cnt = serve(ok_json)
d_url = "http://127.0.0.1:%d/v1/chat/completions" % d_srv.server_address[1]
child = textwrap.dedent("""
    import sys; sys.path.insert(0, %r)
    from mmeval.transport import HttpTransport
    try:
        HttpTransport().send({"arm_id": "loc", "provider": "openai_compatible_local", "route": "local"}, %r,
                             {"Content-Type": "application/json"}, {"x": 1}, 5)
        print("sent")
    except Exception as ex:
        print("error", type(ex).__name__, ex)
""") % (TREE, d_url)
env = dict(os.environ, HTTP_PROXY="http://127.0.0.1:%d" % p_srv.server_address[1], http_proxy="http://127.0.0.1:%d" % p_srv.server_address[1])
env.pop("NO_PROXY", None); env.pop("no_proxy", None)
pr = subprocess.run([sys.executable, "-B", "-c", child], capture_output=True, text=True, env=env, timeout=60)
check("NET-PROXY", "HTTP_PROXY in the environment is ignored: the request goes straight to the local endpoint, the proxy sees nothing",
      d_cnt.hits == 1 and p_cnt.hits == 0, {"direct": d_cnt.hits, "proxy": p_cnt.hits, "child": pr.stdout.strip()[:80]})


# ---- KILL: a real child process is killed during a send; a fresh process must not resend
def slow(h):
    time.sleep(60)


k_srv, k_cnt = serve(slow)
k_url = "http://127.0.0.1:%d/v1/messages" % k_srv.server_address[1]
krd = os.path.join(TMP, "kill-run")
arms_k = [arm(provider="openai_compatible_local", route="local", endpoint=k_url, credential_env=None,
              limits={"max_calls": 5, "max_attempts_per_trial": 2, "timeout_s": 120})]
driver = os.path.join(TMP, "driver.py")
open(driver, "w", encoding="utf-8").write(textwrap.dedent("""
    import json, os, sys
    sys.path.insert(0, %r)
    import run_eval as e
    from mmeval import casesets as CS, runner as RN
    from mmeval.transport import HttpTransport
    cases = [c for c in CS.build_case_manifest(os.path.join(%r, "data"), "published-40", 7) if c["case_id"] == "sample_02_rotated"]
    golds = {c["case_id"]: json.load(open(c["gold_path"], encoding="utf-8")) for c in cases}
    arms = json.loads(%r)
    cfg = json.loads(%r)
    m = RN.build_manifest(cfg, arms, cases, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX, scorer_sha256="t",
                          renderer_sha256="t", data_class="public_synthetic")
    RN.execute(m, cfg, arms, cases, golds, %r, HttpTransport(), e, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX, environ={})
""") % (TREE, TREE, json.dumps(arms_k), json.dumps(cfg(arms_k)), krd))
proc = subprocess.Popen([sys.executable, "-B", driver], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
got = k_cnt.event.wait(60)
time.sleep(0.5)
proc.kill()
proc.wait(30)
kill_state = {"request_reached_server": got, "child_exit": proc.returncode,
              "intents": len(open(os.path.join(krd, "intents.jsonl")).read().splitlines()) if os.path.exists(os.path.join(krd, "intents.jsonl")) else 0,
              "raw": len(os.listdir(os.path.join(krd, "raw"))) if os.path.isdir(os.path.join(krd, "raw")) else None}
lock_left = os.path.exists(os.path.join(krd, "run.lock"))
unlock = {}
if hasattr(RN.RunDir, "release_stale_lock") and lock_left:
    try:
        unlock["moved"] = os.path.basename(RN.RunDir(krd).release_stale_lock("owner-test", "child process was killed by the test"))
    except RN.RunRefused as ex:
        unlock["refused"] = str(ex)[:100]
check("KILL-LOCK", "after a real kill the stale run.lock is released by the owner command (process gone), moved aside and logged",
      lock_left and "moved" in unlock and os.path.exists(os.path.join(krd, "owner-actions.jsonl")), dict(kill_state, lock_left=lock_left, unlock=unlock))
sk = Stub()
rk = run(krd, sk, arms=arms_k)
check("KILL-RESUME", "a fresh process after a real kill mid-send sends nothing and refuses the UNRESOLVED attempt",
      got and sk.sends == [] and "UNRESOLVED" in (rk["error"] or ""), dict(kill_state, resume=(rk["error"] or "")[:100], sends=sk.sends))
live_lock = os.path.join(TMP, "live-lock")
rdl = RN.RunDir(live_lock)
rdl.lock()
try:
    rdl.release_stale_lock("owner-test", "should be refused") if hasattr(rdl, "release_stale_lock") else None
    live_ref = "accepted" if hasattr(rdl, "release_stale_lock") else "no unlock tool"
except RN.RunRefused as ex:
    live_ref = "refused: " + str(ex)[:60]
finally:
    rdl.unlock()
check("LOCK-LIVE", "the owner unlock is refused while the recorded process is alive", live_ref.startswith("refused"), live_ref)

for s in (a_srv, b_srv, p_srv, d_srv, k_srv):
    s.shutdown()
n_fail = sum(r["result"] == "FAIL" for r in RES)
print(f"\n{len(RES) - n_fail} PASS · {n_fail} FAIL  (tree: {TREE})")
if OUT:
    json.dump({"results": RES}, open(OUT, "w"), indent=1)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if n_fail else 0)
