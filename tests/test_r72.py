#!/usr/bin/env python3
"""test_r72.py -- focused regressions for the r7.2 successor (ORCA-COLOUR-TO-OPERATIONS-20261101-r1).

Each check states the CORRECT behaviour. On the r7.1 tree the r7.2 checks are expected to FAIL (failing-first evidence);
checks named CTRL-* are controls and must pass on both trees.

    python3 -B test_r72.py <built tree> [--json out.json] [--only GROUP[,GROUP...]]

Groups: D1 R15 V1 V4 V2 D2 V3 D3 D4 V5 P3 (test editions 4-5: Red rounds 1-2 on r7.2-p2/p3). Offline except LOOPBACK sockets on 127.0.0.1 (the transport checks start local HTTP
servers). No provider, model or external host is contacted.
"""
import contextlib, hashlib, http.server, io, json, os, shutil, socket, socketserver, struct, subprocess, sys, tempfile, threading
import time, urllib.request
from unittest.mock import patch

TREE = os.path.abspath(sys.argv[1])
OUT = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
ONLY = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
sys.path.insert(0, TREE)
sys.dont_write_bytecode = True
import run_eval as e  # noqa: E402
from mmeval import casesets as CS, config as C, report as MR, runner as RN  # noqa: E402
from mmeval import transport as T  # noqa: E402
from mmeval.transport import HttpTransport, TransportError  # noqa: E402

TMP = tempfile.mkdtemp(prefix="r72-")
RES = []


def check(cid, name, ok, observed):
    RES.append({"id": cid, "check": name, "result": "PASS" if ok else "FAIL", "observed": observed})
    print(f"{'PASS' if ok else 'FAIL'} {cid} {name}  [{json.dumps(observed, default=str)[:260]}]")


def want(group):
    return ONLY is None or group in ONLY


def guarded(cid, name, fn):
    """Run one check body; an unexpected exception is a FAIL of that check, never a crash of the script."""
    try:
        fn()
    except Exception as ex:  # noqa: BLE001
        check(cid, name, False, "CRASH %s: %s" % (type(ex).__name__, str(ex)[:200]))


def no_net(*a, **k):
    raise AssertionError("network call attempted")


CASES_ALL = CS.build_case_manifest(os.path.join(TREE, "data"), "published-40", 7)
GOLDS = {c["case_id"]: json.load(open(c["gold_path"], encoding="utf-8")) for c in CASES_ALL}
IMG = {hashlib.sha256(__import__("base64").b64encode(open(c["png_path"], "rb").read())).hexdigest(): c["case_id"] for c in CASES_ALL}
ONE = [c for c in CASES_ALL if c["case_id"] == "sample_02_rotated"]
THREE = [c for c in CASES_ALL if c["case_id"] in ("sample_01_clean", "sample_02_rotated", "sample_03_lowcontrast")]
UID = "a1/sample_02_rotated/t1"


def perfect(cid):
    g = GOLDS[cid]
    return json.dumps({"month": g["month"], "days": {d: {"status": c["status"], "note": c["note"]} for d, c in g["days"].items()},
                       "global_notes": list(g.get("global_notes", []))})


def anth(text):
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "model": "stub-served",
            "usage": {"input_tokens": 10, "output_tokens": 10}}


class Crash(Exception):
    pass


def case_of(payload):
    data = payload["messages"][0]["content"][0]["source"]["data"]
    return IMG[hashlib.sha256(data.encode()).hexdigest()]


def is_repair(payload):
    return payload["messages"][0]["content"][-1]["text"].endswith(e.RETRY_SUFFIX)


class Script:
    """Offline stub. answers(case, n, repair) -> text, or an Exception instance to raise. n counts sends per case."""
    name = "stub"

    def __init__(self, answers):
        self.answers, self.sends, self.count = answers, [], {}

    def send(self, arm, url, headers, payload, timeout_s):      # the r7.1 signature, unchanged (R-5)
        cid = case_of(payload)
        self.count[cid] = self.count.get(cid, 0) + 1
        self.sends.append((cid, self.count[cid], is_repair(payload)))
        a = self.answers(cid, self.count[cid], is_repair(payload))
        if isinstance(a, Exception):
            raise a
        return {"json": anth(a), "elapsed_ms": 1, "http_status": 200}


def arm(**over):
    a = {"arm_id": "a1", "role": "test", "provider": "anthropic", "route": "cloud", "endpoint": "https://api.anthropic.com/v1/messages",
         "model_requested": "m", "modalities": ["text", "image"], "image_capability_verified": True, "credential_env": "K",
         "max_output_tokens": 4096, "sampling": {}, "thinking": None, "image_detail": None, "image_preprocessing": "none",
         "allowed_data_classes": ["public_synthetic"], "status": "ready", "dispatch_enabled": True,
         "limits": {"max_calls": 100, "max_attempts_per_trial": 3, "timeout_s": 5}}
    a.update(over)
    return a


def cfg(arms, trials=1, **proto):
    p = {"protocol_id": "t", "trials": trials, "order_seed": "t", "content_repair_retries": 1, "backoff_s": [0]}
    p.update(proto)
    return {"case_set": {"id": "published-40", "data_class": "public_synthetic"}, "protocol": p,
            "dispatch": {"enabled": True}, "run_caps": {"max_calls_total": 1000}, "arms": arms}


def manifest_for(c, arms, cases, scorer_sha="t"):
    return RN.build_manifest(c, arms, cases, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX, scorer_sha256=scorer_sha,
                             renderer_sha256="t", data_class="public_synthetic")


def run(rd, transport, arms=None, cases=None, trials=1, scorer=e, sleep=None, proto=None, block_net=True, manifest=None):
    arms = arms or [arm()]
    cases = cases or ONE
    c = cfg(arms, trials, **(proto or {}))
    m = manifest or manifest_for(c, arms, cases)
    out = {"status": None, "error": None, "manifest": m}
    ctx = [patch.object(urllib.request, "urlopen", side_effect=no_net),
           patch.object(urllib.request.OpenerDirector, "open", side_effect=no_net)] if block_net else []
    with contextlib.ExitStack() as st:
        for p in ctx:
            st.enter_context(p)
        try:
            out["status"] = RN.execute(m, c, arms, cases, GOLDS, rd, transport, scorer, prompt=e.TASK_PROMPT,
                                       retry_suffix=e.RETRY_SUFFIX, environ={"K": "k" * 20},
                                       sleep=sleep or (lambda s: None))
        except Exception as ex:          # noqa: BLE001 -- the check records the exact refusal
            out["error"] = "%s: %s" % (type(ex).__name__, ex)
    out["results"] = read_jsonl(rd, "results.jsonl")
    out["attempts"] = read_jsonl(rd, "attempts.jsonl")
    return out


def read_jsonl(rd, name):
    p = os.path.join(rd, name)
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def drop_lock(rd):
    p = os.path.join(rd, "run.lock")
    if os.path.exists(p):
        os.remove(p)        # scaffolding: an in-process crash cannot release its own lock


def replay_transport(src):
    from mmeval.replay import ReplayTransport
    return ReplayTransport(src)


class ChangedScorer:
    """A re-scoring scorer: GARBAGE_T1 now parses (as the perfect answer), MARK_T2 no longer parses."""

    def __init__(self, cid):
        self.cid = cid

    def parse_json(self, text):
        if "GARBAGE_T1" in text:
            return json.loads(perfect(self.cid))
        if "MARK_T2" in text:
            return None
        return e.parse_json(text)

    def __getattr__(self, k):
        return getattr(e, k)


