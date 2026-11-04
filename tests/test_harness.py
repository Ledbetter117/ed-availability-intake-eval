#!/usr/bin/env python3
"""Harness regression tests. Run from anywhere:  python3 tests/test_harness.py

No network, no API key, no model call: provider calls are replaced by test doubles. Malformed inputs
below are CONSTRUCTED. Every check can fail; section E proves the comparators fire.

Section A re-scores the stored model responses in results*/raw/. Those files are gitignored and are
not in the public repository, so a public checkout reports section A as UNVERIFIED (not PASS).
Check C8 needs git and a git checkout; elsewhere it reports UNVERIFIED.
Section G (r6) covers the multi-model layer (mmeval/, mm_run.py, configs/). It never builds a network
transport and patches urllib.request.urlopen to fail; G38 needs results*/raw/ and G41 a git checkout.
Section H (r7) runs tests/test_resume_reporting.py: resume safety (REC-05/06/07) and reporting integrity
(REC-11, ACC-08, REC-13), offline, with simulated stops at each write boundary.
Section F checks that the run wrote nothing into the checkout. Scratch files live under one temporary
directory that is removed at exit.
Exit status: 1 if any check FAILS; 2 if any check is UNVERIFIED and --allow-unverified was not given;
0 otherwise.
"""
import atexit, copy, csv, io, json, math, os, shutil, subprocess, sys, tempfile, contextlib, urllib.error
from unittest.mock import patch

