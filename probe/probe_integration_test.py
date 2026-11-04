#!/usr/bin/env python3
"""probe_integration_test.py — runs the founder's ENTIRE Arm A path end-to-end with a mocked model. CANDIDATE A02-r1.

No API, no local model, no photographs: the extraction function is replaced by a test double that reads the gold.
Every check can fail, and the script says which one did. Changes from 2026-09-12 (sha256 dc636492…): T4-T6 and T8 assert
the document-level rules of Amendment 01 (CLOSE retired; Stage 1 is a pilot); T6b-T6d test the Stage 2 minimums;
T12-T13 test the local-only route.

  T1  make_probe_kit builds a kit whose geometry is balanced within condition
  T2  a filled intent CSV converts to gold; a blank or illegal one is REFUSED
  T3  probe_score.main() runs on real files (templates stand in for photos) and writes PROBE-RESULTS.md
  T4  Stage 1, every authored document wrong, copyist perfect -> PILOT, no verdict, never PROCEED
  T5  Stage 1, everything perfect -> PILOT, and CLOSE is stated as retired
  T6  Stage 2 (7 docs/arm), everything perfect -> CONTINUE, never CLOSE
  T6b Stage 2, 5/7 authored error documents vs 0/7 -> PROCEED (the minimum)
  T6c Stage 2, 4/7 vs 0/7 -> CONTINUE
  T6d Stage 2, 6/7 vs 1/7 -> CONTINUE (p < .05 but the Wilson intervals overlap)
  T7  no output contains a forbidden credential string
  T8  a single-arm run says it describes one family only
  T9  a month-mismatched document is excluded, not scored as error
  T10 an empty photos directory -> RUN INVALID and exit 1
  T11 equal error documents in both arms -> not PROCEED
  T12 a real run without --arm-config refuses before anything is sent
  T13 a cloud arm in --arm-config is refused (private data never goes to a cloud route)

Usage:  python3 probe_integration_test.py [--mmeval-root <repo with mmeval/>]    exit 0 = all pass · 1 = a check failed
"""
import os, sys, json, csv, shutil, subprocess, tempfile, importlib, contextlib, io

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FORBIDDEN = ("NRP", "NREMT", "prehospital", "field practice")