# =============================================================== D1 replay identity (+ R-14)
if want("D1"):
    def d1_changed_scorer():
        src = os.path.join(TMP, "d1-src-a")
        def ans(cid, n, rep):
            return {1: "GARBAGE_T1", 2: perfect(cid), 3: perfect(cid) + "\nMARK_T2"}[n]
        s = run(src, Script(ans), trials=2)
        new = os.path.join(TMP, "d1-new-a")
        r = run(new, replay_transport(src), trials=2, scorer=ChangedScorer("sample_02_rotated"))
        rows = {x["unit_id"]: x for x in r["results"]}
        t2 = rows.get("a1/sample_02_rotated/t2", {})
        t2_att = [a for a in r["attempts"] if a["unit_id"] == "a1/sample_02_rotated/t2"]
        served_t1_repair = any(a.get("attempt") == 2 and a.get("result") == "response" for a in t2_att)
        check("D1-A", "changed-scorer replay: trial 2 never receives trial 1's stored repair answer; it ends unavailable, marked "
              "replay_identity", s["error"] is None and r["error"] is None and not served_t1_repair
              and t2.get("outcome") == "unavailable" and t2.get("unavailable_reason") == "replay_identity",
              {"src_error": s["error"], "error": r["error"], "t2": {k: t2.get(k) for k in ("outcome", "attempts", "unavailable_reason")},
               "t2_attempts": [(a["attempt"], a["result"]) for a in t2_att]})
    guarded("D1-A", "changed-scorer replay misattribution", d1_changed_scorer)

    def d1_resumed_replay():
        src = os.path.join(TMP, "d1-src-b")
        def ans(cid, n, rep):
            return TransportError("HTTP 503: busy", status=503, transient=True) if n == 1 else perfect(cid)
        s = run(src, Script(ans))
        new = os.path.join(TMP, "d1-new-b")
        def boom(_):
            raise Crash("simulated stop during the backoff after attempt 1")
        r1 = run(new, replay_transport(src), sleep=boom)
        drop_lock(new)
        r2 = run(new, replay_transport(src))          # the REPLAY run resumes, with a fresh transport
        att = [(a["attempt"], a["result"]) for a in r2["attempts"]]
        check("D1-B", "a resumed REPLAY run replays the source's attempt 2 for attempt 2 (not the stored attempt-1 error again)",
              s["error"] is None and "Crash" in (r1["error"] or "") and r2["error"] is None and att == [(1, "transport_error"), (2, "response")]
              and [x["outcome"] for x in r2["results"]] == ["scored"],
              {"first": r1["error"], "attempts": att, "rows": [(x["outcome"], x["attempts"]) for x in r2["results"]]})
    guarded("D1-B", "resumed replay run", d1_resumed_replay)

    def d1_mismatch():
        src = os.path.join(TMP, "d1-src-c")
        s = run(src, Script(lambda cid, n, rep: "GARBAGE" if n == 1 else perfect(cid)))
        p = os.path.join(src, "attempts.jsonl")
        rows = read_jsonl(src, "attempts.jsonl")
        rows[1]["request_sha256"] = "0" * 64           # the stored attempt 2 was produced by a different request
        open(p, "w", encoding="utf-8").write("".join(json.dumps(x, sort_keys=True) + "\n" for x in rows))
        ip = os.path.join(src, "intents.jsonl")
        ints = read_jsonl(src, "intents.jsonl")
        ints[1]["request_sha256"] = "0" * 64
        open(ip, "w", encoding="utf-8").write("".join(json.dumps(x, sort_keys=True) + "\n" for x in ints))
        new = os.path.join(TMP, "d1-new-c")
        r = run(new, replay_transport(src))
        row = (r["results"] or [{}])[0]
        check("D1-C", "a stored attempt whose request hash differs from the new request is not served: unavailable, replay_identity",
              s["error"] is None and r["error"] is None and row.get("outcome") == "unavailable"
              and row.get("unavailable_reason") == "replay_identity",
              {"error": r["error"], "row": {k: row.get(k) for k in ("outcome", "attempts", "error", "unavailable_reason")}})
    guarded("D1-C", "request-hash mismatch", d1_mismatch)

    def d1_duplicate_and_unreconciled():
        src = os.path.join(TMP, "d1-src-d")
        run(src, Script(lambda cid, n, rep: perfect(cid)))
        open(os.path.join(src, "attempts.jsonl"), "a", encoding="utf-8").write(open(os.path.join(src, "attempts.jsonl"), encoding="utf-8").readline())
        err = None
        try:
            replay_transport(src)
        except Exception as ex:  # noqa: BLE001
            err = "%s: %s" % (type(ex).__name__, ex)
        check("D1-D", "a source with a duplicate (unit, attempt) row is refused when the replay is built",
              err is not None and "RunRefused" in err and "duplicate" in err.lower(), err)
        src2 = os.path.join(TMP, "d1-src-e")
        run(src2, Script(lambda cid, n, rep: perfect(cid)))
        open(os.path.join(src2, "intents.jsonl"), "a", encoding="utf-8").write(json.dumps(
            {"unit_id": UID, "attempt": 2, "kind": "transport_retry", "ts": "x", "prompt_variant": "task",
             "request_sha256": "1" * 64, "endpoint": "e"}) + "\n")
        err2 = None
        try:
            replay_transport(src2)
        except Exception as ex:  # noqa: BLE001
            err2 = "%s: %s" % (type(ex).__name__, ex)
        check("D1-E", "an unreconciled source (an intent with no attempt row) is refused when the replay is built",
              err2 is not None and "RunRefused" in err2, err2)
    guarded("D1-D", "duplicate / unreconciled source", d1_duplicate_and_unreconciled)

    def d1_unbound_send():
        src = os.path.join(TMP, "d1-src-f")
        run(src, Script(lambda cid, n, rep: perfect(cid)))
        rt = replay_transport(src)
        a = arm()
        from mmeval.adapters import build_request
        url, headers, payload = build_request(a, open(ONE[0]["png_path"], "rb").read(), "image/png", e.TASK_PROMPT, credential="k" * 20)
        res = []
        for label in ("unbound", "bound", "reused-bind"):
            if label == "bound" and hasattr(rt, "bind_identity"):
                rt.bind_identity(UID, 1)
            try:
                rt.send(a, url, headers, payload, 5)
                res.append((label, "served"))
            except TransportError as ex:
                res.append((label, "refused:" + ("replay_identity" if "replay_identity" in str(ex) else str(ex)[:40])))
        check("D1-F", "a replay send without a fresh single-use bind_identity(unit, attempt) is refused (replay_identity); a bound "
              "send is served once", res == [("unbound", "refused:replay_identity"), ("bound", "served"),
                                          ("reused-bind", "refused:replay_identity")], res)
    guarded("D1-F", "unbound send", d1_unbound_send)

    def d1_control_identical():
        src = os.path.join(TMP, "d1-src-g")
        def ans(cid, n, rep):
            if cid == "sample_01_clean":
                return perfect(cid)
            if cid == "sample_02_rotated":
                return "GARBAGE" if n == 1 else perfect(cid)
            return TransportError("HTTP 400: bad", status=400, transient=False)
        s = run(src, Script(ans), cases=THREE)
        new = os.path.join(TMP, "d1-new-g")
        r = run(new, replay_transport(src), cases=THREE)
        a = sorted((x["unit_id"], x["outcome"], x["attempts"]) for x in s["results"])
        b = sorted((x["unit_id"], x["outcome"], x["attempts"]) for x in r["results"])
        check("CTRL-D1-G", "an identical-manifest replay reproduces every outcome and attempt count", a == b and r["error"] is None,
              {"source": a, "replay": b, "error": r["error"]})
    guarded("CTRL-D1-G", "identical replay control", d1_control_identical)

    def d1_report_marker():
        new = os.path.join(TMP, "d1-new-a")
        rep = MR.build_report([(MR.load_run(new), "a1")], GOLDS, e, [])
        acc = rep["arms"]["a1"]["accounting"]
        check("D1-H", "the report counts replay_identity units beside the ITT rate", acc.get("replay_identity_units") == 1,
              {k: acc.get(k) for k in ("unavailable", "replay_identity_units", "unusable_rate")})
    guarded("D1-H", "report marker", d1_report_marker)


# =============================================================== R15 + D1(d): the full mm_run.py replay CLI path
def tree_copy(name):
    dst = os.path.join(TMP, name)
    shutil.copytree(TREE, dst, ignore=shutil.ignore_patterns("results*", "mm_runs", "__pycache__", ".git", "tests"))
    return dst


def cli(tree, *args):
    p = subprocess.run([sys.executable, "-B", os.path.join(tree, "mm_run.py"), *args], cwd=tree, capture_output=True, text=True,
                       timeout=600)
    return p.returncode, p.stdout[-400:], p.stderr[-600:]


def write_cli_config(tree, trials=1):
    conf = {"config_version": "r72-test", "case_set": {"id": "published-40", "data_dir": "data", "seed_base": 7,
                                                       "data_class": "public_synthetic", "include": ["sample_02_rotated"]},
            "protocol": {"protocol_id": "r72", "trials": trials, "order_seed": "r72", "content_repair_retries": 1, "backoff_s": [0]},
            "dispatch": {"enabled": False}, "run_caps": {"max_calls_total": 100}, "trusted_local_hosts": [], "arms": [arm()]}
    p = os.path.join(tree, "configs", "r72-test-%d.json" % trials)
    json.dump(conf, open(p, "w", encoding="utf-8"), indent=1)
    return p