ALLOW_UNVERIFIED = "--allow-unverified" in sys.argv[1:]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tree_snapshot(top):
    """(path, size, mtime_ns) of every file under top; .git is excluded (git's own metadata)."""
    snap = set()
    for d, dirs, files in os.walk(top):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            p = os.path.join(d, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            snap.add((os.path.relpath(p, top).replace(os.sep, "/"), st.st_size, st.st_mtime_ns))
    return snap


SNAP0 = tree_snapshot(ROOT)                            # section F compares the checkout with this
TMP_ROOT = tempfile.mkdtemp(prefix="ed-eval-tests-")   # all scratch lives here; removed at exit
atexit.register(shutil.rmtree, TMP_ROOT, True)
sys.dont_write_bytecode = True                         # importing run_eval writes no __pycache__ here
sys.path.insert(0, ROOT)
import run_eval as e  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(("PASS" if ok else "FAIL", name, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def unverified(name, why):
    results.append(("UNVERIFIED", name, why))
    print(f"UNVERIFIED {name}  [{why}]")


def attempt(fn):
    try:
        return {"returned": fn()}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def load(path):
    return json.load(open(path, encoding="utf-8"))


GOLD = load(os.path.join(ROOT, "data", "sample_27_lowcontrast.gold.json"))


def perfect(gold):
    return {"month": gold["month"],
            "days": {d: {"status": c["status"], "note": c["note"]} for d, c in gold["days"].items()},
            "global_notes": list(gold.get("global_notes", []))}


# ======================================================================= A · frozen outputs
print("== A · re-scoring the stored v1 responses ==")
V1_INT = ["gold_unavailable_days", "hallucinated_notes", "predicted_notes", "gold_notes", "captured_notes"]
V1_FLOAT = ["day_accuracy", "critical_error_rate", "hallucination_rate", "note_fidelity"]
ledger = {(r["model"], r["case"]): r for r in csv.DictReader(open(os.path.join(ROOT, "calendar_level.csv")))}
typed = load(os.path.join(ROOT, "typed_errors.json"))
for folder in ("results", "results_haiku"):
    raw_dir = os.path.join(ROOT, folder, "raw")
    if not os.path.isdir(raw_dir):
        unverified(f"A:{folder}", "results*/raw/ is gitignored and absent from this checkout")
        continue
    published = {r["case"]: r for r in csv.DictReader(open(os.path.join(ROOT, folder, "per_case.csv"), newline=""))}
    metrics = load(os.path.join(ROOT, folder, "metrics.json"))
    rows, field_mismatch, typed_mismatch = [], [], []
    for case in sorted(published):
        gold = load(os.path.join(ROOT, "data", case + ".gold.json"))
        text = open(os.path.join(raw_dir, case + ".txt"), encoding="utf-8").read()
        s = e.evaluate_response(e.parse_json(text), gold)
        s["case"], s["slice"] = case, case.split("_")[-1]
        rows.append(s)
        p = published[case]
        if str(s["format_validity"]) != p["format_validity"]:
            field_mismatch.append((case, "format_validity"))
        for k in V1_INT:
            if s[k] != int(p[k]):
                field_mismatch.append((case, k))
        for k in V1_FLOAT:
            want = float(p[k]) if p[k] else None
            if s[k] != want:
                field_mismatch.append((case, k))
        if s["critical_flips"] != json.loads(p["critical_flips"]):
            field_mismatch.append((case, "critical_flips"))
        led = ledger[(metrics["model"], case)]
        if (s["displaced_notes"], s["fabricated_notes"]) != (int(led["note_displaced"]), int(led["note_fabricated"])):
            typed_mismatch.append(case)
    check(f"A1 {folder}: every v1 per-case value reproduced on {len(rows)} stored responses", not field_mismatch,
          str(field_mismatch[:4]))
    check(f"A2 {folder}: every stored response is still schema-valid under the exact schema",
          all(r["format_validity"] for r in rows), str([r["case"] for r in rows if not r["format_validity"]][:4]))
    agg = e.aggregate(rows)
    bad = [k for k in metrics["overall"] if not math.isclose(agg[k], metrics["overall"][k], rel_tol=0, abs_tol=1e-12)]
    exact = [k for k in metrics["overall"] if agg[k] != metrics["overall"][k]]
    check(f"A3 {folder}: re-scored aggregate equals published metrics.json overall (abs tol 1e-12)", not bad,
          f"bad={bad}; not bit-identical={exact}")
    sl_bad = [(s, k) for s in metrics["per_slice"] for k in metrics["per_slice"][s]
              if not math.isclose(e.aggregate(rows, s)[k], metrics["per_slice"][s][k], rel_tol=0, abs_tol=1e-12)]
    check(f"A4 {folder}: re-scored per-slice aggregates equal published (abs tol 1e-12)", not sl_bad, str(sl_bad[:3]))
    check(f"A5 {folder}: typed note split equals calendar_level.csv per calendar", not typed_mismatch, str(typed_mismatch[:4]))
    tot = {k: sum(r[k] for r in rows) for k in ("displaced_notes", "fabricated_notes", "predicted_notes")}
    want = typed[metrics["model"]]["notes"]
    check(f"A6 {folder}: typed totals equal typed_errors.json (displaced {want.get('NOTE_DISPLACED', 0)}, "
          f"fabricated {want.get('NOTE_FABRICATED', 0)})",
          tot["displaced_notes"] == want.get("NOTE_DISPLACED", 0) and tot["fabricated_notes"] == want.get("NOTE_FABRICATED", 0),
          json.dumps(tot))
    check(f"A7 {folder}: displaced + fabricated == mismatched on every case",
          all(r["displaced_notes"] + r["fabricated_notes"] == r["mismatched_notes"] for r in rows))

print("== A8 · the shipped v1 CSVs still re-aggregate exactly ==")
for folder in ("results", "results_haiku"):
    metrics = load(os.path.join(ROOT, folder, "metrics.json"))
    rows = []
    for r in csv.DictReader(open(os.path.join(ROOT, folder, "per_case.csv"), newline="")):
        for k in V1_FLOAT:
            r[k] = float(r[k]) if r[k] else None
        for k in V1_INT:
            r[k] = int(r[k])
        r["critical_flips"] = json.loads(r["critical_flips"])
        rows.append(r)
    check(f"A8 {folder}: aggregate(v1 CSV rows) is bit-identical to metrics.json overall",
          e.aggregate(rows) == metrics["overall"])

# ======================================================================= B · constructed malformed responses
print("== B · constructed malformed responses (CONSTRUCTED) ==")
good = perfect(GOLD)
day0 = sorted(good["days"])[0]
missing = copy.deepcopy(good); missing["days"].pop(day0)
extra = copy.deepcopy(good); extra["confidence"] = 0.9
bad_status = copy.deepcopy(good); bad_status["days"][day0]["status"] = []
bad_note = copy.deepcopy(good); bad_note["days"][day0]["note"] = None
no_globals = copy.deepcopy(good); del no_globals["global_notes"]
CASES = {
    "days null": dict(good, days=None), "days list": dict(good, days=["x"]),
    "global_notes string": dict(good, global_notes="None"), "global_notes null": dict(good, global_notes=None),
    "one day missing": missing, "extra top-level field": extra, "status is a list": bad_status,
    "note is null": bad_note, "global_notes absent": no_globals,
    "unparseable": e.parse_json("I could not read this calendar."),
}
MODEL_FIELDS = ("day_accuracy", "critical_error_rate", "critical_flips", "note_mismatch_rate", "mismatched_notes",
                "displaced_notes", "fabricated_notes", "predicted_notes", "note_fidelity", "captured_notes")
for name, value in CASES.items():
    r = attempt(lambda v=value: e.evaluate_response(v, GOLD))
    s = r.get("returned", {})
    check(f"B1 explicit invalid result, no crash, no metric: {name}",
          "error" not in r and s.get("format_validity") is False and s.get("scored") is False
          and all(s.get(k) is None for k in MODEL_FIELDS) and bool(s.get("invalid_reason")),
          r.get("error") or s.get("invalid_reason"))
raw = json.dumps(good)
dup = raw.replace(f'"month": "{GOLD["month"]}"', f'"month": "1999-01", "month": "{GOLD["month"]}"', 1)
check("B2 parser rejects a field given twice with different values", e.parse_json(dup) is None)
check("B3 parser rejects NaN", e.parse_json(raw[:-1] + ', "x": NaN}') is None)
check("B4 parser survives 10,000-deep nesting", "error" not in attempt(lambda: e.parse_json("[" * 10000 + "0" + "]" * 10000)))
check("B5 parser still accepts fenced and prose-wrapped JSON",
      e.parse_json("```json\n" + raw + "\n```") == good and e.parse_json("Result: " + raw) == good)
ng = {"month": "2026-07", "days": {"2026-07-01": {"status": "AM", "note": "no call"},
                                   "2026-07-02": {"status": "PM", "note": ""}}, "global_notes": ["Days only"]}
p = perfect(ng); p["days"]["2026-07-02"]["note"] = "made up restriction"
base_rate = e.score_case(p, ng)["note_mismatch_rate"]
p["global_notes"] = ["Days only"] * 10000
check("B6 repeating a correct global note does not dilute the mismatch rate",
      e.score_case(p, ng)["note_mismatch_rate"] == base_rate, f"{base_rate}")
p = perfect(ng); p["days"]["2026-07-01"]["note"] = ""; p["days"]["2026-07-02"]["note"] = "no call"
moved = e.score_case(p, ng)
p["days"]["2026-07-02"]["note"] = "invented restriction"
invented = e.score_case(p, ng)
check("B7 typed split: a moved note is DISPLACED, an invented one FABRICATED",
      (moved["displaced_notes"], moved["fabricated_notes"], invented["displaced_notes"], invented["fabricated_notes"]) == (1, 0, 0, 1))

# ======================================================================= C · the CLI, provider calls replaced
print("== C · CLI with a mocked provider ==")
RAW27 = None
for folder in ("results_haiku",):
    path = os.path.join(ROOT, folder, "raw", "sample_27_lowcontrast.txt")
    RAW27 = open(path, encoding="utf-8").read() if os.path.isfile(path) else json.dumps(perfect(GOLD))


def run_cli(responses, extra=(), model="claude-mock", out=None, cases=("sample_02_rotated", "sample_27_lowcontrast")):
    t = tempfile.mkdtemp(dir=TMP_ROOT)
    d = os.path.join(t, "data"); os.makedirs(d)
    for c in cases:
        for ext in (".png", ".gold.json"):
            shutil.copy(os.path.join(ROOT, "data", c + ext), d)
    out = out or os.path.join(t, "out")
    calls = []
    it = iter(responses)

    def vision(*a, **k):
        calls.append(1)
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return v
    argv = ["run_eval.py", "--model", model, "--data", d, "--out", out] + list(extra)
    err, code = None, None
    with patch.object(sys, "argv", argv), patch.object(e, "call_vision", side_effect=vision), \
            patch.object(e, "get_key", return_value="mock-key"), patch.object(e, "judge_notes", return_value=0), \
            contextlib.redirect_stdout(io.StringIO()):
        try:
            code = e.main()
        except SystemExit as ex:
            err = f"SystemExit({ex.code})"
        except Exception as ex:
            err = f"{type(ex).__name__}: {ex}"
    rd = lambda n: (open(os.path.join(out, n), encoding="utf-8").read() if os.path.isfile(os.path.join(out, n)) else None)
    res = dict(err=err, code=code, calls=len(calls), metrics=json.loads(rd("metrics.json") or "null"),
               status=json.loads(rd("run_status.json") or "null"), summary=rd("summary.md") or "",
               per_case=rd("per_case.csv"), out=out, tmp=t)
    return res


r = run_cli(["not JSON", "still not JSON", RAW27])
check("C1 one unparseable case: run completes, invalid counted, summary says so",
      r["err"] is None and r["code"] == 0 and r["metrics"]["invalid_cases"] == 1 and r["metrics"]["cases"] == 2
      and "Invalid responses (reported, not scored): 1 of 2." in r["summary"], r["err"])
r = run_cli([RuntimeError("simulated outage"), RAW27])
check("C2 provider error: INCOMPLETE, counted apart, format validity covers answered cases only",
      r["err"] is None and r["code"] == 3 and r["metrics"]["run_status"] == "INCOMPLETE"
      and r["metrics"]["provider_error_cases"] == 1 and r["metrics"]["overall"]["format_validity"] == 1.0
      and "provider_error" in (r["per_case"] or ""), json.dumps(r["metrics"] and r["metrics"]["overall"]))
first = run_cli([RAW27, RAW27])
again = run_cli([RuntimeError("down"), RuntimeError("down")], out=first["out"])
prev = os.path.join(first["out"], "_previous")
check("C3 failed rerun: FAILED, no metrics beside new raw, earlier outputs moved aside, not deleted",
      again["code"] == 1 and again["metrics"] is None and again["status"]["run_status"] == "FAILED"
      and os.path.isdir(prev) and any(os.path.isfile(os.path.join(prev, x, "metrics.json")) for x in os.listdir(prev)))
for lim in ("0", "-1"):
    r = run_cli([RAW27, RAW27], ["--limit", lim])
    check(f"C4 --limit {lim} is refused before any call", r["calls"] == 0 and r["err"] is not None, r["err"])
r = run_cli([RAW27, RAW27], model="definitely-not-a-provider")
check("C5 unknown model name refused before any call", r["calls"] == 0 and r["err"] is not None, r["err"])
r = run_cli(["not JSON", "still not JSON", RAW27], ["--judge"])
check("C6 --judge (mocked) with an invalid case completes", r["err"] is None and r["metrics"]["invalid_cases"] == 1, r["err"])
cases5 = ("sample_01_clean", "sample_02_rotated", "sample_03_lowcontrast", "sample_04_handwritten", "sample_05_clean")
r = run_cli([RuntimeError("down")] * 3, cases=cases5)
check("C7 three consecutive provider errors stop the run; the rest are 'not run'",
      r["calls"] == 3 and r["status"]["not_run_cases"] == 2 and r["status"]["run_status"] == "FAILED", json.dumps(r["status"]))

# ======================================================================= D · provider adapters
# ---- C8 · archived raw responses stay gitignored (actual archive layout; review P06-ED F02)
def _git_root_is_this_tree():
    """r7.1: git answers for the repository it finds; a parent repository's rules are not this checkout's."""
    p = subprocess.run(["git", "-C", ROOT, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return p.returncode == 0 and os.path.normcase(os.path.realpath(p.stdout.strip())) == os.path.normcase(os.path.realpath(ROOT))


def check_ignore(rel):
    if not _git_root_is_this_tree():
        return 128   # r7.1: not this tree's own checkout -> unverified, never a pass or a fail
    p = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", "--no-index", rel], capture_output=True)
    return p.returncode   # 0 ignored · 1 not ignored · 128 not a git checkout or error


layout_tmp = tempfile.mkdtemp(dir=TMP_ROOT)
os.makedirs(os.path.join(layout_tmp, "raw"))
open(os.path.join(layout_tmp, "metrics.json"), "w").write("{}")
moved_to = e.archive_previous_run(layout_tmp)          # the real function decides the layout
layout = os.path.relpath(moved_to, layout_tmp).replace(os.sep, "/")   # e.g. _previous/<UTC>
shutil.rmtree(layout_tmp, ignore_errors=True)
if shutil.which("git") is None:
    unverified("C8 archived raw responses stay gitignored", "git not available")
elif check_ignore("results/raw/probe.txt") == 128:
    unverified("C8 archived raw responses stay gitignored", "not a git checkout")
else:
    must_ignore = ["results/raw/probe.txt", f"results/{layout}/raw/sample_01_clean.txt",
                   f"results_haiku/{layout}/raw/sample_01_clean.txt"]
    must_keep = ["results/metrics.json", "results/per_case.csv", "results/summary.md",
                 "results/charts/error_breakdown.png", "results_haiku/metrics.json"]
    got_ignore = {p: check_ignore(p) for p in must_ignore}
    got_keep = {p: check_ignore(p) for p in must_keep}
    check(f"C8a archived raw responses are ignored (layout {layout.split('/')[0]}/<UTC>/raw; "
          "positive control results/raw/)", all(v == 0 for v in got_ignore.values()), json.dumps(got_ignore))
    check("C8b published outputs stay trackable (negative control)",
          all(v == 1 for v in got_keep.values()), json.dumps(got_keep))

# ---- C9 · exit codes are distinct and documented (review P06-ED F08)
codes = {"complete": run_cli([RAW27, RAW27])["code"],
         "incomplete": run_cli([RuntimeError("down"), RAW27])["code"],
         "failed": run_cli([RuntimeError("down"), RuntimeError("down")])["code"],
         "nothing_scored": run_cli(["not JSON", "still not JSON", "not JSON", "still not JSON"])["code"],
         "usage": run_cli([RAW27], ["--limit", "0"])["err"]}
check("C9 exit codes: 0 complete · 3 incomplete · 1 failed · 4 nothing scored · 2 usage",
      codes == {"complete": 0, "incomplete": 3, "failed": 1, "nothing_scored": 4, "usage": "SystemExit(2)"},
      json.dumps(codes))

print("== D · provider adapters (no network) ==")
captured = []
with patch.object(e, "_post", side_effect=lambda u, h, p: captured.append(p) or {"choices": [{"message": {"content": "{}"}}]}):
    e.call_vision("o3", "k" * 20, os.path.join(ROOT, "data", "sample_01_clean.png"), "x")
    e.call_vision("gpt-4o", "k" * 20, os.path.join(ROOT, "data", "sample_01_clean.png"), "x")
check("D1 o-series uses max_completion_tokens; gpt-4o keeps max_tokens",
      "max_completion_tokens" in captured[0] and "max_tokens" not in captured[0] and "max_tokens" in captured[1])
secret = "TEST_SENTINEL_NOT_A_REAL_KEY_123"
err = urllib.error.HTTPError("https://example.invalid", 401, "x", {}, io.BytesIO(("bad key " + secret).encode()))
with patch.object(e.transport.OPENER, "open", side_effect=err):
    out = attempt(lambda: e._post("https://api.openai.com/v1/chat/completions", {"Authorization": "Bearer " + secret}, {}))
check("D2 the supplied key is redacted from HTTP error text", secret not in str(out) and "[REDACTED]" in str(out), str(out)[:80])
# ---- D4 · a truncated answer is a harness outcome, not an invalid answer (review P06-ED F09)
with patch.object(e, "_post", side_effect=lambda u, h, p: {"choices": [{"message": {"content": '{"month": "2026-07"'},
                                                                         "finish_reason": "length"}]}):
    trunc = attempt(lambda: e.call_vision("gpt-4o", "k" * 20, os.path.join(ROOT, "data", "sample_01_clean.png"), "x"))
with patch.object(e, "_post", side_effect=lambda u, h, p: {"content": [{"type": "text", "text": "{"}],
                                                            "stop_reason": "max_tokens"}):
    trunc_a = attempt(lambda: e.call_vision("claude-x", "k" * 20, os.path.join(ROOT, "data", "sample_01_clean.png"), "x"))
check("D4a both adapters raise TruncatedResponse at the token limit",
      "TruncatedResponse" in str(trunc) and "TruncatedResponse" in str(trunc_a), f"{trunc} | {trunc_a}")
r = run_cli([e.TruncatedResponse('{"month": "2026-07"', "finish_reason=length"), RAW27])
saved = os.path.isfile(os.path.join(r["out"], "raw", "sample_02_rotated.truncated.txt"))
check("D4b CLI records a truncated answer as a provider/harness outcome, keeps its text, does not score it",
      r["code"] == 3 and r["metrics"]["provider_error_cases"] == 1 and r["metrics"]["invalid_cases"] == 0
      and "TruncatedResponse" in (r["per_case"] or "") and saved, json.dumps(r["status"]))
check("D5 o-series requests reserve at least 25,000 completion tokens",
      e.openai_token_limit("o3", 4096) == {"max_completion_tokens": 25000}
      and e.openai_token_limit("o4-mini", 16) == {"max_completion_tokens": 25000}
      and e.openai_token_limit("gpt-4o", 4096) == {"max_tokens": 4096})
check("D3 provider inference", (e.provider_for("claude-x"), e.provider_for("gpt-4o"), e.provider_for("o4-mini"),
                                 e.provider_for("omni"), e.provider_for("llama")) == ("anthropic", "openai", "openai", None, None))

# ======================================================================= E · positive controls
print("== E · positive controls: the comparators must fire ==")
rp = perfect(GOLD); rp["days"][day0]["status"] = "AVAILABLE" if GOLD["days"][day0]["status"] != "AVAILABLE" else "PM"
check("E1 a single wrong status is detected", e.score_case(rp, GOLD)["day_accuracy"] < 1)
check("E2 a tolerance comparator flags a perturbed aggregate",
      not math.isclose(0.5 + 1e-9, 0.5, rel_tol=0, abs_tol=1e-12))
check("E3 the B1 predicate rejects a scored row", not (e.evaluate_response(perfect(GOLD), GOLD)["scored"] is False))

# ======================================================================= G · multi-model layer (r6)
# No network: every transport here is DenyTransport, RecordedTransport or ReplayTransport, and
# urllib.request.urlopen is patched to fail loudly so an accidental live call cannot pass. A mock pass
# is not a provider run. All run directories are under TMP_ROOT.
print("== G · multi-model layer: config, transport, runner, replay, report (no network) ==")
import base64, hashlib, urllib.request  # noqa: E402
from mmeval import casesets as CS, config as MC, report as MR, runner as RN  # noqa: E402
from mmeval.adapters import build_request, parse_response  # noqa: E402
from mmeval.replay import ReplayTransport, import_legacy  # noqa: E402
from mmeval.transport import (DenyTransport, HttpTransport, RecordedTransport, TransportDenied,  # noqa: E402
                              TransportError)


def _no_net(*a, **k):
    raise AssertionError("network call attempted inside section G")


G_CASES_ALL = CS.build_case_manifest(os.path.join(ROOT, "data"), "published-40", 7)
G_CASES = [c for c in G_CASES_ALL if c["case_id"] in ("sample_02_rotated", "sample_27_lowcontrast")]
G_GOLDS = {c["case_id"]: load(c["gold_path"]) for c in G_CASES_ALL}


def g_arm(arm_id="a1", provider="anthropic", **over):
    base = {"anthropic": ("cloud", "https://api.anthropic.com/v1/messages", "TEST_KEY_ENV"),
            "openai": ("cloud", "https://api.openai.com/v1/chat/completions", "TEST_KEY_ENV"),
            "ollama_local": ("local", "http://127.0.0.1:11434/api/chat", None),
            "openai_compatible_local": ("local", "http://127.0.0.1:8080/v1/chat/completions", None)}[provider]
    a = {"arm_id": arm_id, "role": "test", "provider": provider, "route": base[0], "endpoint": base[1],
         "model_requested": "test-model", "modalities": ["text", "image"], "image_capability_verified": True,
         "credential_env": base[2], "max_output_tokens": 4096, "sampling": {}, "thinking": None,
         "image_detail": "high" if provider == "openai" else None, "image_preprocessing": "none",
         "allowed_data_classes": ["public_synthetic"], "status": "ready", "dispatch_enabled": True,
         "limits": {"max_calls": 100, "max_attempts_per_trial": 3, "timeout_s": 5}}
    a.update(over)
    return a


def g_cfg(arms, trials=1, **over):
    c = {"case_set": {"id": "published-40", "data_class": "public_synthetic"},
         "protocol": {"protocol_id": "test", "trials": trials, "order_seed": "t", "content_repair_retries": 1,
                      "backoff_s": [0]},
         "dispatch": {"enabled": True}, "run_caps": {"max_calls_total": 1000}, "arms": arms}
    c.update(over)
    return c


def g_manifest(cfg, arms, cases=None):
    return RN.build_manifest(cfg, arms, cases or G_CASES, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX,
                             scorer_sha256="test", renderer_sha256="test", data_class="public_synthetic")


def anth(text, stop="end_turn"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop, "model": "test-model-served",
            "usage": {"input_tokens": 1500, "output_tokens": 900}}


def g_run(script, arms=None, trials=1, cases=None, run_dir=None, cfg_over=None):
    arms = arms or [g_arm()]
    cfg = g_cfg(arms, trials, **(cfg_over or {}))
    m = g_manifest(cfg, arms, cases)
    rd = run_dir or tempfile.mkdtemp(dir=TMP_ROOT)
    tr = script if hasattr(script, "send") else RecordedTransport(script)
    with patch.object(urllib.request, "urlopen", side_effect=_no_net), patch.object(urllib.request.OpenerDirector, "open", side_effect=_no_net):
        st = RN.execute(m, cfg, arms, cases or G_CASES, G_GOLDS, rd, tr, e, prompt=e.TASK_PROMPT,
                        retry_suffix=e.RETRY_SUFFIX, environ={"TEST_KEY_ENV": "k" * 20}, sleep=lambda s: None)
    return {"status": st, "dir": rd, "results": RN.RunDir(rd).results(), "attempts": RN.RunDir(rd).attempts(),
            "transport": tr, "manifest": m, "cfg": cfg, "arms": arms}


def g_refuses(fn, needle=""):
    out = attempt(fn)
    return "error" in out and ("ConfigError" in out["error"] or "RunRefused" in out["error"]) and needle in out["error"]


G_PERFECT = {c: json.dumps(perfect(G_GOLDS[c])) for c in G_GOLDS}
_B64 = {}
for _c in G_CASES_ALL:
    _B64[hashlib.sha256(base64.b64encode(open(_c["png_path"], "rb").read())).hexdigest()] = _c["case_id"]


class CaseAware(RecordedTransport):
    """Offline double that answers by (arm, case): it finds the case from the image in the request, so
    a test does not depend on the run's seeded unit order."""

    def __init__(self, answer):
        super().__init__([])
        self.answer = answer

    def send(self, arm, url, headers, payload, timeout_s):
        case = next((cid for h, cid in _B64.items() if h in _hashes_in(payload)), None)
        self.script = [self.answer(arm["arm_id"], case)]
        return super().send(arm, url, headers, payload, timeout_s)


def _hashes_in(obj):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "data" and isinstance(v, str):
                out.add(hashlib.sha256(v.encode()).hexdigest())
            out |= _hashes_in(v)
    elif isinstance(obj, list):
        for x in obj:
            out |= _hashes_in(x)
    return out


# ---- configuration and routing (refused before any transport exists)
check("G1 unknown provider is refused before transport", g_refuses(lambda: MC.validate_arm(g_arm() | {"provider": "llama"}), "unknown provider"))
check("G2 provider/route mismatch is refused", g_refuses(lambda: MC.validate_arm(g_arm() | {"route": "local"}), "cloud route"))
check("G3 a local arm pointed at a cloud host is refused (no local-to-cloud fallback)",
      g_refuses(lambda: MC.validate_arm(g_arm(provider="ollama_local") | {"endpoint": "https://api.openai.com/v1/chat/completions"}), "not allowed"))
check("G4 a cloud arm pointed at a non-provider host is refused",
      g_refuses(lambda: MC.validate_arm(g_arm() | {"endpoint": "https://api.anthropic.com.evil.example/v1/messages"}), "not allowed"))
check("G5 a fallback/override field does not exist (unknown field refused)",
      g_refuses(lambda: MC.validate_arm(g_arm(provider="ollama_local") | {"fallback_endpoint": "https://api.openai.com"}), "unknown field"))
check("G6 an image task on an arm without image input is refused",
      g_refuses(lambda: MC.validate_arm(g_arm() | {"modalities": ["text"]}), "image"))
check("G7 private local-only data may never be allowed on a cloud arm",
      g_refuses(lambda: MC.validate_arm(g_arm() | {"allowed_data_classes": ["public_synthetic", "private_local_only"]}), "never be allowed"))
check("G8 private data offered to an arm that does not allow it is refused",
      g_refuses(lambda: MC.validate_arm(g_arm(provider="ollama_local"), data_class="private_local_only"), "not allowed"))
q = g_arm() | {"model_requested": MC.PLACEHOLDER, "image_capability_verified": False, "status": "queued",
               "dispatch_enabled": False, "limits": {"max_calls": None, "max_attempts_per_trial": 3, "timeout_s": 5}}
check("G9 a queued placeholder arm validates for dry-run but is refused for dispatch, naming every gap",
      "returned" in attempt(lambda: MC.validate_arm(q))
      and g_refuses(lambda: MC.validate_arm(q, for_dispatch=True), "model_requested; image_capability_verified"))
local_bad = g_arm(provider="ollama_local")
rt = RecordedTransport([anth("{}")])
sent = attempt(lambda: rt.send(local_bad, "https://api.openai.com/v1/chat/completions", {}, {}, 5))
check("G10 the transport itself refuses a local arm's request to a cloud URL (second line of defence)",
      "TransportDenied" in sent.get("error", "") and rt.sent == [], str(sent))
with patch.object(urllib.request, "urlopen", side_effect=_no_net), patch.object(urllib.request.OpenerDirector, "open", side_effect=_no_net):
    ht = attempt(lambda: HttpTransport().send(local_bad, "https://api.openai.com/v1/chat/completions", {}, {}, 5))
check("G11 the HTTP transport refuses the same request before opening a connection",
      "TransportDenied" in ht.get("error", ""), str(ht))
check("G12 the deny transport refuses every send", "TransportDenied" in attempt(lambda: DenyTransport().send(g_arm(), "https://api.anthropic.com/v1/messages", {}, {}, 5)).get("error", ""))

# ---- dispatch gate
arms_ok = [g_arm()]
cfg_ok = g_cfg(arms_ok)
m_ok = g_manifest(cfg_ok, arms_ok)
env_ok = {"TEST_KEY_ENV": "k" * 20, RN.ACK_ENV: m_ok["manifest_hash"][:12]}
gate = {
    "no_cli_flag": g_refuses(lambda: RN.live_transport(cfg_ok, arms_ok, m_ok, cli_dispatch=False, environ=env_ok), "command line"),
    "config_disabled": g_refuses(lambda: RN.live_transport(g_cfg(arms_ok, dispatch={"enabled": False}), arms_ok, m_ok, cli_dispatch=True, environ=env_ok), "dispatch.enabled"),
    "wrong_ack": g_refuses(lambda: RN.live_transport(cfg_ok, arms_ok, m_ok, cli_dispatch=True, environ=dict(env_ok, **{RN.ACK_ENV: "000000000000"})), RN.ACK_ENV),
    "missing_credential": g_refuses(lambda: RN.live_transport(cfg_ok, arms_ok, m_ok, cli_dispatch=True, environ={RN.ACK_ENV: m_ok["manifest_hash"][:12]}), "credential"),
    "no_call_cap": g_refuses(lambda: RN.live_transport(g_cfg(arms_ok, run_caps={}), arms_ok, m_ok, cli_dispatch=True, environ=env_ok), "max_calls_total"),
    "usd_cap_without_prices": g_refuses(lambda: RN.live_transport(g_cfg(arms_ok, run_caps={"max_calls_total": 5, "max_usd": 1}), arms_ok, m_ok, cli_dispatch=True, environ=env_ok), "prices"),
    "placeholder_model": g_refuses(lambda: RN.live_transport(g_cfg([q]), [q], m_ok, cli_dispatch=True, environ=env_ok), "not dispatchable"),
}
opened = attempt(lambda: RN.live_transport(cfg_ok, arms_ok, m_ok, cli_dispatch=True, environ=env_ok))
check("G13 dispatch gate: each missing condition refuses; all conditions together return the HTTP transport",
      all(gate.values()) and isinstance(opened.get("returned"), HttpTransport), json.dumps(gate))
unv = g_arm() | {"image_capability_verified": False}
cap_cfg = g_cfg([unv], protocol={"protocol_id": "cap", "trials": 1, "order_seed": "t", "capability_check": True})
cap_m = g_manifest(cap_cfg, [unv])
sco_m = g_manifest(g_cfg([unv]), [unv])
cap_open = attempt(lambda: RN.live_transport(cap_cfg, [unv], cap_m, cli_dispatch=True,
                                             environ={"TEST_KEY_ENV": "k" * 20, RN.ACK_ENV: cap_m["manifest_hash"][:12]}))
check("G44 an arm whose image capability is unverified may dispatch only a capability-check run, never a scored run",
      isinstance(cap_open.get("returned"), HttpTransport)
      and g_refuses(lambda: RN.live_transport(g_cfg([unv]), [unv], sco_m, cli_dispatch=True,
                                              environ={"TEST_KEY_ENV": "k" * 20, RN.ACK_ENV: sco_m["manifest_hash"][:12]}),
                    "image_capability_verified"), str(cap_open)[:120])
arm_c = g_arm(); arm_c2 = json.loads(json.dumps(arm_c)); arm_c2["limits"]["max_calls"] = 999
arm_c3 = json.loads(json.dumps(arm_c)); arm_c3["limits"]["max_attempts_per_trial"] = 5
h1, h2, h3 = (g_manifest(g_cfg([x]), [x])["manifest_hash"] for x in (arm_c, arm_c2, arm_c3))
check("G46 raising an arm's call cap keeps the manifest (a stopped run can resume); changing its retry policy does not",
      h1 == h2 and h1 != h3)
tl_dir = tempfile.mkdtemp(dir=TMP_ROOT)


def tl_cfg(hosts):
    p = os.path.join(tl_dir, f"c{len(os.listdir(tl_dir))}.json")
    json.dump({"arms": [], "trusted_local_hosts": hosts}, open(p, "w"))
    return p


lan = g_arm(provider="ollama_local") | {"endpoint": "http://192.168.1.20:11434/api/chat"}
check("G47 trusted local hosts must be private IP literals: names and public IPs are refused; a listed private IP is "
      "reachable and still cannot open a cloud host",
      g_refuses(lambda: MC.load_config(tl_cfg(["api.openai.com"])), "private IP")
      and g_refuses(lambda: MC.load_config(tl_cfg(["8.8.8.8"])), "private IP")
      and "returned" in attempt(lambda: MC.load_config(tl_cfg(["192.168.1.20"])))
      and "returned" in attempt(lambda: MC.validate_arm(lan, trusted_local_hosts=("192.168.1.20",)))
      and not MC.endpoint_allowed(lan, "https://api.openai.com/v1/chat/completions", ("api.openai.com", "192.168.1.20"))
      and g_refuses(lambda: MC.validate_arm(lan), "not allowed"))
qcfg = json.load(open(os.path.join(ROOT, "configs", "arms.queued.json"), encoding="utf-8"))
qm = RN.build_manifest(qcfg, qcfg["arms"], G_CASES_ALL, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX,
                       scorer_sha256="x", renderer_sha256="x", data_class="public_synthetic")
qenv = {"ANTHROPIC_API_KEY": "k" * 20, "OPENAI_API_KEY": "k" * 20, RN.ACK_ENV: qm["manifest_hash"][:12]}
check("G14 the shipped queued config is valid, has dispatch disabled, and the gate refuses it",
      all("returned" in attempt(lambda a=a: MC.validate_arm(a)) for a in qcfg["arms"])
      and qcfg["dispatch"]["enabled"] is False and all(a["dispatch_enabled"] is False for a in qcfg["arms"])
      and g_refuses(lambda: RN.live_transport(qcfg, qcfg["arms"], qm, cli_dispatch=True, environ=qenv)))
with patch.object(urllib.request, "urlopen", side_effect=_no_net), patch.object(urllib.request.OpenerDirector, "open", side_effect=_no_net):
    pkt = attempt(lambda: RN.dry_run_packet(qm, qcfg, qcfg["arms"], G_CASES_ALL, prompt=e.TASK_PROMPT))
pj = json.dumps(pkt.get("returned"))
check("G15 the dry-run packet plans 3 arms x 40 cases x 3 trials = 360 units, sends nothing and holds no image bytes",
      "returned" in pkt and pkt["returned"]["planned_units_total"] == 360 and len(pj) < 200_000
      and "iVBORw0KGgo" not in pj, str(pkt.get("error", ""))[:120])

# ---- adapters (request shape from the providers' documentation; a built request is not a working call)
img = open(G_CASES[0]["png_path"], "rb").read()
_, ah, ap_ = build_request(g_arm(), img, "image/png", "P", credential="k" * 20)
_, oh, op_ = build_request(g_arm(provider="openai"), img, "image/png", "P", credential="k" * 20)
_, lh, lp_ = build_request(g_arm(provider="ollama_local"), img, "image/png", "P")
check("G16 adapters: Anthropic image block before text; OpenAI data URL with explicit detail and "
      "max_completion_tokens; Ollama images list with stream false; local request carries no key",
      ap_["messages"][0]["content"][0]["type"] == "image" and ap_["messages"][0]["content"][1]["type"] == "text"
      and op_["messages"][0]["content"][0]["image_url"]["detail"] == "high"
      and op_["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
      and "max_completion_tokens" in op_ and "max_tokens" not in op_
      and lp_["stream"] is False and len(lp_["messages"][0]["images"]) == 1
      and not any(k.lower() in ("authorization", "x-api-key") for k in lh))
fin = (parse_response(g_arm(), anth("x", "max_tokens"))["finish"],
       parse_response(g_arm(provider="openai"), {"choices": [{"message": {"content": "x"}, "finish_reason": "content_filter"}]})["finish"],
       parse_response(g_arm(provider="ollama_local"), {"message": {"content": "x"}, "done_reason": "length"})["finish"])
check("G17 finish reasons map to length / refusal / length", fin == ("length", "refusal", "length"), str(fin))

# ---- runner outcomes and accounting
r1 = g_run(CaseAware(lambda arm, case: anth(G_PERFECT[case])))
check("G18 valid answers are scored; every planned unit is accounted for",
      r1["status"]["outcomes"]["scored"] == 2 and r1["status"]["unrun_units"] == 0
      and all(x["score"]["day_accuracy"] == 1.0 for x in r1["results"]), json.dumps(r1["status"]["outcomes"]))
r2 = g_run([anth("not JSON"), anth("still not JSON"), anth("no"), anth("nope")])
k2 = [a["kind"] for a in r2["attempts"]]
check("G19 an unparseable answer gets exactly one repair attempt, then ends invalid (both attempts kept)",
      r2["status"]["outcomes"]["invalid"] == 2 and k2.count("content_repair") == 2 and len(r2["attempts"]) == 4
      and all(a["prompt_variant"] == "repair" for a in r2["attempts"] if a["kind"] == "content_repair"), str(k2))
bad_null = perfect(G_GOLDS["sample_02_rotated"]); bad_null["days"][sorted(bad_null["days"])[0]] = None
bad_missing = perfect(G_GOLDS["sample_27_lowcontrast"]); bad_missing["days"].pop(sorted(bad_missing["days"])[0])
r3 = g_run([anth(json.dumps(bad_null)), anth(json.dumps(bad_missing))])
check("G20 null and missing day fields end invalid with a schema reason, not a crash and not a score",
      r3["status"]["outcomes"]["invalid"] == 2 and all(x["score"]["scored"] is False and x["score"]["invalid_reason"].startswith("schema")
                                                         for x in r3["results"]), json.dumps([x["score"]["invalid_reason"] for x in r3["results"]])[:160])
dup = G_PERFECT["sample_02_rotated"][:-1] + ', "month": "1999-01"}'
nonfinite = G_PERFECT["sample_27_lowcontrast"].replace('"global_notes"', '"x": NaN, "global_notes"', 1)
r4 = g_run([anth(dup), anth(dup), anth(nonfinite), anth(nonfinite)])
check("G21 conflicting duplicate keys and NaN are rejected (invalid after the repair attempt), never scored",
      r4["status"]["outcomes"]["invalid"] == 2, json.dumps(r4["status"]["outcomes"]))
r5_ = g_run([TransportError("HTTP 529", status=529, transient=True)] * 3 + [TransportError("HTTP 401", status=401, transient=False)])
check("G22 transient failures are retried up to the bound, a permanent one is not; both end 'unavailable', never 'invalid'; "
      "a run whose units ended without answers is INCOMPLETE, not COMPLETE",
      r5_["status"]["outcomes"]["unavailable"] == 2 and r5_["status"]["outcomes"]["invalid"] == 0 and len(r5_["attempts"]) == 4
      and r5_["status"]["run_status"] == "INCOMPLETE" and r1["status"]["run_status"] == "COMPLETE",
      json.dumps([r5_["status"]["outcomes"], r5_["status"]["run_status"]]))
r6 = g_run([anth('{"month": "2026-07"', "max_tokens"), anth("I can't help with that.", "refusal")])
saved6 = [json.load(open(os.path.join(r6["dir"], a["raw_file"]))) for a in r6["attempts"]]
check("G23 a truncated answer ends 'truncated' (text kept, not scored); a refusal ends 'refused'",
      [x["outcome"] for x in r6["results"]] == ["truncated", "refused"] and saved6[0]["text"] == '{"month": "2026-07"'
      and "score" not in r6["results"][0], json.dumps([x["outcome"] for x in r6["results"]]))

# ---- resume
rd = tempfile.mkdtemp(dir=TMP_ROOT)
part = g_run([anth(G_PERFECT["sample_02_rotated"])] * 2, trials=2, run_dir=rd, cfg_over={"run_caps": {"max_calls_total": 2}})
rest = g_run([anth(G_PERFECT["sample_02_rotated"]), anth(G_PERFECT["sample_27_lowcontrast"])] * 2, trials=2, run_dir=rd)
check("G24 a stopped run resumes with the same manifest: finished units are not re-asked, all units end once",
      part["status"]["run_status"] == "STOPPED" and part["status"]["terminal_units"] == 2
      and rest["status"]["run_status"] == "COMPLETE" and rest["status"]["terminal_units"] == 4
      and len({x["unit_id"] for x in rest["results"]}) == 4 and rest["status"]["attempts_total"] == 4
      and len(rest["transport"].sent) == 2, json.dumps([part["status"]["stopped"], rest["status"]["attempts_total"]]))
mism = attempt(lambda: g_run([anth("{}")], trials=3, run_dir=rd))
check("G25 a changed manifest (trials 2 -> 3) cannot resume into the same run directory",
      "RunRefused" in mism.get("error", "") and "identical manifest" in mism.get("error", ""), str(mism)[:140])
rd2 = tempfile.mkdtemp(dir=TMP_ROOT)
a1 = g_run([anth(G_PERFECT["sample_02_rotated"])], cases=G_CASES[:1], run_dir=rd2, cfg_over={"run_caps": {"max_calls_total": 1}})
os.remove(os.path.join(rd2, "results.jsonl"))         # simulate a crash after the answer, before the outcome
a2 = g_run([], cases=G_CASES[:1], run_dir=rd2)
check("G26 a unit whose answer was stored but whose outcome was not is finished from the stored answer, with no new call",
      a2["status"]["outcomes"]["scored"] == 1 and a2["transport"].sent == [] and a2["status"]["attempts_total"] == 1)

lk_dir = tempfile.mkdtemp(dir=TMP_ROOT)
rdl = RN.RunDir(lk_dir); rdl.lock()
blocked = attempt(lambda: g_run([anth(G_PERFECT["sample_02_rotated"])], cases=G_CASES[:1], run_dir=lk_dir))
rdl.unlock()
after = g_run([anth(G_PERFECT["sample_02_rotated"])], cases=G_CASES[:1], run_dir=lk_dir)
check("G48 one writer per run directory: a second run is refused while a lock is held, before it writes anything; "
      "a finished run releases its lock",
      "RunRefused" in blocked.get("error", "") and "run.lock" in blocked.get("error", "")
      and after["status"]["run_status"] == "COMPLETE" and not os.path.exists(os.path.join(lk_dir, "run.lock")),
      str(blocked)[:120])

# ---- replay, report, degenerate output
rp_dir = tempfile.mkdtemp(dir=TMP_ROOT)
mixed = [anth("not JSON"), anth(G_PERFECT["sample_02_rotated"]), TransportError("HTTP 503", status=503, transient=True),
         anth(G_PERFECT["sample_27_lowcontrast"])]
src = g_run(mixed)
rep = g_run(ReplayTransport(src["dir"]), run_dir=rp_dir)
strip = lambda rows: [{k: v for k, v in x.items() if k != "error"} for x in rows]
check("G27 offline replay of stored responses reproduces every outcome and score, with no network transport",
      strip(rep["results"]) == strip(src["results"]) and rep["status"]["attempts_total"] == src["status"]["attempts_total"]
      and rep["status"]["transport"] == "replay")
miss = g_run(ReplayTransport(tempfile.mkdtemp(dir=TMP_ROOT)))
check("G28 replay with no stored response ends 'unavailable' with a replay error, never a pass",
      miss["status"]["outcomes"]["unavailable"] == 2 and all("replay" in (x["error"] or "") for x in miss["results"]))


def all_status(gold, status):
    p = perfect(gold)
    for c in p["days"].values():
        c["status"] = status
    return json.dumps(p)


degen = g_run([anth(all_status(G_GOLDS[c["case_id"]], "UNAVAILABLE")) for c in G_CASES])
drep = MR.build_report([(MR.load_run(degen["dir"]), "a1")], G_GOLDS, e)
da = drep["arms"]["a1"]
check("G29 all-UNAVAILABLE output: critical-error rate 0, but flagged DEGENERATE with ~100% false unavailability "
      "and 0% document success - never a perfect result",
      da["historic_conditional"]["critical_error_rate"] == 0 and any(f.startswith("DEGENERATE") for f in da["flags"])
      and da["extended"]["false_unavailable_rate"] == 1.0 and da["extended"]["doc_success_rate_itt"] == 0.0
      and "DEGENERATE" in MR.render_markdown(drep), json.dumps(da["flags"])[:160])
inv = MR.build_report([(MR.load_run(r2["dir"]), "a1")], G_GOLDS, e)["arms"]["a1"]
check("G30 an all-invalid batch reports 100% unusable, 0% format validity and n/a conditional rates, flagged NOTHING SCORED",
      inv["accounting"]["unusable_rate"] == 1.0 and inv["historic_conditional"]["format_validity"] == 0.0
      and inv["historic_conditional"]["day_accuracy"] is None and any("NOTHING SCORED" in f for f in inv["flags"]))
una = MR.build_report([(MR.load_run(r5_["dir"]), "a1")], G_GOLDS, e)["arms"]["a1"]
check("G31 an all-unavailable batch has no historic block at all (no answer, nothing conditional to report)",
      una["historic_conditional"] is None and una["accounting"]["unavailable"] == 2 and una["accounting"]["unusable_rate"] == 1.0)
two = g_run(CaseAware(lambda arm, case: anth(G_PERFECT[case] if arm == "good" else all_status(G_GOLDS[case], "AVAILABLE"))),
            arms=[g_arm("good"), g_arm("bad")], cases=G_CASES)
prep = MR.build_report([(MR.load_run(two["dir"]), "good"), (MR.load_run(two["dir"]), "bad")], G_GOLDS, e, [("good", "bad")])
pc = prep["paired_document_level"][0] if prep["paired_document_level"] else {}
check("G32 paired document-level comparison: the better arm wins every document, with a sign test over documents",
      pc.get("sign_test", {}).get("a_better") == 2 and pc.get("sign_test", {}).get("b_better") == 0 and pc.get("documents") == 2,
      json.dumps(pc.get("sign_test")))
c01 = [c for c in G_CASES_ALL if c["case_id"] == "sample_01_clean"]
conf01 = CS.global_note_conflicts(G_GOLDS["sample_01_clean"])


def reconciled(gold):
    p = perfect(gold)
    for note, d, _ in CS.global_note_conflicts(gold):
        p["days"][d]["status"] = "UNAVAILABLE" if note in ("No Mondays", "No weekends") else "AVAILABLE"
    return json.dumps(p)


rec_run = g_run(CaseAware(lambda arm, case: anth(reconciled(G_GOLDS[case]) if arm == "rec" else G_PERFECT[case])),
                arms=[g_arm("rec"), g_arm("tra")], cases=c01)
crep = MR.build_report([(MR.load_run(rec_run["dir"]), "rec"), (MR.load_run(rec_run["dir"]), "tra")], G_GOLDS, e)["arms"]
gr, gt = crep["rec"]["extended"]["global_note_conflict_days"], crep["tra"]["extended"]["global_note_conflict_days"]
check("G45 the global-note conflict slice separates an arm that applied the note from one that reported the mark",
      len(conf01) > 0 and gr == {"days": len(conf01), "reported_mark": 0, "applied_note": len(conf01), "other": 0}
      and gt == {"days": len(conf01), "reported_mark": len(conf01), "applied_note": 0, "other": 0}, json.dumps([gr, gt]))
check("G33 positive controls for the statistics: sign test 9/0 gives p = 2/512; Holm never lowers a p-value",
      math.isclose(MR.sign_test_p(9, 0), 2 / 512) and MR.sign_test_p(0, 0) == 1.0
      and all(c["sign_test"]["p_holm"] >= c["sign_test"]["p_two_sided"]
              for c in MR.holm([{"sign_test": {"p_two_sided": p}} for p in (0.01, 0.04, 0.03)])))

# ---- case sets: duplicates, splits, render / reference agreement
dupset = G_CASES_ALL[:3] + [dict(G_CASES_ALL[0], case_id="sample_99_clean")]
check("G34 duplicate images and duplicate references inside a set are reported",
      any("png_sha256" in x for x in CS.check_set(dupset)) and any("truth_hash" in x for x in CS.check_set(dupset))
      and CS.check_set(G_CASES_ALL) == [])
check("G35 a confirmation set sharing a seed or reference with the development set is reported; disjoint sets pass",
      any("seed" in x for x in CS.check_splits(G_CASES_ALL[:5], [dict(G_CASES_ALL[4], case_id="c1", png_sha256="x", truth_hash="y")]))
      and CS.check_splits(G_CASES_ALL[:5], G_CASES_ALL[5:10]) == [])
import generate_dataset as G  # noqa: E402
font_ok = os.path.isfile(os.path.join(ROOT, "assets", "fonts", "PatrickHand-Regular.ttf"))
render_tmp = tempfile.mkdtemp(dir=TMP_ROOT)
c27 = [c for c in G_CASES_ALL if c["case_id"] == "sample_27_lowcontrast"][0]
c04 = [c for c in G_CASES_ALL if c["case_id"] == "sample_04_handwritten"][0]
planted_gold = load(c27["gold_path"]); k0 = sorted(planted_gold["days"])[0]
planted_gold["days"][k0]["status"] = "NIGHT" if planted_gold["days"][k0]["status"] != "NIGHT" else "AM"
pg_path = os.path.join(render_tmp, "planted.gold.json"); json.dump(planted_gold, open(pg_path, "w"))
planted = dict(c27, gold_path=pg_path)
# r7.1: the stored images were rendered with DejaVuSans from the Linux path generate_dataset.py looks for; elsewhere Pillow's
# default font is used, so pixel equality can only be checked where that reference font exists (Windows 2026-10-30: 33,370 px).
REF_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
ref_render = os.path.isfile(REF_FONT)
check("G36b a one-day change to a reference is detected by truth regeneration (any OS)",
      CS.regenerate_truth_check(c27, G) and not CS.regenerate_truth_check(planted, G))
if ref_render:
    r_ok, r_bad = CS.render_check(c27, G, render_tmp), CS.render_check(planted, G, render_tmp)
    check("G36 render check: the stored image re-renders pixel-exactly from its reference; a one-day change is detected",
          r_ok["result"] == "MATCH" and r_bad["result"] == "MISMATCH", json.dumps([r_ok, r_bad]))
else:
    unverified("G36 pixel-exact re-render", "reference font %s not present (the stored images were rendered with it)" % REF_FONT)
if font_ok and ref_render:
    check("G37 render check on a handwritten case (needs the bundled hand font)", CS.render_check(c04, G, render_tmp)["result"] == "MATCH")
else:
    unverified("G37 render check on a handwritten case", "needs assets/fonts/PatrickHand-Regular.ttf and the reference font %s" % REF_FONT)

# ---- historic metrics through the new layer
raw_s, raw_h = os.path.join(ROOT, "results", "raw"), os.path.join(ROOT, "results_haiku", "raw")
if os.path.isdir(raw_s) and os.path.isdir(raw_h):
    hist = {}
    for name, raw, pub in (("hist-sonnet", raw_s, "results"), ("hist-haiku", raw_h, "results_haiku")):
        d = tempfile.mkdtemp(dir=TMP_ROOT)
        import_legacy(raw, os.path.join(ROOT, "data"), d, arm_id=name, model_label=name, scorer=e, cases=G_CASES_ALL)
        got = MR.build_report([(MR.load_run(d), name)], G_GOLDS, e)["arms"][name]["historic_conditional"]
        want = load(os.path.join(ROOT, pub, "metrics.json"))["overall"]
        hist[name] = all(math.isclose(got[k], want[k], abs_tol=1e-12) if isinstance(want[k], float) else got[k] == want[k]
                         for k in ("day_accuracy", "critical_error_rate", "critical_flips", "gold_unavailable_days",
                                   "hallucination_rate", "note_fidelity", "format_validity", "cases"))
    check("G38 the stored v1 answers, imported into the new layer, reproduce both published metrics.json files exactly",
          all(hist.values()), json.dumps(hist))
else:
    unverified("G38 historic metrics through the new layer", "results*/raw/ not present (public checkout)")

# ---- secrets and ignore rules
rec = RecordedTransport([anth("{}")])
rec.send(g_arm(), "https://api.anthropic.com/v1/messages", {"x-api-key": "TEST_SENTINEL_NOT_A_REAL_KEY_456"},
         {"data": "A" * 500}, 5)
secret = "TEST_SENTINEL_NOT_A_REAL_KEY_789"
err = urllib.error.HTTPError("https://api.anthropic.com/v1/messages", 401, "x", {}, io.BytesIO(("echo " + secret).encode()))
with patch.object(urllib.request, "urlopen", side_effect=err), patch.object(urllib.request.OpenerDirector, "open", side_effect=err):
    hx = attempt(lambda: HttpTransport().send(g_arm(), "https://api.anthropic.com/v1/messages", {"x-api-key": secret}, {}, 5))
check("G39 logs keep header names only and hash image data; an echoed key is redacted from provider errors",
      "TEST_SENTINEL" not in json.dumps(rec.sent) and "A" * 300 not in json.dumps(rec.sent)
      and secret not in str(hx) and "[REDACTED]" in str(hx))
run_files = "".join(open(os.path.join(dp, f), encoding="utf-8").read() for dp, _, fs in os.walk(r1["dir"]) for f in fs)
check("G40 a run directory never contains the credential value", "k" * 20 not in run_files)
import mm_run  # noqa: E402
qpath = os.path.join(ROOT, "configs", "arms.queued.json")
cpath = os.path.join(ROOT, "configs", "arms.capability-check.json")
cli_tmp = tempfile.mkdtemp(dir=TMP_ROOT)
with patch.object(urllib.request, "urlopen", side_effect=_no_net), patch.object(urllib.request.OpenerDirector, "open", side_effect=_no_net), \
        contextlib.redirect_stdout(io.StringIO()), \
        contextlib.redirect_stderr(io.StringIO()):
    c_run = mm_run.main(["run", "--config", qpath, "--data", os.path.join(ROOT, "data"), "--run-dir", os.path.join(cli_tmp, "r1")])
    c_disp = mm_run.main(["run", "--config", qpath, "--data", os.path.join(ROOT, "data"), "--run-dir", os.path.join(cli_tmp, "r2"), "--dispatch"])
    c_plan = mm_run.main(["plan", "--config", cpath, "--data", os.path.join(ROOT, "data"), "--out", os.path.join(cli_tmp, "cap.json")])
check("G42 CLI: `run` on the queued config refuses with exit 2 and creates no run directory, with or without --dispatch",
      c_run == 2 and c_disp == 2 and not os.path.exists(os.path.join(cli_tmp, "r1")) and not os.path.exists(os.path.join(cli_tmp, "r2")))
cap = load(os.path.join(cli_tmp, "cap.json")) if os.path.exists(os.path.join(cli_tmp, "cap.json")) else {}
bad_cfg = json.load(open(cpath, encoding="utf-8")); bad_cfg["case_set"]["include"] = ["sample_99_nothing"]
bad_path = os.path.join(cli_tmp, "bad.json"); json.dump(bad_cfg, open(bad_path, "w"))
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    c_bad = mm_run.main(["plan", "--config", bad_path, "--data", os.path.join(ROOT, "data"), "--out", os.path.join(cli_tmp, "bad_pkt.json")])
check("G43 the capability-check config plans 3 arms x 4 named cases x 1 trial = 12 units; an unknown case name is refused",
      c_plan == 0 and cap.get("planned_units_total") == 12 and cap.get("cases") == 4 and c_bad == 2,
      json.dumps([c_plan, cap.get("planned_units_total"), c_bad]))
if shutil.which("git") is None or check_ignore("results/raw/probe.txt") == 128:
    unverified("G41 mm_runs/ is gitignored", "not a git checkout or git not available")
else:
    check("G41 multi-model run directories (raw answers, attempt ledgers) are gitignored; configs stay trackable",
          check_ignore("mm_runs/x/raw/a.json") == 0 and check_ignore("mm_runs/x/attempts.jsonl") == 0
          and check_ignore("configs/arms.queued.json") == 1)


# ======================================================================= H · r7 resume safety and reporting integrity
# REC-05/06/07 (resume after a stop must not resend or turn a terminal attempt retryable), REC-11 (duplicate outcome
# rows), ACC-08 (out-of-plan rows), REC-13 (same arm id in two runs), and torn ledger lines. The checks live in
# tests/test_resume_reporting.py, which also runs against any built tree on its own; this section runs it and records
# every check here, so the standard suite guards the repairs. Offline: urlopen is patched to fail inside that file.
print("== H · r7: resume safety and reporting integrity (tests/test_resume_reporting.py) ==")
h_json = os.path.join(TMP_ROOT, "h_results.json")
h_env = dict(os.environ, TMPDIR=TMP_ROOT, PYTHONDONTWRITEBYTECODE="1")
hp = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "tests", "test_resume_reporting.py"), ROOT, "--json", h_json],
                    capture_output=True, text=True, timeout=900, env=h_env)
h_rows = json.load(open(h_json, encoding="utf-8"))["results"] if os.path.exists(h_json) else []
check("H0 the resume/reporting file ran to completion and reported at least 21 checks",
      hp.returncode in (0, 1) and len(h_rows) >= 21 and "Traceback" not in hp.stderr,
      f"exit {hp.returncode}; {len(h_rows)} checks; {hp.stderr.strip()[-120:]}")
for h_row in h_rows:
    check(f"H-{h_row['id']} {h_row['check']}", h_row["result"] == "PASS", json.dumps(h_row["observed"])[:120])

# ======================================================================= F · the checkout is unchanged
print("== F · the run leaves the checkout unchanged ==")
probe_dir = tempfile.mkdtemp(dir=TMP_ROOT)
s0 = tree_snapshot(probe_dir)
open(os.path.join(probe_dir, "probe.txt"), "w").write("x")
check("F0 positive control: the snapshot comparator detects an added file", s0 != tree_snapshot(probe_dir))
changed = sorted({p for p, *_ in SNAP0 ^ tree_snapshot(ROOT)})
check("F1 the run wrote nothing into the checkout (paths, sizes, times; .git excluded)",
      not changed, ", ".join(changed[:5]) + (" ..." if len(changed) > 5 else ""))

n_pass = sum(1 for r in results if r[0] == "PASS")
n_fail = sum(1 for r in results if r[0] == "FAIL")
n_unv = sum(1 for r in results if r[0] == "UNVERIFIED")
print(f"\n{n_pass} PASS · {n_fail} FAIL · {n_unv} UNVERIFIED")
if n_unv and not n_fail and not ALLOW_UNVERIFIED:
    print("UNVERIFIED checks did not run here; exit 2. Pass --allow-unverified to accept them (e.g. a public checkout).")
sys.exit(1 if n_fail else 2 if (n_unv and not ALLOW_UNVERIFIED) else 0)