def run(cmd, cwd):
    return subprocess.run([sys.executable, "-B", "-X", "utf8"] + cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def fill_intent(path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    out = [rows[0]]
    cyc = ["AM", "AM", "PM", "UNAVAILABLE", "AVAILABLE", "NIGHT", "UNAVAILABLE", "PM"]
    for i, r in enumerate(rows[1:]):
        if r and r[0] == "GLOBAL_NOTES":
            out.append([r[0], "No weekends", ""]); continue
        if r and r[0]:
            out.append([r[0], cyc[i % 8], "charge only" if i == 6 else ""])
    csv.writer(open(path, "w", newline="", encoding="utf-8")).writerows(out)


def mock_model(errors_for, kit):
    """errors_for(doc_id, condition) -> number of plain misreads to inject into that document."""
    man = json.load(open(os.path.join(kit, "MANIFEST.json")))
    cond = {d["doc_id"]: d["condition"] for d in man["documents"]}

    def fake_call(model, key, img_path, prompt):
        did = os.path.basename(img_path).rsplit(".", 1)[0]
        c = cond[did]
        gp = os.path.join(kit, f"spec_{did}.gold.json" if c == "copy" else f"intent_{did}.gold.json")
        g = json.load(open(gp)); pred = {"month": g["month"], "days": {}, "global_notes": list(g["global_notes"])}
        n_err, k = errors_for(did, c), 0
        for day, cell in g["days"].items():
            st = cell["status"]
            if k < n_err and st != "UNAVAILABLE":
                st = "PM" if st != "PM" else "AM"; k += 1
            pred["days"][day] = {"status": st, "note": cell["note"]}
        return json.dumps(pred)
    return fake_call


def by_cond(spec):
    return lambda did, c: spec.get(c, 0)


def first_k(cond, k, n_err=3, other=None):
    """The first k documents of `cond` carry n_err misreads each; `other` (cond, k2) likewise."""
    def f(did, c):
        idx = int(did.rsplit("-", 1)[-1])
        if c == cond and idx <= k:
            return n_err
        if other and c == other[0] and idx <= other[1]:
            return n_err
        return 0
    return f


def main():
    mmeval_root = sys.argv[sys.argv.index("--mmeval-root") + 1] if "--mmeval-root" in sys.argv else \
        os.path.dirname(HERE)
    tmp = tempfile.mkdtemp(prefix="probe_it_")
    kit = os.path.join(tmp, "kit"); photos = os.path.join(tmp, "photos"); os.makedirs(photos)
    fails, outputs = [], []

    def check(name, ok):
        print(f"{name:88s} -> {'PASS' if ok else 'FAIL'}")
        ok or fails.append(name.split()[0])

    r = run(["make_probe_kit.py", "--out", kit], HERE)
    man = json.load(open(os.path.join(kit, "MANIFEST.json")))
    from collections import Counter
    bal = Counter((d["geometry"], d["condition"]) for d in man["documents"])
    check(f"T1 kit builds, geometry balanced within condition {dict(bal)}",
          r.returncode == 0 and bal[("A", "copy")] == bal[("A", "auth")] and bal[("B", "copy")] == bal[("B", "auth")])

    blank = os.path.join(kit, "intent_A-auth-1.csv")
    r_blank = run(["intent_to_gold.py", blank], HERE)
    ok2 = r_blank.returncode != 0 and "REFUSING" in r_blank.stdout
    for d in man["documents"]:
        if d["condition"] == "auth":
            fill_intent(os.path.join(kit, f"intent_{d['doc_id']}.csv"))
            r2 = run(["intent_to_gold.py", os.path.join(kit, f"intent_{d['doc_id']}.csv")], HERE)
            ok2 = ok2 and r2.returncode == 0 and os.path.exists(os.path.join(kit, f"intent_{d['doc_id']}.gold.json"))
    check("T2 blank intent REFUSED; filled intent -> gold", ok2)
    for d in man["documents"]:
        shutil.copy(os.path.join(kit, d["template"]), os.path.join(photos, d["doc_id"] + ".jpg"))

    import probe_score

    def run_probe(errors_for, out_name, models="mock-a,mock-b", photos_dir=None, patch=True):
        importlib.reload(probe_score)
        if patch:
            probe_score.call_vision = mock_model(errors_for, kit)
        out = os.path.join(tmp, out_name)
        argv = sys.argv; sys.argv = ["probe_score.py", "--kit", kit, "--photos", photos_dir or photos, "--out", out, "--models", models]
        code = 0
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                probe_score.main()
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = argv
        p = os.path.join(out, "PROBE-RESULTS.md")
        txt = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        outputs.append(txt)
        return txt, code

    txt, _ = run_probe(by_cond({"copy": 0, "auth": 8}), "r_effect")
    check("T3 scorer runs end-to-end and writes PROBE-RESULTS.md", "Decision against the amended rule" in txt and "| mock-a |" in txt)
    check("T4 Stage 1, every authored document wrong vs copyist perfect -> PILOT, never PROCEED",
          "**PILOT — no verdict.**" in txt and "**PROCEED**" not in txt)
    txt, _ = run_probe(by_cond({}), "r_ceiling1")
    check("T5 Stage 1 perfect -> PILOT; CLOSE stated as retired, never printed as a verdict",
          "**PILOT — no verdict.**" in txt and "CLOSE is retired" in txt and "CLOSE THE TRACK" not in txt)

    man2 = json.load(open(os.path.join(kit, "MANIFEST.json")))
    for cond, src in (("copy", "A-copy-1"), ("auth", "A-auth-1")):
        n_have = sum(1 for d in man2["documents"] if d["condition"] == cond)
        for n in range(n_have + 1, 8):
            did = f"A-{cond}-{n}"
            gsrc = os.path.join(kit, f"spec_{src}.gold.json" if cond == "copy" else f"intent_{src}.gold.json")
            gdst = os.path.join(kit, f"spec_{did}.gold.json" if cond == "copy" else f"intent_{did}.gold.json")
            shutil.copy(gsrc, gdst); shutil.copy(os.path.join(photos, src + ".jpg"), os.path.join(photos, did + ".jpg"))
            man2["documents"].append({"doc_id": did, "geometry": "A", "condition": cond, "template": "template_A_grid.png"})
    json.dump(man2, open(os.path.join(kit, "MANIFEST.json"), "w"), indent=2)
    n_auth = sum(1 for d in man2["documents"] if d["condition"] == "auth")
    n_copy = sum(1 for d in man2["documents"] if d["condition"] == "copy")
    # every B-geometry document is kept perfect, so only A-geometry documents carry errors; renumbering is by doc suffix
    a_auth = sorted(d["doc_id"] for d in man2["documents"] if d["condition"] == "auth")
    a_copy = sorted(d["doc_id"] for d in man2["documents"] if d["condition"] == "copy")

    def exact(auth_err_docs, copy_err_docs):
        bad = set(a_auth[:auth_err_docs]) | set(a_copy[:copy_err_docs])
        return lambda did, c: 3 if did in bad else 0

    txt, _ = run_probe(by_cond({}), "r_ceiling2")
    check(f"T6 Stage 2 ({n_auth}/{n_copy} docs per arm) perfect -> CONTINUE, never CLOSE",
          "Stage 2" in txt and "**CONTINUE**" in txt and "CLOSE THE TRACK" not in txt)
    txt, _ = run_probe(exact(5, 0), "r_min5")
    check("T6b Stage 2, 5 of 7 authored error documents vs 0 of 7 -> PROCEED (the minimum)",
          n_auth == 7 and n_copy == 7 and "**PROCEED**" in txt)
    txt, _ = run_probe(exact(4, 0), "r_min4")
    check("T6c Stage 2, 4 of 7 vs 0 of 7 -> CONTINUE", "**CONTINUE**" in txt and "**PROCEED**" not in txt)
    txt, _ = run_probe(exact(6, 1), "r_overlap")
    check("T6d Stage 2, 6 of 7 vs 1 of 7 -> CONTINUE (p < .05 but the intervals overlap)",
          "**CONTINUE**" in txt and "| Wilson intervals overlap | True |" in txt)
    txt8, _ = run_probe(by_cond({}), "r_single", models="mock-a")
    check("T8 a single-arm run states that it describes one family only", "Single-family run" in txt8)

    importlib.reload(probe_score)
    base_mock = mock_model(by_cond({}), kit)

    def month_bug(model, key, img_path, prompt):
        out = json.loads(base_mock(model, key, img_path, prompt))
        if os.path.basename(img_path).startswith("A-auth-1"):
            out["month"] = "2026-11"
        return json.dumps(out)
    probe_score.call_vision = month_bug
    out9 = os.path.join(tmp, "r_month"); argv = sys.argv
    sys.argv = ["probe_score.py", "--kit", kit, "--photos", photos, "--out", out9, "--models", "mock-b"]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            probe_score.main()
    finally:
        sys.argv = argv
    txt9 = open(os.path.join(out9, "PROBE-RESULTS.md"), encoding="utf-8").read(); outputs.append(txt9)
    check("T9 month-mismatched document flagged, excluded, does not force PROCEED",
          "excluded as parse failures: A-auth-1/mock-b" in txt9 and "**PROCEED**" not in txt9)
    empty = os.path.join(tmp, "nophotos"); os.makedirs(empty, exist_ok=True)
    txt10, code10 = run_probe(by_cond({}), "r_empty", models="mock-b", photos_dir=empty)
    check(f"T10 empty photos dir -> RUN INVALID banner + exit 1 (got exit {code10})", code10 == 1 and "RUN INVALID" in txt10)
    txt11, _ = run_probe(exact(5, 5), "r_equal")
    check("T11 equal error documents in both arms (5 of 7 each) -> NOT PROCEED", "**PROCEED**" not in txt11)
    sent = []
    import urllib.request as _u
    real_urlopen = _u.urlopen
    _u.urlopen = lambda *a, **k: sent.append(1) or (_ for _ in ()).throw(AssertionError("network"))
    try:
        txt12, code12 = run_probe(None, "r_noconfig", models="mock-a", patch=False)
    finally:
        _u.urlopen = real_urlopen
    check("T12 without --arm-config the real extraction refuses and nothing is sent",
          isinstance(code12, str) and "REFUSED" in code12 and not sent)
    if os.path.isdir(os.path.join(mmeval_root, "mmeval")):
        cloud = {"arms": [{"arm_id": "c", "role": "t", "provider": "anthropic", "route": "cloud",
                           "endpoint": "https://api.anthropic.com/v1/messages", "model_requested": "m",
                           "modalities": ["text", "image"], "image_capability_verified": True, "credential_env": "X",
                           "allowed_data_classes": ["public_synthetic", "private_local_only"], "status": "ready",
                           "dispatch_enabled": True, "limits": {"max_calls": 5, "max_attempts_per_trial": 1, "timeout_s": 5}}]}
        cp = os.path.join(tmp, "cloud.json"); json.dump(cloud, open(cp, "w"))
        importlib.reload(probe_score)
        try:
            probe_score.load_local_arms(cp, mmeval_root); refused = False
        except Exception as e:
            refused = "never be allowed" in str(e)
        check("T13 a cloud arm offered private_local_only data is refused by the arm configuration", refused)
    else:
        print(f"T13 UNVERIFIED: no mmeval/ under {mmeval_root}"); fails.append("T13-UNVERIFIED")

    bad = [w for w in FORBIDDEN if w.lower() in "".join(outputs).lower()]
    check(f"T7 no forbidden credential strings in any output ({bad or 'none'})", not bad)
    shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print(f"\n*** INTEGRATION TEST FAILED: {fails} ***"); return 1
    print("\nINTEGRATION TEST PASS — the whole Arm A path runs; PROCEED is reachable only where Amendment 01 says; CLOSE never.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