def cli_source(tree, conf, name):
    """A source run built with the CLI's own manifest (mm_run._load), answered by an offline stub."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mm_run_" + name, os.path.join(tree, "mm_run.py"))
    m = importlib.util.module_from_spec(spec)
    old = sys.path[:]
    sys.path.insert(0, tree)
    try:
        spec.loader.exec_module(m)
        cfg_, arms, cases, golds, manifest = m._load(conf, os.path.join(tree, "data"))
        src = os.path.join(TMP, name)
        RN.execute(manifest, cfg_, arms, cases, golds, src, Script(lambda cid, n, rep: perfect(cid)), e, prompt=e.TASK_PROMPT,
                   retry_suffix=e.RETRY_SUFFIX, environ={"K": "k" * 20}, sleep=lambda s: None)
    finally:
        sys.path[:] = old
    return src


if want("R15") or want("D1"):
    def r15():
        tree = tree_copy("cli-tree")
        conf = write_cli_config(tree)
        src = cli_source(tree, conf, "cli-src")
        same = cli(tree, "replay", "--config", conf, "--data", "data", "--from", src, "--run-dir", os.path.join(TMP, "cli-new-1"))
        check("CTRL-D1-CLI", "mm_run.py replay (identical manifest) runs the stored answers to the same outcome; exit 0",
              same[0] == 0, same)
        with open(os.path.join(tree, "run_eval.py"), "a", encoding="utf-8") as f:
            f.write("\n# r72 test: a scorer edit that changes the scorer hash only\n")
        no_flag = cli(tree, "replay", "--config", conf, "--data", "data", "--from", src, "--run-dir", os.path.join(TMP, "cli-new-2"))
        flag = cli(tree, "replay", "--config", conf, "--data", "data", "--from", src, "--run-dir", os.path.join(TMP, "cli-new-3"),
                   "--allow-changed-scorer")
        check("CTRL-R15-A", "a changed scorer is refused without the flag (exit 2) and replayed with it (exit 0)",
              no_flag[0] == 2 and flag[0] == 0, {"no_flag": no_flag[0], "flag": flag[:2]})
        conf2 = write_cli_config(tree, trials=2)
        src2 = cli_source(tree, conf2, "cli-src-2trials")
        other = cli(tree, "replay", "--config", conf, "--data", "data", "--from", src2, "--run-dir", os.path.join(TMP, "cli-new-4"),
                    "--allow-changed-scorer")
        check("R15-B", "--allow-changed-scorer refuses a source whose manifest differs in more than the scorer (here: trials)",
              other[0] == 2 and "scorer" in (other[2] or "").lower(), other)
    guarded("R15-B", "changed-scorer flag scope", r15)


# =============================================================== V1 replay of an owner-settled attempt
def unresolved_source(name, decision):
    rd = os.path.join(TMP, name)
    real_save = RN.RunDir.save_raw
    fired = {"done": False}

    def save_raw(self, unit_id, n, obj):
        if not fired["done"]:
            fired["done"] = True
            raise Crash("simulated stop before the raw response was saved")
        return real_save(self, unit_id, n, obj)

    with patch.object(RN.RunDir, "save_raw", save_raw):
        run(rd, Script(lambda cid, n, rep: perfect(cid)))
    drop_lock(rd)
    RN.RunDir(rd).settle(UID, 1, decision, "owner-test", "test settlement")
    run(rd, Script(lambda cid, n, rep: perfect(cid)))   # applies the settlement
    return rd


if want("V1"):
    def v1():
        src = unresolved_source("v1-src-u", "count_unavailable")
        new = os.path.join(TMP, "v1-new-u")
        r = run(new, replay_transport(src))
        row = (r["results"] or [{}])[0]
        again = run(new, replay_transport(src))
        check("V1-A", "replay of a source attempt settled 'count_unavailable' ends unavailable naming the settlement; no crash; "
              "a rerun of the replay directory finds nothing unresolved",
              r["error"] is None and row.get("outcome") == "unavailable" and "count_unavailable" in (row.get("error") or "")
              and row.get("unavailable_reason") is None and again["error"] is None,
              {"error": r["error"], "row": {k: row.get(k) for k in ("outcome", "error")}, "rerun": again["error"]})
        src2 = unresolved_source("v1-src-r", "resend_authorized")
        new2 = os.path.join(TMP, "v1-new-r")
        r2 = run(new2, replay_transport(src2))
        att = [(a["attempt"], a["result"]) for a in r2["attempts"]]
        check("V1-B", "replay of 'resend_authorized' replays the next stored attempt within the limit: scored at attempt 2",
              r2["error"] is None and [x["outcome"] for x in r2["results"]] == ["scored"] and att[-1] == (2, "response"),
              {"error": r2["error"], "attempts": att})
    guarded("V1-A", "settled replay", v1)


# =============================================================== V4 + R-3 + R-13: malformed and ambiguous HTTP outcomes
class Srv:
    def __init__(self, mode):
        self.mode, self.posts = mode, 0
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                outer.posts += 1
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)
                outer.behave(self)

        class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.srv = S(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/v1/chat/completions" % self.srv.server_address[1]

    def ok(self, h):
        body = json.dumps({"choices": [{"message": {"content": perfect("sample_02_rotated")}, "finish_reason": "stop"}],
                           "model": "loop", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode()
        h.send_response(200); h.send_header("Content-Type", "application/json"); h.send_header("Content-Length", str(len(body)))
        h.end_headers(); h.wfile.write(body)

    def behave(self, h):
        m = self.mode
        if m == "ok" or (m in ("503-then-ok", "ambiguous-then-ok") and self.posts > 1):
            return self.ok(h)
        if m == "503-then-ok":
            body = b'{"error":"busy"}'
            h.send_response(503); h.send_header("Content-Length", str(len(body))); h.end_headers(); h.wfile.write(body)
            return
        if m == "nonjson":
            body = b"not json at all"
            h.send_response(200); h.send_header("Content-Length", str(len(body))); h.end_headers(); h.wfile.write(body)
            return
        if m == "stall":
            h.send_response(200); h.send_header("Content-Length", "100"); h.end_headers(); h.wfile.flush(); time.sleep(3)
            return
        if m == "short":
            h.send_response(200); h.send_header("Content-Length", "100"); h.end_headers(); h.wfile.write(b'{"choices"'); h.wfile.flush()
            h.close_connection = True
            return
        if m == "reset":
            h.send_response(200); h.send_header("Content-Length", "100"); h.end_headers(); h.wfile.write(b'{"choices"'); h.wfile.flush()
            h.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            h.connection.close()
            return
        if m in ("ambiguous", "ambiguous-then-ok"):
            time.sleep(3)              # no status line before the client's timeout: the request was received
            return

    def close(self):
        self.srv.shutdown()


def local_arm(url, attempts=3):
    return {"arm_id": "loc", "role": "test", "provider": "openai_compatible_local", "route": "local", "endpoint": url,
            "model_requested": "loop", "modalities": ["text", "image"], "image_capability_verified": True, "credential_env": None,
            "max_output_tokens": 256, "sampling": {}, "thinking": None, "image_detail": None, "image_preprocessing": "none",
            "allowed_data_classes": ["public_synthetic"], "status": "ready", "dispatch_enabled": True,
            "limits": {"max_calls": 100, "max_attempts_per_trial": attempts, "timeout_s": 1}}


def http_run(name, mode, proto=None):
    s = Srv(mode)
    try:
        rd = os.path.join(TMP, name)
        a = local_arm(s.url)
        r = run(rd, HttpTransport(), arms=[a], block_net=False, proto=proto)
        r["posts"] = s.posts
        r["raw"] = {f: json.load(open(os.path.join(rd, "raw", f), encoding="utf-8")) for f in sorted(os.listdir(os.path.join(rd, "raw")))} \
            if os.path.isdir(os.path.join(rd, "raw")) else {}
        r2 = run(rd, HttpTransport(), arms=[a], block_net=False, proto=proto)     # a rerun must find nothing to send or resolve
        r["rerun_error"], r["posts_after_rerun"] = r2["error"], s.posts
        return r
    finally:
        s.close()


if want("V4"):
    for mode, cid in (("nonjson", "V4-A"), ("stall", "V4-B"), ("short", "V4-C"), ("reset", "V4-D")):
        def body(mode=mode, cid=cid):
            r = http_run("v4-" + mode, mode)
            att = [(a["attempt"], a["result"]) for a in r["attempts"]]
            raw = list(r["raw"].values())
            malformed = (att == [(1, "bad_provider_shape")] and len(raw) == 1 and raw[0].get("kind") == "malformed_2xx"
                         and raw[0].get("status") == 200)
            # test edition 3: a TCP reset can discard the received status line before the client reads it (Windows, WB
            # 2026-11-01); the client then never saw a 2xx and the send is AMBIGUOUS. Either way: exactly one POST, no resend.
            ambiguous = (mode == "reset" and att == [(1, "transport_error")] and not raw
                         and bool((r["attempts"] or [{}])[0].get("ambiguous")))
            check(cid, "a 2xx whose body cannot be read or decoded (%s) is never resent: one POST, recorded as malformed_2xx "
                  "(bad_provider_shape)%s, unavailable, nothing unresolved on rerun" % (
                      mode, " or, when the reset arrives before the status line, as an ambiguous send" if mode == "reset" else ""),
                  r["error"] is None and r["posts"] == 1 and (malformed or ambiguous)
                  and [x["outcome"] for x in r["results"]] == ["unavailable"]
                  and r["rerun_error"] is None and r["posts_after_rerun"] == 1,
                  {"error": r["error"], "posts": r["posts"], "attempts": att, "raw_kind": [x.get("kind") for x in raw],
                   "path": "malformed" if malformed else ("ambiguous" if ambiguous else "neither"),
                   "rerun": r["rerun_error"], "posts_after": r["posts_after_rerun"]})
        guarded(cid, "malformed 2xx " + mode, body)

    def v4_controls():
        r = http_run("v4-ok", "ok")
        check("CTRL-V4-OK", "a valid JSON 200 is scored as before (one POST)", r["error"] is None and r["posts"] == 1
              and [x["outcome"] for x in r["results"]] == ["scored"], {"error": r["error"], "posts": r["posts"],
                                                                       "rows": [x["outcome"] for x in r["results"]]})
        r = http_run("v4-503", "503-then-ok")
        check("CTRL-V4-503", "an HTTP 503 is still transient: retried once, then scored", r["error"] is None and r["posts"] == 2
              and [x["outcome"] for x in r["results"]] == ["scored"], {"error": r["error"], "posts": r["posts"]})
        rd = os.path.join(TMP, "v4-refused")
        sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close()
        r = run(rd, HttpTransport(), arms=[local_arm("http://127.0.0.1:%d/v1/chat/completions" % port)], block_net=False)
        att = [(a["attempt"], a["result"], a.get("transient")) for a in r["attempts"]]
        check("CTRL-V4-REFUSED", "a refused connection (nothing reached a provider) stays transient: all 3 attempts used",
              r["error"] is None and att == [(1, "transport_error", True), (2, "transport_error", True), (3, "transport_error", True)],
              att)
    guarded("CTRL-V4-OK", "transport controls", v4_controls)

    def v4_ambiguous():
        r = http_run("v4-amb", "ambiguous-then-ok")
        att = [(a["attempt"], a["result"], bool(a.get("ambiguous"))) for a in r["attempts"]]
        check("V4-E", "no status line before the timeout is AMBIGUOUS (the request may have been received): by default it is not "
              "resent; the unit ends unavailable and the attempt is marked ambiguous",
              r["error"] is None and r["posts"] == 1 and att == [(1, "transport_error", True)]
              and [x["outcome"] for x in r["results"]] == ["unavailable"], {"posts": r["posts"], "attempts": att, "error": r["error"]})
        r = http_run("v4-amb-owner", "ambiguous-then-ok", proto={"ambiguous_resend": True})
        att = [(a["attempt"], a["result"], bool(a.get("ambiguous_resend"))) for a in r["attempts"]]
        check("V4-F", "with the owner setting protocol.ambiguous_resend true (recorded in the manifest) the send is retried and the "
              "retry row is marked ambiguous_resend", r["error"] is None and r["posts"] == 2 and att[-1] == (2, "response", True)
              and r["manifest"]["protocol"].get("ambiguous_resend") is True, {"posts": r["posts"], "attempts": att})
    guarded("V4-E", "ambiguous send", v4_ambiguous)

    def v4_crash_window():
        rd = os.path.join(TMP, "v4-window")
        a = local_arm("http://127.0.0.1:9/v1/chat/completions")
        os.makedirs(os.path.join(rd, "raw"), exist_ok=True)
        c = cfg([a])
        m = manifest_for(c, [a], ONE)
        json.dump(m, open(os.path.join(rd, "manifest.json"), "w", encoding="utf-8"), indent=1, sort_keys=True)
        uid = "loc/sample_02_rotated/t1"
        from mmeval.adapters import build_request
        _, _, pl = build_request(a, open(ONE[0]["png_path"], "rb").read(), "image/png", e.TASK_PROMPT, credential=None)
        open(os.path.join(rd, "intents.jsonl"), "w", encoding="utf-8").write(json.dumps(
            {"unit_id": uid, "attempt": 1, "kind": "initial", "ts": "x", "prompt_variant": "task",
             "request_sha256": C.canonical_hash(T._scrub_payload(pl)), "endpoint": a["endpoint"]}) + "\n")
        json.dump({"unit_id": uid, "attempt": 1, "kind": "malformed_2xx", "status": 200, "body_text": "not json",
                   "body_truncated": False, "error": "JSONDecodeError: Expecting value", "provider_json": None},
                  open(os.path.join(rd, "raw", RN._safe(uid) + ".a1.json"), "w", encoding="utf-8"))
        st = Script(lambda cid, n, rep: perfect(cid))
        r = run(rd, st, arms=[a], manifest=m)
        att = [(x["attempt"], x["result"], x.get("recovered")) for x in r["attempts"]]
        check("V4-G", "the crash window (a malformed raw record saved, no attempt row) is rebuilt as bad_provider_shape on resume: "
              "no UNRESOLVED refusal, no send", r["error"] is None and st.sends == [] and att == [(1, "bad_provider_shape", "from_raw")]
              and [x["outcome"] for x in r["results"]] == ["unavailable"], {"error": (r["error"] or "")[:120], "attempts": att,
                                                                             "sends": st.sends})
        new = os.path.join(TMP, "v4-window-replay")
        r2 = run(new, replay_transport(rd), arms=[a], manifest=m)
        att2 = [(x["attempt"], x["result"]) for x in r2["attempts"]]
        check("V4-H", "replaying a source whose attempt is a malformed 2xx reproduces bad_provider_shape without a crash",
              r2["error"] is None and att2 == [(1, "bad_provider_shape")], {"error": r2["error"], "attempts": att2})
    guarded("V4-G", "malformed crash window", v4_crash_window)


# =============================================================== V2 + R-2: stale-lock release identity
LOCK_WRITER = """
import sys, os
sys.path.insert(0, %r)
sys.dont_write_bytecode = True
from mmeval import runner as RN
rd = RN.RunDir(%r)
rd.lock()
os._exit(0)
"""

if want("V2"):
    def v2():
        here = RN.proc_identity(os.getpid())
        results = {}

        def attempt(label, content, expect_release):
            d = os.path.join(TMP, "v2-" + label)
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "run.lock")
            if content is not None:
                open(p, "w", encoding="utf-8").write(content)
            before = open(p, "rb").read() if os.path.exists(p) else None
            try:
                RN.RunDir(d).release_stale_lock("owner-test", "test")
                got = "released"
            except RN.RunRefused as ex:
                got = "refused"
            after = open(p, "rb").read() if os.path.exists(p) else None
            ok = (got == "released") if expect_release else (got == "refused" and after == before)
            results[label] = (got, ok)
            return d

        # a dead pid on this host: a child writes the lock with this tree's RunDir.lock(), then exits without unlocking
        dead_dir = os.path.join(TMP, "v2-dead-same-host")
        subprocess.run([sys.executable, "-c", LOCK_WRITER % (TREE, dead_dir)], check=True, timeout=60)
        dead = json.load(open(os.path.join(dead_dir, "run.lock"), encoding="utf-8"))
        r71_format = json.dumps({"pid": dead["pid"], "pid_start": dead.get("pid_start") or "1", "since": "x"})
        other_host = json.dumps(dict(dead, host={"name": "elsewhere", "id": "another-machine"}))
        attempt("empty", "", False)
        attempt("torn", '{"pid": 12', False)
        attempt("nonjson", "hello", False)
        attempt("string-pid", json.dumps({"pid": str(dead["pid"]), "pid_start": "1", "since": "x"}), False)
        attempt("no-host-r71-format", r71_format, False)
        attempt("other-host", other_host, False)
        attempt("alive-null-start", json.dumps(dict(dead, pid=os.getpid(), pid_start=None)), False)
        live = os.path.join(TMP, "v2-live")
        lrd = RN.RunDir(live)
        lrd.lock()
        try:
            try:
                lrd.release_stale_lock("owner-test", "test")
                results["CTRL-live"] = ("released", False)
            except RN.RunRefused:
                results["CTRL-live"] = ("refused", True)
        finally:
            lrd.unlock()
        try:
            RN.RunDir(dead_dir).release_stale_lock("owner-test", "test")
            logged = read_jsonl(dead_dir, "owner-actions.jsonl")
            results["CTRL-dead-same-host"] = ("released", len(logged) == 1)
        except RN.RunRefused as ex:
            results["CTRL-dead-same-host"] = ("refused: " + str(ex)[:80], False)
        refusals = {k: v for k, v in results.items() if not k.startswith("CTRL")}
        check("V2-A", "unlock refuses every lock whose owner cannot be positively identified on this host (empty, torn, non-JSON, "
              "string pid, r7.1 format without host, another host, alive with no start time); the lock bytes are unchanged",
              all(ok for _, ok in refusals.values()), refusals)
        check("CTRL-V2-B", "unlock still refuses a live owner and releases (and logs) a dead same-host owner",
              results["CTRL-live"][1] and results["CTRL-dead-same-host"][1],
              {k: v for k, v in results.items() if k.startswith("CTRL")})
        check("V2-C", "a lock written by this tree names its host (name and instance id)",
              isinstance(dead.get("host"), dict) and bool(dead["host"].get("name")) and bool(dead["host"].get("id")), dead)

        d = os.path.join(TMP, "v2-logfail")
        subprocess.run([sys.executable, "-c", LOCK_WRITER % (TREE, d)], check=True, timeout=60)
        os.makedirs(os.path.join(d, "owner-actions.jsonl"))       # the log append will fail after the lock is moved
        msg = None
        try:
            RN.RunDir(d).release_stale_lock("owner-test", "test")
        except Exception as ex:  # noqa: BLE001
            msg = "%s: %s" % (type(ex).__name__, ex)
        moved = [f for f in os.listdir(d) if f.startswith("run.lock.stale-")]
        check("V2-D", "if logging fails after the lock was moved, the refusal says the lock WAS moved and where",
              msg is not None and "RunRefused" in msg and bool(moved) and moved[0] in msg, {"msg": msg, "moved": moved})
    guarded("V2-A", "lock identity", v2)


# =============================================================== D2 legacy import prefix  ·  V3 refusal status
def legacy_raw(name, cases, with_retry=()):
    raw = os.path.join(TMP, name)
    os.makedirs(raw, exist_ok=True)
    for c in cases:
        if c["case_id"] in with_retry:
            open(os.path.join(raw, c["case_id"] + ".txt"), "w", encoding="utf-8").write("GARBAGE")
            open(os.path.join(raw, c["case_id"] + ".retry.txt"), "w", encoding="utf-8").write(perfect(c["case_id"]))
        else:
            open(os.path.join(raw, c["case_id"] + ".txt"), "w", encoding="utf-8").write(perfect(c["case_id"]))
    return raw


def snapshot(rd):
    out = {}
    for dp, dn, fn in os.walk(rd):
        for f in fn:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, rd)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


if want("D2") or want("V3") or want("P3"):
    from mmeval.replay import import_legacy

if want("D2"):
    def d2():
        raw = legacy_raw("d2-raw", THREE, with_retry=("sample_02_rotated",))
        rd = os.path.join(TMP, "d2-run")
        os.makedirs(os.path.join(rd, "raw"))
        uid = "hist/sample_02_rotated/t1"
        rf = "raw/" + RN._safe(uid) + ".a2.json"
        json.dump({"text": perfect("sample_02_rotated"), "provider_json": None, "legacy_file": True},
                  open(os.path.join(rd, rf), "w", encoding="utf-8"))
        open(os.path.join(rd, "attempts.jsonl"), "w", encoding="utf-8").write(json.dumps(
            {"unit_id": uid, "attempt": 2, "kind": "content_repair", "result": "response", "finish": "stop", "raw_file": rf, "ts": "legacy",
             "request_sha256": None, "usage": {}}, sort_keys=True) + "\n")
        # the first import creates the manifest; seed it so the state check below sees this prior state
        before = None
        err = None
        try:
            import_legacy(raw, None, rd, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        except RN.RunRefused as ex:
            err = str(ex)
        att = read_jsonl(rd, "attempts.jsonl")
        mine = sorted(a["attempt"] for a in att if a["unit_id"] == uid)
        raws = sorted(f for f in os.listdir(os.path.join(rd, "raw")) if "sample_02" in f)
        check("D2-A", "a prior state that is not a prefix (attempt 2 recorded without attempt 1) is refused BEFORE any write for that "
              "case: no attempt-1 row or raw file appears", err is not None and "sample_02_rotated" in err and mine == [2]
              and raws == [RN._safe(uid) + ".a2.json"], {"refusal": (err or "")[:140], "attempts": mine, "raw": raws})
        rd2 = os.path.join(TMP, "d2-run-interrupted")
        os.makedirs(os.path.join(rd2, "raw"))
        json.dump({"text": "GARBAGE", "provider_json": None, "legacy_file": True},
                  open(os.path.join(rd2, "raw", RN._safe(uid) + ".a1.json"), "w", encoding="utf-8"))
        err2 = None
        try:
            import_legacy(raw, None, rd2, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        except RN.RunRefused as ex:
            err2 = str(ex)
        rows = read_jsonl(rd2, "results.jsonl")
        check("CTRL-D2-B", "an interrupted import (raw file for the next attempt only, no row) resumes and completes every case once",
              err2 is None and sorted(r["case_id"] for r in rows) == sorted(c["case_id"] for c in THREE),
              {"refusal": err2, "rows": len(rows)})
    guarded("D2-A", "legacy prefix", d2)

if want("V3"):
    def v3():
        raw = legacy_raw("v3-raw", THREE)
        rd = os.path.join(TMP, "v3-run")
        import_legacy(raw, None, rd, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        old_status = open(os.path.join(rd, "run_status.json"), "rb").read()
        os.remove(os.path.join(rd, "results.jsonl"))            # the run's results are gone; its status still says COMPLETE
        p = [f for f in os.listdir(os.path.join(rd, "raw")) if "sample_02" in f][0]
        d = json.load(open(os.path.join(rd, "raw", p), encoding="utf-8")); d["text"] = "edited"
        json.dump(d, open(os.path.join(rd, "raw", p), "w", encoding="utf-8"))
        err = None
        try:
            import_legacy(raw, None, rd, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        except RN.RunRefused as ex:
            err = str(ex)
        files = os.listdir(rd)
        kept = [f for f in files if f.startswith("run_status.before-refusal-")]
        new = json.load(open(os.path.join(rd, "run_status.json"), encoding="utf-8"))
        refusals = read_jsonl(rd, "import-refusals.jsonl")
        check("V3-A", "an import refusal preserves the old status under a new name (bytes unchanged), writes IMPORT_REFUSED naming "
              "it, and appends a refusal row", err is not None and len(kept) == 1
              and open(os.path.join(rd, kept[0]), "rb").read() == old_status and new.get("run_status") == "IMPORT_REFUSED"
              and new.get("previous_status_file") == kept[0] and len(refusals) == 1 and "sample_02" in refusals[0].get("reason", ""),
              {"refusal": (err or "")[:80], "kept": kept, "status": new.get("run_status"), "refusal_rows": len(refusals)})
        raw2 = legacy_raw("v3-raw-ok", THREE)
        rd2 = os.path.join(TMP, "v3-run-ok")
        import_legacy(raw2, None, rd2, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        st = json.load(open(os.path.join(rd2, "run_status.json"), encoding="utf-8"))
        check("CTRL-V3-B", "a successful import still writes COMPLETE and no refusal files", st.get("run_status") == "COMPLETE"
              and not os.path.exists(os.path.join(rd2, "import-refusals.jsonl")), st.get("run_status"))
    guarded("V3-A", "refusal status", v3)


# =============================================================== D3 every summary rate has a named denominator
EXPECTED_TOP = ["accounting.unusable_rate", "extended.status_error_rate", "extended.false_unavailable_rate",
                "extended.doc_status_exact_rate_conditional", "extended.doc_success_rate_itt"]
SLICE_KEYS = ["status_error_rate", "false_unavailable_rate", "doc_status_exact_rate_conditional"]
HIST_KEYS = ["day_accuracy", "critical_error_rate", "note_mismatch_rate", "hallucination_rate", "note_fidelity", "format_validity"]
REP_KEYS = ["mean_fraction_of_days_where_trials_disagree", "mean_within_case_sd_day_accuracy"]

if want("D3"):
    def d3():
        rd = os.path.join(TMP, "d3-run")
        run(rd, Script(lambda cid, n, rep: perfect(cid)), cases=THREE, trials=2)
        rep = MR.build_report([(MR.load_run(rd), "a1")], GOLDS, e, [])
        s = rep["arms"]["a1"]
        den = s.get("denominators") or {}
        slices = sorted(s["extended"]["per_slice"])
        expected = EXPECTED_TOP + ["historic_conditional." + k for k in HIST_KEYS] \
            + ["extended.per_slice.%s.%s" % (sl, k) for sl in slices for k in SLICE_KEYS] + ["extended.repetition." + k for k in REP_KEYS]
        missing = [k for k in expected if not (isinstance(den.get(k), str) and len(den[k].strip()) >= 10)]
        check("D3-A", "the arm summary's 'denominators' map names a denominator (text of 10+ characters) for every rate in the "
              "explicit expected list (top level, historic, per slice, repetition)", not missing,
              {"missing": missing[:8], "n_missing": len(missing), "n_expected": len(expected)})
        check("CTRL-D3-B", "the r7.1 extended.rate_denominators block is unchanged (ACC-02b)",
              {"status_error_rate", "false_unavailable_rate", "doc_status_exact_rate_conditional", "doc_success_rate_itt"}
              <= set(s["extended"].get("rate_denominators") or {}), sorted(s["extended"].get("rate_denominators") or {}))
    guarded("D3-A", "denominators", d3)


# =============================================================== D4 malformed run state in settle / unlock
def unresolved_for_cli(rd):
    real_save = RN.RunDir.save_raw
    fired = {"done": False}

    def save_raw(self, unit_id, n, obj):
        if not fired["done"]:
            fired["done"] = True
            raise Crash("stop")
        return real_save(self, unit_id, n, obj)

    with patch.object(RN.RunDir, "save_raw", save_raw):
        run(rd, Script(lambda cid, n, rep: perfect(cid)))
    drop_lock(rd)
    return rd


if want("D4"):
    def d4():
        tree = tree_copy("d4-tree")
        out = {}
        a = os.path.join(TMP, "d4-a"); os.makedirs(a)
        json.dump([1, 2, 3], open(os.path.join(a, "manifest.json"), "w"))
        out["settle-manifest-list"] = cli(tree, "settle", "--run-dir", a, "--unit", "x/y/t1", "--attempt", "1", "--decision",
                                          "count_unavailable", "--by", "o", "--reason", "r")
        b = os.path.join(TMP, "d4-b"); os.makedirs(b)
        c_ = cfg([arm()])
        json.dump(manifest_for(c_, [arm()], ONE), open(os.path.join(b, "manifest.json"), "w"))
        open(os.path.join(b, "intents.jsonl"), "w").write(json.dumps({"x": 1}) + "\n")
        out["settle-row-without-keys"] = cli(tree, "settle", "--run-dir", b, "--unit", UID, "--attempt", "1", "--decision",
                                             "count_unavailable", "--by", "o", "--reason", "r")
        d = os.path.join(TMP, "d4-d"); os.makedirs(os.path.join(d, "run.lock"))
        out["unlock-unreadable-lock"] = cli(tree, "unlock", "--run-dir", d, "--by", "o", "--reason", "r")
        bad = {k: v for k, v in out.items() if not (v[0] == 2 and "Traceback" not in v[2] and "REFUSED" in v[2])}
        check("D4-A", "settle and unlock on malformed run state (manifest of the wrong shape, a row without its keys, an unreadable "
              "lock) refuse with a REFUSED line, exit 2, and no traceback", not bad,
              {k: (v[0], v[2][-160:]) for k, v in out.items()})
        g = os.path.join(TMP, "d4-good")
        src = unresolved_for_cli(g)
        ok = cli(tree, "settle", "--run-dir", src, "--unit", UID, "--attempt", "1", "--decision", "count_unavailable", "--by", "o",
                 "--reason", "r")
        check("CTRL-D4-B", "a valid settlement still exits 0", ok[0] == 0, ok[:2])
    guarded("D4-A", "malformed state", d4)


# =============================================================== V5 documentation matches the tool
if want("V5"):
    def v5():
        import re
        p = subprocess.run([sys.executable, "-B", os.path.join(TREE, "mm_run.py"), "--help"], capture_output=True, text=True, timeout=60)
        m = re.search(r"\{([a-z,\-]+)\}", p.stdout)
        subs = m.group(1).split(",") if m else []
        doc = open(os.path.join(TREE, "mm_run.py"), encoding="utf-8").read().split('"""')[1]
        missing = [s for s in subs if ("mm_run.py " + s) not in doc and ("mm_run.py " + s + " ") not in doc]
        check("V5-A", "the mm_run.py docstring shows a usage line for every subcommand and names r7.2 (not 'candidate r6')",
              bool(subs) and not missing and "r7.2" in doc and "candidate r6" not in doc, {"subcommands": subs, "missing": missing})
        md = open(os.path.join(TREE, "docs", "MULTIMODEL-RUNNER.md"), encoding="utf-8").read()
        need = ["settle", "unlock", "replay_identity", "malformed_2xx", "ambiguous_resend", "IMPORT_REFUSED"]
        check("V5-B", "docs/MULTIMODEL-RUNNER.md documents settle, unlock, replay identity, malformed 2xx, ambiguous resends and "
              "import refusals", all(n in md for n in need), [n for n in need if n not in md])
    guarded("V5-A", "docs", v5)


# =============================================================== P3 test edition 4: Red round 1 on r7.2-p2 (reviews/RED-ED-r72.md)
def wrong(cid):
    g = GOLDS[cid]
    return json.dumps({"month": g["month"], "days": {d: {"status": "UNAVAILABLE", "note": c["note"]} for d, c in g["days"].items()},
                       "global_notes": list(g.get("global_notes", []))})


class FakeResp:
    def __init__(self, status, read):
        self.status, self._read = status, read

    def read(self):
        return self._read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_open(resp, counter):
    def opener(req, timeout=None):
        counter.append(req.full_url)
        return resp
    return opener


if want("P3"):
    def p3_raw_identity():     # R-ED-1
        src = os.path.join(TMP, "p3-a-src")
        s = run(src, Script(lambda cid, n, rep: wrong(cid) if n == 1 else perfect(cid)), trials=2)
        rows = {r["unit_id"]: r for r in s["results"]}
        bad = [u for u, r in rows.items() if (r.get("score") or {}).get("day_accuracy", 1) < 1][0]
        good = [u for u in rows if u != bad][0]
        att = read_jsonl(src, "attempts.jsonl")
        braw = [a for a in att if a["unit_id"] == bad][0]["raw_file"]
        graw = [a for a in att if a["unit_id"] == good][0]["raw_file"]
        for a in att:
            if a["unit_id"] == bad:
                a["raw_file"] = graw
        open(os.path.join(src, "attempts.jsonl"), "w", encoding="utf-8").write("".join(json.dumps(a, sort_keys=True) + "\n" for a in att))
        os.remove(os.path.join(src, braw))
        r = run(os.path.join(TMP, "p3-a-new"), replay_transport(src), trials=2)
        out = {x["unit_id"]: (x["outcome"], x.get("unavailable_reason")) for x in r["results"]}
        check("P3-A", "a stored row that names another trial's raw file is not served (R-ED-1): that unit ends unavailable, "
              "replay_identity; the other trial replays", r["error"] is None and out.get(bad) == ("unavailable", "replay_identity")
              and out.get(good, (None,))[0] == "scored", {"error": r["error"], "out": out})
    guarded("P3-A", "raw identity", p3_raw_identity)

    def p3_raw_identity_parts():     # R-ED-1: each of the two checks on its own
        def source(name):
            src = os.path.join(TMP, name)
            s = run(src, Script(lambda cid, n, rep: wrong(cid) if n == 1 else perfect(cid)), trials=2)
            rows = {r["unit_id"]: r for r in s["results"]}
            bad = [u for u, r in rows.items() if (r.get("score") or {}).get("day_accuracy", 1) < 1][0]
            good = [u for u in rows if u != bad][0]
            att = read_jsonl(src, "attempts.jsonl")
            return src, bad, good, att, {a["unit_id"]: a["raw_file"] for a in att}
        # (a) raws without embedded ids (the legacy-import layout): only the canonical-name check can refuse the repointed row
        src, bad, good, att, rf = source("p3-a2-src")
        for f in rf.values():
            d = json.load(open(os.path.join(src, f), encoding="utf-8")); d.pop("unit_id", None); d.pop("attempt", None)
            json.dump(d, open(os.path.join(src, f), "w", encoding="utf-8"))
        for a in att:
            if a["unit_id"] == bad:
                a["raw_file"] = rf[good]
        open(os.path.join(src, "attempts.jsonl"), "w", encoding="utf-8").write("".join(json.dumps(a, sort_keys=True) + "\n" for a in att))
        os.remove(os.path.join(src, rf[bad]))
        r = run(os.path.join(TMP, "p3-a2-new"), replay_transport(src), trials=2)
        out = {x["unit_id"]: (x["outcome"], x.get("unavailable_reason")) for x in r["results"]}
        check("P3-A2", "a row naming another trial's raw file is refused by name even when the raw records no ids (legacy layout)",
              r["error"] is None and out.get(bad) == ("unavailable", "replay_identity"), {"error": r["error"], "out": out})
        # (b) the canonical file of one trial holds another trial's record: only the embedded-id check can refuse it
        src, bad, good, att, rf = source("p3-a3-src")
        shutil.copy(os.path.join(src, rf[good]), os.path.join(src, rf[bad]))
        r = run(os.path.join(TMP, "p3-a3-new"), replay_transport(src), trials=2)
        out = {x["unit_id"]: (x["outcome"], x.get("unavailable_reason")) for x in r["results"]}
        check("P3-A3", "a trial's canonical raw file that records another trial's unit is refused by its embedded ids",
              r["error"] is None and out.get(bad) == ("unavailable", "replay_identity"), {"error": r["error"], "out": out})
    guarded("P3-A2", "raw identity parts", p3_raw_identity_parts)

    def p3_torn_and_foreign():    # R-ED-2, R-ED-8
        raw = legacy_raw("p3-b-raw", THREE)
        rd = os.path.join(TMP, "p3-b-run")
        import_legacy(raw, None, rd, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        open(os.path.join(rd, "results.jsonl"), "a", encoding="utf-8").write('{"unit_id": "hist/x", "outc')
        err = None
        try:
            import_legacy(raw, None, rd, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        except RN.RunRefused as ex:
            err = str(ex)
        st = json.load(open(os.path.join(rd, "run_status.json"), encoding="utf-8")) if os.path.exists(os.path.join(rd, "run_status.json")) else None
        check("P3-B", "an import refused on a torn ledger still leaves run_status.json (IMPORT_REFUSED, results_rows_now null), "
              "the old status kept and a refusal row (R-ED-2)", err is not None and st is not None and st.get("run_status") == "IMPORT_REFUSED"
              and st.get("results_rows_now") is None and bool(st.get("previous_status_file"))
              and len(read_jsonl(rd, "import-refusals.jsonl")) == 1, {"err": (err or "")[:80], "status": st and st.get("run_status")})
        mm = os.path.join(TMP, "p3-c-mm")
        run(mm, Script(lambda cid, n, rep: perfect(cid)))
        before = snapshot(mm)
        err2 = None
        try:
            import_legacy(raw, None, mm, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        except RN.RunRefused as ex:
            err2 = str(ex)
        check("P3-C", "an import aimed at a directory that belongs to another manifest is refused and writes nothing there (R-ED-8)",
              err2 is not None and snapshot(mm) == before, {"err": (err2 or "")[:80], "changed": sorted(set(snapshot(mm)) ^ set(before))})
    guarded("P3-B", "torn ledger and foreign directory", p3_torn_and_foreign)

    def p3_whole_state():      # R-ED-11
        raw = legacy_raw("p3-d-raw", THREE, with_retry=("sample_03_lowcontrast",))
        rd = os.path.join(TMP, "p3-d-run")
        import_legacy(raw, None, rd, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        att = read_jsonl(rd, "attempts.jsonl")
        keep = [a for a in att if a["unit_id"] == "hist/sample_03_lowcontrast/t1" and a["attempt"] == 2]
        open(os.path.join(rd, "attempts.jsonl"), "w", encoding="utf-8").write("".join(json.dumps(a, sort_keys=True) + "\n" for a in keep))
        open(os.path.join(rd, "results.jsonl"), "w", encoding="utf-8").write("")
        for f in os.listdir(os.path.join(rd, "raw")):
            if "sample_03" not in f:
                os.remove(os.path.join(rd, "raw", f))
        before = {k: v for k, v in snapshot(rd).items() if not k.startswith(("run_status", "import-refusals"))}
        err = None
        try:
            import_legacy(raw, None, rd, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        except RN.RunRefused as ex:
            err = str(ex)
        after = {k: v for k, v in snapshot(rd).items() if not k.startswith(("run_status", "import-refusals"))}
        check("P3-D", "one case's invalid prior state refuses the whole import before ANY case is written (R-ED-11)",
              err is not None and "sample_03" in err and after == before, {"err": (err or "")[:80], "changed": sorted(set(after) ^ set(before))})
        rd2 = os.path.join(TMP, "p3-d2-run")
        raw2 = legacy_raw("p3-d2-raw", THREE, with_retry=("sample_02_rotated",))
        import_legacy(raw2, None, rd2, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        att = read_jsonl(rd2, "attempts.jsonl")
        dup = dict([a for a in att if a["unit_id"] == "hist/sample_02_rotated/t1" and a["attempt"] == 1][0], kind="content_repair")
        att2 = [a for a in att if a["unit_id"] != "hist/sample_02_rotated/t1"] + [dup] + \
            [a for a in att if a["unit_id"] == "hist/sample_02_rotated/t1"]
        open(os.path.join(rd2, "attempts.jsonl"), "w", encoding="utf-8").write("".join(json.dumps(a, sort_keys=True) + "\n" for a in att2))
        res = [r for r in read_jsonl(rd2, "results.jsonl") if r["unit_id"] != "hist/sample_02_rotated/t1"]
        open(os.path.join(rd2, "results.jsonl"), "w", encoding="utf-8").write("".join(json.dumps(r, sort_keys=True) + "\n" for r in res))
        err = None
        try:
            import_legacy(raw2, None, rd2, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        except RN.RunRefused as ex:
            err = str(ex)
        check("P3-D2", "a contradicting duplicate attempt row is refused, not silently replaced by the last row (R-ED-11)",
              err is not None and "duplicate" in err, (err or "")[:120])
    guarded("P3-D", "whole prior state", p3_whole_state)

    def strip_policy(m):
        o = {k: v for k, v in m.items() if k not in ("manifest_hash", "runner_policy")}
        o["manifest_hash"] = C.canonical_hash(o)
        return o

    def p3_edition():          # R-ED-3, R2-ED-1 (test edition 5: the policy is in the hashed manifest)
        def boom(_):
            raise Crash("stop during the backoff")
        flaky = lambda cid, n, rep: TransportError("HTTP 503", status=503, transient=True) if n == 1 else perfect(cid)
        m = manifest_for(cfg([arm()]), [arm()], ONE)
        old = strip_policy(m)                       # the manifest an r7.1-or-earlier runner builds: no runner_policy key
        rd = os.path.join(TMP, "p3-e-run")
        r1 = run(rd, Script(flaky), sleep=boom, manifest=old)
        drop_lock(rd)
        st = Script(lambda cid, n, rep: perfect(cid))
        r2 = run(rd, st, manifest=m)
        check("P3-E", "a run started under an earlier runner policy is not resumed: refused naming the policy, nothing sent (R-ED-3)",
              bool(m.get("runner_policy")) and "Crash" in (r1["error"] or "") and r2["error"] is not None
              and "runner policy" in r2["error"] and st.sends == [], {"error": (r2["error"] or "")[:140], "sends": st.sends})
        rd3 = os.path.join(TMP, "p3-e3-run")
        run(rd3, Script(flaky), sleep=boom, manifest=m)
        drop_lock(rd3)
        st3 = Script(lambda cid, n, rep: perfect(cid))
        r3 = run(rd3, st3, manifest=old)
        check("P3-E3", "the binding holds in the other direction (R2-ED-1): the manifest an earlier runner builds has another hash, so "
              "a run started under this policy is refused to it, nothing sent", old["manifest_hash"] != m["manifest_hash"]
              and r3["error"] is not None and st3.sends == [], {"error": (r3["error"] or "")[:140], "sends": st3.sends})
        rd2 = os.path.join(TMP, "p3-e2-run")
        run(rd2, Script(flaky), sleep=boom, manifest=m)
        drop_lock(rd2)
        r4 = run(rd2, Script(lambda cid, n, rep: perfect(cid)), manifest=m)
        check("P3-E2", "the same crash resumed under the same policy continues, and run_status records the runner edition",
              r4["error"] is None and [x["outcome"] for x in r4["results"]] == ["scored"]
              and (r4["status"] or {}).get("runner_edition") == RN.RUNNER_EDITION, {"error": r4["error"], "status": (r4["status"] or {}).get("runner_edition")})
        tree = tree_copy("p3-e4-tree")
        conf = write_cli_config(tree)
        import importlib.util
        spec = importlib.util.spec_from_file_location("mm_run_p3e4", os.path.join(tree, "mm_run.py"))
        mm = importlib.util.module_from_spec(spec)
        oldp = sys.path[:]
        sys.path.insert(0, tree)
        try:
            spec.loader.exec_module(mm)
            cfg_, arms_, cases_, golds_, man = mm._load(conf, os.path.join(tree, "data"))
        finally:
            sys.path[:] = oldp
        src = os.path.join(TMP, "p3-e4-src")
        RN.execute(strip_policy(man), cfg_, arms_, cases_, golds_, src, Script(lambda cid, n, rep: perfect(cid)), e, prompt=e.TASK_PROMPT,
                   retry_suffix=e.RETRY_SUFFIX, environ={"K": "k" * 20}, sleep=lambda s: None)
        out = cli(tree, "replay", "--config", conf, "--data", "data", "--from", src, "--run-dir", os.path.join(TMP, "p3-e4-new"))
        check("CTRL-P3-E4", "replay (a new directory) of a source started by an earlier runner with an otherwise identical manifest "
              "still runs, without --allow-changed-scorer", out[0] == 0, out)
    guarded("P3-E", "runner edition", p3_edition)

    def p3_ambiguous_resume():     # R-ED-4 (+ M24)
        amb = TransportError("network error after the request was sent", transient=True, ambiguous=True)
        rd = os.path.join(TMP, "p3-f-run")
        real = RN.RunDir.append
        def append(self, name, rec):
            if name == "results.jsonl":
                raise Crash("crash before the outcome row")
            return real(self, name, rec)
        with patch.object(RN.RunDir, "append", append):
            run(rd, Script(lambda cid, n, rep: amb if n == 1 else perfect(cid)))
        drop_lock(rd)
        st = Script(lambda cid, n, rep: perfect(cid))
        r = run(rd, st)
        check("P3-F", "an ambiguous attempt whose outcome row was lost is not resent on resume by default (R-ED-4): nothing sent, "
              "unavailable", r["error"] is None and st.sends == [] and [x["outcome"] for x in r["results"]] == ["unavailable"],
              {"error": r["error"], "sends": st.sends, "rows": [x["outcome"] for x in r["results"]]})
        rd2 = os.path.join(TMP, "p3-f2-run")
        def boom(_):
            raise Crash("stop during the backoff")
        run(rd2, Script(lambda cid, n, rep: amb if n == 1 else perfect(cid)), sleep=boom, proto={"ambiguous_resend": True})
        drop_lock(rd2)
        st2 = Script(lambda cid, n, rep: perfect(cid))
        r2 = run(rd2, st2, proto={"ambiguous_resend": True})
        a2 = [a for a in r2["attempts"] if a["attempt"] == 2]
        check("CTRL-P3-F", "with protocol.ambiguous_resend the resumed unit sends once, and that attempt is marked ambiguous_resend",
              r2["error"] is None and len(st2.sends) == 1 and bool(a2) and a2[0].get("ambiguous_resend") is True,
              {"error": r2["error"], "sends": st2.sends, "attempt2": a2 and {k: a2[0].get(k) for k in ("kind", "ambiguous_resend")}})
    guarded("P3-F", "ambiguous resume", p3_ambiguous_resume)

    def p3_unknown_identity():     # R-ED-5
        d = os.path.join(TMP, "p3-g")
        subprocess.run([sys.executable, "-c", LOCK_WRITER % (TREE, d)], check=True, timeout=60)
        before = open(os.path.join(d, "run.lock"), "rb").read()
        got = None
        with patch.object(RN, "proc_identity", return_value=(None, None)):
            try:
                RN.RunDir(d).release_stale_lock("owner-test", "test")
                got = "released"
            except RN.RunRefused as ex:
                got = "refused: " + str(ex)[:80]
        check("P3-G", "unlock refuses when the process identity cannot be checked (Windows ACCESS_DENIED); the lock is kept (R-ED-5)",
              got.startswith("refused") and open(os.path.join(d, "run.lock"), "rb").read() == before, got)
    guarded("P3-G", "unknown identity", p3_unknown_identity)

    def p3_reset_after_2xx_and_redaction():     # R-ED-6, R-ED-7
        def reset():
            raise ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")
        posts = []
        a = local_arm("http://127.0.0.1:9/v1/chat/completions")
        err = None
        with patch.object(T.OPENER, "open", side_effect=fake_open(FakeResp(200, reset), posts)):
            try:
                HttpTransport().send(a, a["endpoint"], {}, {"x": 1}, 1)
            except TransportError as ex:
                err = ex
        check("P3-H", "a reset while reading a 200 body is malformed (status 200), never ambiguous (R-ED-6)",
              err is not None and err.malformed and not err.ambiguous and err.status == 200,
              err and {"malformed": err.malformed, "ambiguous": err.ambiguous, "status": err.status})
        posts2 = []
        rd = os.path.join(TMP, "p3-h-run")
        with patch.object(T.OPENER, "open", side_effect=fake_open(FakeResp(200, reset), posts2)):
            r = run(rd, HttpTransport(), arms=[a], block_net=False, proto={"ambiguous_resend": True})
        check("CTRL-P3-H", "even with protocol.ambiguous_resend, a 2xx whose body reset is sent once (bad_provider_shape)",
              r["error"] is None and len(posts2) == 1 and [(x["attempt"], x["result"]) for x in r["attempts"]] == [(1, "bad_provider_shape")],
              {"error": r["error"], "posts": len(posts2), "attempts": [(x["attempt"], x["result"]) for x in r["attempts"]]})
        secret = "sk-test-SECRET-0123456789"
        body = ("echo: Authorization: Bearer " + secret + " ").encode() + b"x" * 70000
        err = None
        with patch.object(T.OPENER, "open", side_effect=fake_open(FakeResp(200, lambda: body), [])):
            try:
                HttpTransport().send(a, a["endpoint"], {"Authorization": "Bearer " + secret}, {"x": 1}, 1)
            except TransportError as ex:
                err = ex
        check("P3-I", "a malformed body is redacted and capped at RAW_BODY_LIMIT characters, marked truncated (R-ED-7)",
              err is not None and err.malformed and secret not in (err.body or "") and len(err.body or "") == T.RAW_BODY_LIMIT
              and err.body_truncated, err and {"secret_in_body": secret in (err.body or ""), "len": len(err.body or ""),
                                               "truncated": err.body_truncated})
    guarded("P3-H", "reset after 2xx; redaction", p3_reset_after_2xx_and_redaction)

    def p3_cli_and_unlock():     # R-ED-10
        tree = tree_copy("p3-j-tree")
        out = {}
        for label, cs in (("empty-case", {"cases": [[]]}), ("huge-trials", None)):
            d = os.path.join(TMP, "p3-j-" + label); os.makedirs(d)
            c_ = cfg([arm()])
            m = manifest_for(c_, [arm()], ONE)
            if cs:
                m["case_set"] = dict(m["case_set"], **cs)
            else:
                m["protocol"] = dict(m["protocol"], trials=1e400)
            open(os.path.join(d, "manifest.json"), "w", encoding="utf-8").write(json.dumps(m).replace("Infinity", "1e400"))
            out[label] = cli(tree, "settle", "--run-dir", d, "--unit", UID, "--attempt", "1", "--decision", "count_unavailable",
                             "--by", "o", "--reason", "r")
        bad = {k: v for k, v in out.items() if not (v[0] == 2 and "Traceback" not in v[2] and "REFUSED" in v[2])}
        check("P3-J", "settle refuses a manifest whose case list or trial count is malformed with one REFUSED line, exit 2, no "
              "traceback (R-ED-10)", not bad, {k: (v[0], v[2][-140:]) for k, v in out.items()})
        d = os.path.join(TMP, "p3-j-twice")
        moved = []
        with patch.object(RN, "now_utc", return_value="2026-11-02T00:00:00Z"):     # the same second, deterministically
            for i in range(2):
                subprocess.run([sys.executable, "-c", LOCK_WRITER % (TREE, d)], check=True, timeout=60)
                moved.append(os.path.basename(RN.RunDir(d).release_stale_lock("owner-test", "test %d" % i)))
        kept = sorted(f for f in os.listdir(d) if f.startswith("run.lock.stale-"))
        check("P3-K", "two stale-lock releases in the same second keep both moved locks (R-ED-10)",
              len(set(moved)) == 2 and len(kept) == 2, {"moved": moved, "kept": kept})
    guarded("P3-J", "settle/unlock hardening", p3_cli_and_unlock)

    def p3_unlock_handler():
        import importlib.util, argparse
        d = os.path.join(TMP, "p3-l")
        os.makedirs(d, exist_ok=True)
        spec = importlib.util.spec_from_file_location("mm_run_p3", os.path.join(TREE, "mm_run.py"))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        buf = io.StringIO()
        with patch.object(m.RN.RunDir, "release_stale_lock", side_effect=KeyError("pid")), contextlib.redirect_stderr(buf):
            code = m.cmd_unlock(argparse.Namespace(run_dir=d, by="o", reason="r"))
        check("P3-L", "unlock reports malformed run state from inside release_stale_lock as one REFUSED line, exit 2 (M18)",
              code == 2 and "REFUSED" in buf.getvalue(), {"code": code, "stderr": buf.getvalue()[-120:]})
    guarded("P3-L", "unlock handler", p3_unlock_handler)

    def p3_surviving_mutants():     # R-ED-12
        tree = tree_copy("p3-m-tree")
        conf = write_cli_config(tree)
        src = cli_source(tree, conf, "p3-m-src")
        c2 = json.load(open(conf, encoding="utf-8"))
        c2["arms"][0]["limits"] = dict(c2["arms"][0]["limits"], max_attempts_per_trial=1)
        conf2 = os.path.join(tree, "configs", "r72-test-arms.json")
        json.dump(c2, open(conf2, "w", encoding="utf-8"), indent=1)
        with open(os.path.join(tree, "run_eval.py"), "a", encoding="utf-8") as f:
            f.write("\n# p3: a scorer edit\n")
        other = cli(tree, "replay", "--config", conf2, "--data", "data", "--from", src, "--run-dir", os.path.join(TMP, "p3-m-new"),
                    "--allow-changed-scorer")
        check("P3-M", "--allow-changed-scorer refuses a source whose arms differ (limits are not in the request hash) (M19)",
              other[0] == 2, other)
        s2 = os.path.join(TMP, "p3-n-src")
        run(s2, Script(lambda cid, n, rep: perfect(cid)))
        shutil.copy(os.path.join(s2, "raw", os.listdir(os.path.join(s2, "raw"))[0]), os.path.join(s2, "raw", "stray.a9.json"))
        err = None
        try:
            replay_transport(s2)
        except RN.RunRefused as ex:
            err = str(ex)
        check("P3-N", "a replay source with a raw file that no attempt row names is refused at load (M23)",
              err is not None and "raw file" in err, (err or "")[:120])
        s3 = os.path.join(TMP, "p3-o-src")
        run(s3, Script(lambda cid, n, rep: TransportError("network error after the request was sent", transient=True, ambiguous=True)))
        r = run(os.path.join(TMP, "p3-o-new"), replay_transport(s3))
        att = [(a["attempt"], a["result"], bool(a.get("ambiguous"))) for a in r["attempts"]]
        check("P3-O", "a replayed ambiguous error stays ambiguous: one attempt, not resent (M27)",
              r["error"] is None and att == [(1, "transport_error", True)], {"error": r["error"], "attempts": att})
        rep = MR.build_report([(MR.load_run(s2), "a1")], GOLDS, e, [])
        sent = rep["arms"]["a1"]["denominators"].get("historic_conditional.format_validity", "")
        check("P3-P", "the format-validity denominator names refused units as excluded (R-ED-12)", "refused" in sent, sent)
    guarded("P3-M", "surviving mutants", p3_surviving_mutants)

    def p3_round2():     # RED-ED-r72-R2.md: R2-ED-2 and the R2-ED-4 controls
        # N1: the attempt half of the embedded-id check
        src = os.path.join(TMP, "p3-q-src")
        run(src, Script(lambda cid, n, rep: "GARBAGE" if n == 1 else perfect(cid)))
        raws = sorted(os.listdir(os.path.join(src, "raw")))
        a1 = [f for f in raws if f.endswith(".a1.json")][0]
        a2 = [f for f in raws if f.endswith(".a2.json")][0]
        shutil.copy(os.path.join(src, "raw", a1), os.path.join(src, "raw", a2))   # attempt 2's file now records attempt 1
        r = run(os.path.join(TMP, "p3-q-new"), replay_transport(src))
        row = (r["results"] or [{}])[0]
        check("P3-Q", "a raw file whose recorded attempt differs from the bound attempt is not served (R2-ED-4 N1)",
              r["error"] is None and row.get("outcome") == "unavailable" and row.get("unavailable_reason") == "replay_identity",
              {"error": r["error"], "row": {k: row.get(k) for k in ("outcome", "unavailable_reason")}})
        # N3: duplicate outcome rows in an import
        raw = legacy_raw("p3-r-raw", THREE)
        rd = os.path.join(TMP, "p3-r-run")
        import_legacy(raw, None, rd, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        res = read_jsonl(rd, "results.jsonl")
        open(os.path.join(rd, "results.jsonl"), "a", encoding="utf-8").write(json.dumps(res[0], sort_keys=True) + "\n")
        err = None
        try:
            import_legacy(raw, None, rd, arm_id="hist", model_label="hist", scorer=e, cases=THREE)
        except RN.RunRefused as ex:
            err = str(ex)
        check("P3-R", "duplicate outcome rows refuse an import (R2-ED-4 N3)", err is not None and "duplicate outcome" in err, (err or "")[:120])
    guarded("P3-Q", "round-2 controls", p3_round2)

    def p3_round2_lock():
        # N4: the lock cannot be moved
        d = os.path.join(TMP, "p3-s")
        subprocess.run([sys.executable, "-c", LOCK_WRITER % (TREE, d)], check=True, timeout=60)
        before = open(os.path.join(d, "run.lock"), "rb").read()
        got = None
        with patch.object(RN.os, "rename", side_effect=PermissionError(13, "Access is denied")):
            try:
                RN.RunDir(d).release_stale_lock("owner-test", "test")
                got = "released"
            except RN.RunRefused as ex:
                got = "refused: " + str(ex)[:80]
        check("P3-S", "a lock that cannot be moved is refused by name and kept as found (R2-ED-4 N4)",
              got.startswith("refused") and "could not be moved" in got and open(os.path.join(d, "run.lock"), "rb").read() == before, got)
        # R2-ED-2: the lock changes between the identity check and the move
        d2 = os.path.join(TMP, "p3-t")
        subprocess.run([sys.executable, "-c", LOCK_WRITER % (TREE, d2)], check=True, timeout=60)
        live = json.dumps({"pid": os.getpid(), "pid_start": "x", "since": "now", "host": RN.host_identity()})
        real = RN.proc_identity
        def racing(pid):
            out = real(pid)
            open(os.path.join(d2, "run.lock"), "w", encoding="utf-8").write(live)    # a new run takes the lock meanwhile
            return out
        msg = None
        with patch.object(RN, "proc_identity", side_effect=racing):
            try:
                RN.RunDir(d2).release_stale_lock("owner-test", "test")
                msg = "released"
            except RN.RunRefused as ex:
                msg = "refused: " + str(ex)[:120]
        left = sorted(os.listdir(d2))
        check("P3-T", "a lock that changed between the identity check and the move is put back and the release refused (R2-ED-2)",
              msg.startswith("refused") and open(os.path.join(d2, "run.lock"), encoding="utf-8").read() == live
              and not [f for f in left if f.startswith("run.lock.stale-")], {"msg": msg, "files": left})
    guarded("P3-S", "round-2 lock controls", p3_round2_lock)


n_pass = sum(1 for r in RES if r["result"] == "PASS")
n_fail = len(RES) - n_pass
print(f"\n{n_pass} PASS · {n_fail} FAIL  (tree: {TREE})")
if OUT:
    json.dump({"tree": TREE, "only": sorted(ONLY) if ONLY else None, "results": RES}, open(OUT, "w", encoding="utf-8"), indent=1)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if n_fail == 0 else 1)
