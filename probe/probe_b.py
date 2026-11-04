#!/usr/bin/env python3
"""
probe_b.py — Arm B of the probe: the author's REAL availability documents.  CANDIDATE A02-r1 (2026-10-26).
Pre-registration: docs/PROBE-B.md (committed before any image was scored), amended by PROBE-AMENDMENT-01 and -02.

Changes from the 2026-09-12 file (ed-eval-probe/probe_b.py, sha256 d399daa5…, preserved unchanged there):
  * decisions at the DOCUMENT level (probe_decide.decide_arm_b); G3 is excluded from every decision denominator and
    still scored and reported in full; B-CLOSE is retired and cannot be printed
  * a grid document that fails to parse counts as an error document ("scoring every document, including badly
    photographed ones", carried over unchanged by Amendment 01 §4) and is listed
  * the synthetic baseline is the same model's own synthetic run, counted in ERROR DOCUMENTS from a results file
    named on the command line (never typed in); no baseline on file -> B-PROCEED cannot fire
  * photographs are scored only by a validated LOCAL arm (probe_score.call_vision; D-1, Amendment 01 §4b)
  * RES-03: the self-test uses only legal statuses and its own synthetic map, so it passes in a clean room
  * families are stated; they no longer gate any branch

  python3 probe_b.py --make-kit                     # writes kit-B/MANIFEST-B.json + intent CSVs (frozen document set)
  python3 probe_b.py --selftest                     # positive controls; no model, no images, no private files
  python3 probe_b.py --mock --error-docs 2          # end-to-end with a fake model
  python3 probe_b.py --photos <dir> --arm-config <local arms> --baseline <arm>=<per_case.csv | mm run dir> --amendment-02-frozen

CONFIDENTIALITY: --photos points at a private folder. Photos are sent only to the configured local vision endpoint.
Raw model transcriptions are saved under --out/raw and can contain private document text. Keep all probe outputs private.
"""
import argparse, json, os, sys, calendar, csv
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_score as A                                   # Arm A candidate: local route, strict parse, typed scoring
import probe_decide as PD
from intent_to_gold import build as build_gold, LEGAL

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "kit-B")
REPO = os.path.dirname(HERE)

DOCS = [{"doc_id": d, "kind": "grid"} for d in ("G1","G2","G3","G4","G5","G6","G7")] + \
       [{"doc_id": d, "kind": "list"} for d in ("F1","F2","F3","F4")]
EXCLUDED_FROM_DECISION = {"G3"}       # duplicate month of G2 (Amendment 01 §2): scored and reported, never decides
PRIVATE_MAP = "private-map.json"      # in kit-B/ ; gitignored, never shipped, never committed


def load_private():
    p = os.path.join(KIT, PRIVATE_MAP)
    if not os.path.isfile(p):
        sys.exit(f"REFUSED: {p} not found.\nIt maps each abstract document ID to its month, photo filename and legend, and it "
                 "is the only place those appear. It is deliberately not in the repository.")
    return json.load(open(p, encoding="utf-8"))


def enrich(docs, priv):
    from mmeval.config import safe_identifier
    out = []
    for d in docs:
        if not safe_identifier(d.get("doc_id")):
            raise ValueError("document ID must be a portable filename identifier")
        m = priv.get(d["doc_id"])
        if not m:
            sys.exit(f"REFUSED: {d['doc_id']} missing from {PRIVATE_MAP}")
        if set(m) & {"doc_id", "kind"}:
            raise ValueError("private map may not override the document ID or kind")
        A.photo_name(m.get("photo"))
        if m.get("pair"):
            A.photo_name(m["pair"])
        out.append({**d, **m})
    return out


SCHEMA_GRID = ('{"month": "YYYY-MM", "days": {"YYYY-MM-DD": {"status": "AVAILABLE|AM|PM|NIGHT|UNAVAILABLE", "note": ""}}, '
               '"global_notes": []}')
SCHEMA_LIST = '{"dates": ["YYYY-MM-DD", ...], "shift": "AVAILABLE|AM|PM|NIGHT|UNAVAILABLE|UNKNOWN", "notes": []}'


def prompt_for(doc, condition):
    if doc["kind"] == "grid":
        base = ("This image is a filled-in monthly staff availability calendar written by hand. Extract it to JSON with exactly "
                f"this schema: {SCHEMA_GRID}. Every day of the month must appear. Infer what each mark means from the page; "
                "a cell with no mark takes whatever the page implies for unmarked days. Transcribe any writing in the margins "
                "as global_notes, exactly as written. Do not invent notes. Output ONLY the JSON.")
    else:
        base = ("This image is a handwritten list of dates on which a staff member is available or scheduled. Extract it to JSON "
                f"with exactly this schema: {SCHEMA_LIST}. Use the year and month implied by the page. List only dates actually "
                "written on the page. Output ONLY the JSON.")
    if condition == "given":
        base += f" LEGEND FOR THIS DOCUMENT: {doc['legend']}."
    return base


AMENDED_RULE = {
    "unit": "document; an error document has at least one status error (PROBE-AMENDMENT-01 §2)",
    "B-PROCEED": "two-sided Fisher exact p < 0.05 on error documents, LEGEND-BLIND output of the best model, the 6 real grid "
                 "documents (G3 excluded) against that model's own synthetic run, real > synthetic, AND Wilson 95% lower bound "
                 "of the real error-document rate > 1%",
    "B-CLOSE": "RETIRED (Amendment 01 §3: 189 documents would be needed)",
    "B-CONTINUE": "otherwise",
    "route": "local vision model only (D-1; Amendment 01 §4b; PROBE-AMENDMENT-02)"}


def make_kit():
    os.makedirs(KIT, exist_ok=True)
    docs = enrich(DOCS, load_private())
    for d in docs:
        p = os.path.join(KIT, f"intent_{d['doc_id']}.csv")
        y, m = map(int, d["month"].split("-")); nd = calendar.monthrange(y, m)[1]
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if d["kind"] == "grid":
                w.writerow(["date", "status  (fill ONLY the days you MARKED; AVAILABLE|AM|PM|NIGHT|UNAVAILABLE, or the mark you actually used)", "note (exactly what you wrote, or blank)"])
                for i in range(nd):
                    w.writerow([f"{y:04d}-{m:02d}-{i+1:02d}", "", ""])
                w.writerow(["DEFAULT_STATUS", "", "REQUIRED: what an UNMARKED day meant on THIS document (usually AVAILABLE or UNAVAILABLE)"])
                w.writerow(["LEGEND", d["legend"], "correct this if wrong"])
                w.writerow(["GLOBAL_NOTES", "", "anything written outside the grid, exactly as written; separate with ;"])
            else:
                w.writerow(["date  (ONLY the dates written on the page)", "status", "note"])
                w.writerow([f"{y:04d}-{m:02d}-01", "", "delete or edit; add one row per date on the page"])
                w.writerow(["LEGEND", d["legend"], "correct this if wrong"])
    public_docs = [{"doc_id": d["doc_id"], "kind": d["kind"],
                    "days": calendar.monthrange(*map(int, d["month"].split("-")))[1] if d["kind"] == "grid" else None,
                    "decides": d["kind"] == "grid" and d["doc_id"] not in EXCLUDED_FROM_DECISION}
                   for d in docs]
    man = {"_pre_registration": "docs/PROBE-B.md, committed BEFORE any image was scored; amended by docs/PROBE-AMENDMENT-01.md and -02.md.",
           "_privacy": "Photo filenames, months and the writer's encodings are NOT recorded here. They live in kit-B/private-map.json, which never ships.",
           "_frozen": "2026-09-06", "documents": public_docs, "decision_rule": AMENDED_RULE,
           "decision_rule_as_preregistered_2026-09-06": "B-CLOSE / B-PROCEED / B-CONTINUE over day-cells (PROBE-B.md §6); superseded by Amendment 01",
           "pairs": [{"doc_id": d["doc_id"]} for d in docs if d.get("pair")]}
    json.dump(man, open(os.path.join(KIT, "MANIFEST-B.json"), "w"), indent=2)
    ng = sum(1 for d in docs if d["kind"] == "grid")
    nd_ = sum(1 for d in public_docs if d["decides"])
    print(f"kit-B written: {ng} grid intent sheets ({nd_} decide), {len(docs) - ng} list sheets, {len(man['pairs'])} re-shoot pairs")
    return nd_


def score_grid(pred, gold):
    r = A.score_doc(pred, gold)
    marked = {d for d, c in gold["days"].items() if c.get("marked", True)}
    split = {"marked": Counter(), "unmarked": Counter()}
    for (day, g, p, t) in r["error_details"]:
        split["marked" if day in marked else "unmarked"][t] += 1
    r["errors_on_marked"] = sum(split["marked"].values()); r["errors_on_unmarked"] = sum(split["unmarked"].values())
    r["marked_cells"] = len(marked); r["unmarked_cells"] = len(gold["days"]) - len(marked)
    r["split"] = {k: dict(v) for k, v in split.items()}
    return r


def score_list(pred, gold):
    gset = set(gold["days"].keys())
    pdates = pred.get("dates", []) if isinstance(pred, dict) else []
    pset = {str(x).strip() for x in pdates if isinstance(pdates, list)}
    rec = len(gset & pset); fab = len(pset - gset); miss = len(gset - pset)
    return {"dates_on_page": len(gset), "recovered": rec, "fabricated": fab, "missed": miss,
            "shift_ok": (str(pred.get("shift", "")).upper() == next(iter(gold["days"].values()))["status"]) if gset and isinstance(pred, dict) else None}


def pair_diff(p1, p2):
    d1 = p1.get("days", {}) if isinstance(p1, dict) else {}; d2 = p2.get("days", {}) if isinstance(p2, dict) else {}
    days = set(d1) | set(d2); agree = 0
    for d in days:
        s1 = str((d1.get(d) or {}).get("status", "")).upper(); s2 = str((d2.get(d) or {}).get("status", "")).upper()
        agree += (s1 == s2 and s1 != "")
    n = len(days); lo, hi = A.wilson(agree, n) if n else (0, 0)
    return {"cells": n, "agree": agree, "agreement": round(agree / n, 4) if n else None, "wilson": [round(lo, 4), round(hi, 4)]}


# ------------------------------------------------------------------ synthetic baseline, in error documents
def baseline_from_file(path, arm_id=None):
    """Error documents in a model's own synthetic run. per_case.csv (v1 harness): a case is an error document if it was
    not scored (no usable answer counts against the model: conservative for B-PROCEED) or its day accuracy is below 1.
    An mmeval run directory: trial 1 of each document, same rule. Returns {"errors", "documents", "src"}."""
    if os.path.isdir(path):
        rows = [json.loads(l) for l in open(os.path.join(path, "results.jsonl"), encoding="utf-8") if l.strip()]
        rows = [r for r in rows if r.get("trial") == 1]
        identity = None
        if arm_id is not None:
            manifest = json.load(open(os.path.join(path, "manifest.json"), encoding="utf-8"))
            rows = [r for r in rows if r.get("arm_id") == arm_id]
            identities = [a for a in manifest["arms"] if a["arm_id"] == arm_id]
            expected = [c[0] for c in manifest["case_set"]["cases"]]
            if (len(identities) != 1 or manifest["data_class"] != "public_synthetic"
                    or manifest["case_set"]["id"] != "published-40" or len(expected) != 40
                    or len(rows) != 40 or sorted(r["case_id"] for r in rows) != sorted(set(expected))):
                raise ValueError("baseline must contain exactly the selected arm's 40 published synthetic trial-1 outcomes")
            identity = identities[0]
        err = sum(1 for r in rows if r["outcome"] != "scored" or r["score"]["day_accuracy"] < 1)
        result = {"errors": err, "documents": len(rows), "src": path}
        if arm_id is not None:
            result["arm_identity"] = identity
        return result
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    def bad(r):
        if str(r.get("format_validity", "")).strip().lower() not in ("true", "1", "1.0"):
            return True
        return float(r["day_accuracy"]) < 1.0
    return {"errors": sum(1 for r in rows if bad(r)), "documents": len(rows), "src": path}


def decide(per_model, families, baselines):
    """Amended Arm B rule: grid documents that decide, LEGEND-BLIND, best model by fewest error documents."""
    best = None
    for model, res in per_model.items():
        docs = [d for d in res["grid"]["blind"]["docs"] if d["decides"]]
        if not docs:
            continue
        e = sum(1 for d in docs if PD.error_document(d["errors"]))
        if best is None or e < best[1]:
            best = (model, e, len(docs))
    if best is None:
        return {"verdict": "RUN INVALID", "reason": "no scorable grid documents", "families": sorted(families)}
    model, e, n = best
    base = baselines.get(model)
    d = PD.decide_arm_b(e, n, base["errors"] if base else None, base["documents"] if base else None)
    d.update({"model": model, "baseline_src": base["src"] if base else None, "families": sorted(families),
              "minimum_needed": PD.arm_b_minimum(base["errors"], base["documents"], n) if base else None,
              "family_note": ("Single-family run: a statement about one model family only." if len(families) == 1 else "")})
    return d


# ------------------------------------------------------------------ run
def load_gold(doc):
    p = os.path.join(KIT, f"intent_{doc['doc_id']}.gold.json")
    return json.load(open(p)) if os.path.isfile(p) else None


def mock_extract(gold, n_errors, kind):
    if kind == "list":
        return {"dates": list(gold["days"].keys()), "shift": next(iter(gold["days"].values()))["status"], "notes": []}
    pred = {"month": gold["month"], "days": {d: {"status": c["status"], "note": c["note"]} for d, c in gold["days"].items()},
            "global_notes": list(gold["global_notes"])}
    for d in sorted(pred["days"])[:n_errors]:
        pred["days"][d]["status"] = "PM" if pred["days"][d]["status"] != "PM" else "AM"
    return pred


def preflight(photos, man):
    want = sorted({d["photo"] for d in man["documents"]} | {d["pair"] for d in man["documents"] if d["pair"]})
    missing = [f for f in want if not os.path.isfile(A.photo_path(photos, f))]
    if missing:
        sys.exit("PRE-FLIGHT REFUSED — expected files not found in --photos:\n  " + "\n  ".join(missing) +
                 "\nNothing was sent. Point --photos at the folder holding exactly these documents.")
    print(f"pre-flight OK: all {len(want)} expected files resolve; only these will be read.")


def run(a):
    if not a.mock and os.path.isdir(a.out) and os.listdir(a.out):
        sys.exit("REFUSED: output directory is not empty; choose a new --out to preserve earlier attempts")
    man = json.load(open(os.path.join(KIT, "MANIFEST-B.json")))
    man["documents"] = enrich(DOCS, load_private())
    man["pairs"] = [{"doc_id": d["doc_id"], "primary": d["photo"], "partner": d["pair"]} for d in man["documents"] if d.get("pair")]
    if not a.mock:
        preflight(a.photos, man)
        models = list(A.load_local_arms(a.arm_config, a.mmeval_root))
    else:
        models = a.models or ["mock-a", "mock-b"]
    families = set(models)
    baselines = dict(a.baselines or {})
    if not a.mock:
        from mmeval.config import arm_identity
        for model in models:
            if (baselines.get(model) or {}).get("arm_identity") != arm_identity(A.ARMS[model]):
                raise ValueError(f"{model}: baseline must be a complete mmeval run with this exact arm identity")
        os.makedirs(os.path.join(a.out, "raw"), exist_ok=False)

    def extract(model, image_path, doc, condition):
        raw = A.call_vision(model, None, image_path, prompt_for(doc, "blind" if condition.startswith("pair") else condition))
        with open(os.path.join(a.out, "raw", f"{doc['doc_id']}__{model}__{condition}.txt"), "x", encoding="utf-8") as f:
            f.write(raw)
        return A.parse_json(raw)
    out = {"_pre_registration": man["_pre_registration"], "models": models, "families": sorted(families), "per_model": {},
           "pairs": {}, "excluded": [], "parse_failures_counted_as_error_documents": []}
    for model in models:
        pm = {"grid": {"blind": {"docs": []}, "given": {"docs": []}}, "list": {"blind": [], "given": []}}
        k = 0
        for doc in man["documents"]:
            gold = load_gold(doc)
            if gold is None:
                if doc["doc_id"] not in out["excluded"]:
                    out["excluded"].append(doc["doc_id"])
                continue
            decides = doc["kind"] == "grid" and doc["doc_id"] not in EXCLUDED_FROM_DECISION
            for cond in ("blind", "given"):
                if a.mock:
                    n_err = 1 if (cond == "blind" and decides and k < a.error_docs) else 0
                    pred = mock_extract(gold, n_err, doc["kind"])
                    if a.parse_fail_doc == doc["doc_id"] and cond == "blind":
                        pred = None
                else:
                    img = A.photo_path(a.photos, doc["photo"])
                    pred = extract(model, img, doc, cond)
                if doc["kind"] == "grid":
                    r = score_grid(pred if pred is not None else {}, gold)
                    errs = r["cells"] if r["parse_failure"] else r["status_errors"]
                    if r["parse_failure"] and cond == "blind":
                        out["parse_failures_counted_as_error_documents"].append(f"{doc['doc_id']}/{model}")
                    pm["grid"][cond]["docs"].append({"doc": doc["doc_id"], "decides": decides, "cells": r["cells"], "errors": errs,
                                                     "parse_failure": r["parse_failure"], "types": r["status_types"],
                                                     "flips": r["critical_flips"], "on_marked": r["errors_on_marked"],
                                                     "on_unmarked": r["errors_on_unmarked"]})
                else:
                    pm["list"][cond].append({"doc": doc["doc_id"], **score_list(pred if pred is not None else {}, gold)})
            if decides:
                k += 1
        out["per_model"][model] = pm
    for pr in man["pairs"]:
        doc = next(d for d in man["documents"] if d["doc_id"] == pr["doc_id"]); gold = load_gold(doc)
        if gold is None:
            continue
        if a.mock:
            p1 = mock_extract(gold, 0, "grid"); p2 = mock_extract(gold, a.pair_errors, "grid")
        else:
            m0 = models[0]
            i1, i2 = A.photo_path(a.photos, pr["primary"]), A.photo_path(a.photos, pr["partner"])
            p1 = extract(m0, i1, doc, "pair-primary")
            p2 = extract(m0, i2, doc, "pair-partner")
        out["pairs"][pr["doc_id"]] = pair_diff(p1, p2)
    out["decision"] = decide(out["per_model"], families, baselines)
    os.makedirs(a.out, exist_ok=True)
    json.dump(out, open(os.path.join(a.out, "probe_b_results.json"), "w"), indent=2)
    write_report(out, a.out)
    if out["decision"]["verdict"] == "RUN INVALID":
        sys.exit(1)
    return out


def write_report(out, outdir):
    d = out["decision"]
    L = ["# PROBE-B-RESULTS — Arm B, real documents", "",
         f"Pre-registration: `docs/PROBE-B.md`, amended by `PROBE-AMENDMENT-01.md` and `-02.md`. Arms (local only): "
         f"{', '.join(out['models'])}.", "", f"## Verdict: **{d['verdict']}**", ""]
    if d["verdict"] != "RUN INVALID":
        L += [f"Best arm (LEGEND-BLIND, deciding grid documents, G3 excluded): `{d['model']}` — **{d['real'][0]} error documents of "
              f"{d['real'][1]}**" + (f", Wilson 95% {d['wilson_real']}" if d.get("wilson_real") else "") + ".",
              f"Synthetic baseline (same arm's own synthetic run, error documents): {d['synthetic']} from `{d.get('baseline_src')}`. "
              f"Fisher exact two-sided p: {d.get('fisher_p_two_sided')}. Minimum real error documents that would fire B-PROCEED: "
              f"{d.get('minimum_needed')}.", "",
              "*B-CLOSE is retired (Amendment 01 §3).* " + (d.get("family_note") or ""), ""]
        if d.get("reason"):
            L += [f"*{d['reason']}.*", ""]
    for m, pm in out["per_model"].items():
        L += [f"## {m}", "", "| condition | doc | decides | cells | status errors (descriptive) | error document | parse failure |",
              "|---|---|---|---|---|---|---|"]
        for c in ("blind", "given"):
            for x in pm["grid"][c]["docs"]:
                L.append(f"| LEGEND-{c.upper()} | {x['doc']} | {x['decides']} | {x['cells']} | {x['errors']} | "
                         f"{PD.error_document(x['errors'])} | {x['parse_failure']} |")
        L += ["", "Lists (descriptive, no decision branch):", "", "| condition | doc | on page | recovered | fabricated | missed |",
              "|---|---|---|---|---|---|"]
        for c in ("blind", "given"):
            for r in pm["list"][c]:
                L.append(f"| {c} | {r['doc']} | {r['dates_on_page']} | {r['recovered']} | {r['fabricated']} | {r['missed']} |")
        L.append("")
    if out["pairs"]:
        L += ["## Re-shoot pairs — same document, two photographs, no gold", "", "| doc | cells | agree | agreement | Wilson |",
              "|---|---|---|---|---|"]
        for k, v in out["pairs"].items():
            L.append(f"| {k} | {v['cells']} | {v['agree']} | {v['agreement']} | {v['wilson']} |")
        L.append("")
    if out["parse_failures_counted_as_error_documents"]:
        L += ["## Parse failures (counted as error documents)", ""] + [f"- {e}" for e in out["parse_failures_counted_as_error_documents"]] + [""]
    if out["excluded"]:
        L += ["## Excluded (no gold; stated, per PROBE-B.md §4)", ""] + [f"- {e}" for e in out["excluded"]] + [""]
    L += ["---", "*Scope: one writer; documents he kept and could locate; not a random sample. No image is published. Handwriting is biometric.*"]
    open(os.path.join(outdir, "PROBE-B-RESULTS.md"), "w", encoding="utf-8").write("\n".join(L))


# ------------------------------------------------------------------ selftest — the scorer must be able to say NO
def selftest():
    import tempfile, shutil
    global KIT
    tmp = tempfile.mkdtemp(); saved = KIT; KIT = os.path.join(tmp, "kit-B"); ok = []
    try:
        os.makedirs(KIT, exist_ok=True)
        months = ["2099-01", "2099-02", "2099-02", "2099-04", "2099-05", "2099-07", "2099-08", "2099-09", "2099-10", "2099-11", "2099-12"]
        json.dump({d["doc_id"]: {"month": m, "photo": f"X{i}.jpg", "pair": (f"Y{i}.jpg" if i in (3, 6) else None),
                                 "legend": f"synthetic legend {i}"} for i, (d, m) in enumerate(zip(DOCS, months))},
                  open(os.path.join(KIT, PRIVATE_MAP), "w"))
        n_decide = make_kit()
        for d in enrich(DOCS, load_private()):
            y, m = map(int, d["month"].split("-")); nd = calendar.monthrange(y, m)[1]
            rows = [["date", "status", "note"]]
            if d["kind"] == "grid":
                # RES-03: a LEGAL status, so the self-test needs no private alias table
                rows += [[f"{y:04d}-{m:02d}-{i+1:02d}", ("NIGHT" if i % 3 == 0 else ""), ""] for i in range(nd)]
                rows += [["DEFAULT_STATUS", "AVAILABLE", ""]]
            else:
                rows += [[f"{y:04d}-{m:02d}-{i+1:02d}", "NIGHT", ""] for i in range(0, nd, 4)]
            g, bad = build_gold(rows, d["doc_id"])
            if bad:
                raise AssertionError((d["doc_id"], bad))
            json.dump(g, open(os.path.join(KIT, f"intent_{d['doc_id']}.gold.json"), "w"))

        class Args:
            pass

        def go(error_docs, models, baselines=None, pair_errors=0, parse_fail_doc=None):
            a = Args(); a.mock = True; a.error_docs = error_docs; a.models = models; a.photos = ""; a.pair_errors = pair_errors
            a.out = os.path.join(tmp, f"out_{error_docs}_{len(models)}_{pair_errors}_{parse_fail_doc}"); a.baselines = baselines
            a.parse_fail_doc = parse_fail_doc
            return run(a)
        zero = {"mock-a": {"errors": 0, "documents": 40, "src": "synthetic 0/40"},
                "mock-b": {"errors": 0, "documents": 40, "src": "synthetic 0/40"}}
        nine = {"mock-a": {"errors": 9, "documents": 40, "src": "synthetic 9/40"},
                "mock-b": {"errors": 9, "documents": 40, "src": "synthetic 9/40"}}
        ok.append(("T0 RES-03: the self-test builds every gold in a clean room (no private map, no private alias)", True))
        ok.append(("T1 6 grid documents decide; G3 excluded", n_decide == 6))
        o = go(0, ["mock-a", "mock-b"], zero)
        rep = open(os.path.join(tmp, "out_0_2_0_None", "PROBE-B-RESULTS.md"), encoding="utf-8").read()
        ok.append(("T2 0 error documents -> B-CONTINUE; B-CLOSE never fires and is stated as retired",
                   o["decision"]["verdict"] == "B-CONTINUE" and "Verdict: **B-CLOSE**" not in rep and "B-CLOSE is retired" in rep))
        o = go(2, ["mock-a", "mock-b"], zero)
        ok.append(("T3 2 of 6 vs 0/40 -> B-PROCEED (the minimum)", o["decision"]["verdict"] == "B-PROCEED" and o["decision"]["real"] == [2, 6]))
        o = go(1, ["mock-a", "mock-b"], zero)
        ok.append(("T4 1 of 6 vs 0/40 -> B-CONTINUE", o["decision"]["verdict"] == "B-CONTINUE"))
        o = go(4, ["mock-a", "mock-b"], nine)
        ok.append(("T5 4 of 6 vs 9/40 -> B-PROCEED; 3 of 6 -> B-CONTINUE",
                   o["decision"]["verdict"] == "B-PROCEED" and go(3, ["mock-a", "mock-b"], nine)["decision"]["verdict"] == "B-CONTINUE"))
        o = go(6, ["mock-a", "mock-b"], None)
        ok.append(("T6 no synthetic baseline on file -> cannot proceed (fails closed)", o["decision"]["verdict"] == "B-CONTINUE"
                   and o["decision"]["synthetic"] is None))
        o = go(0, ["mock-a"], zero)
        ok.append(("T7 a single-arm run says it describes one family", "Single-family" in o["decision"]["family_note"]))
        o = go(1, ["mock-a", "mock-b"], zero, parse_fail_doc="G4")
        ok.append(("T8 a parse failure on a deciding document counts as an error document and is listed",
                   o["decision"]["real"] == [2, 6] and "G4/mock-a" in o["parse_failures_counted_as_error_documents"]))
        o = go(0, ["mock-a", "mock-b"], zero, parse_fail_doc="G3")
        ok.append(("T9 G3 is scored and reported but never enters the decision",
                   o["decision"]["real"] == [0, 6] and any(x["doc"] == "G3" for x in o["per_model"]["mock-a"]["grid"]["blind"]["docs"])))
        o = go(0, ["mock-a", "mock-b"], zero, pair_errors=5); pr = next(iter(o["pairs"].values()))
        ok.append(("T10 pair diff sees 5 planted disagreements", pr["cells"] - pr["agree"] == 5))
        gl = json.load(open(os.path.join(KIT, "intent_F4.gold.json")))
        r = score_list({"dates": list(gl["days"].keys()) + ["2025-09-31"], "shift": "NIGHT"}, gl)
        ok.append(("T11 list scorer counts an invented date as fabricated", r["fabricated"] == 1 and r["missed"] == 0))
        d0 = enrich(DOCS, load_private())[5]
        ok.append(("T12 BLIND prompt withholds the legend, GIVEN includes it",
                   d0["legend"] not in prompt_for(d0, "blind") and d0["legend"] in prompt_for(d0, "given")))
        gold = json.load(open(os.path.join(KIT, "intent_G6.gold.json")))
        pred = {"month": gold["month"], "days": {d: {"status": c["status"], "note": ""} for d, c in gold["days"].items()}, "global_notes": []}
        pred["days"][sorted(gold["days"])[1]]["status"] = "PM"
        r = score_grid(pred, gold)
        ok.append(("T13 an error on a blank cell is typed 'unmarked'", r["errors_on_unmarked"] == 1 and r["errors_on_marked"] == 0))
        hidden = os.path.join(KIT, "intent_G6.gold.json"); bak = hidden + ".bak"; os.rename(hidden, bak)
        try:
            o = go(0, ["mock-a", "mock-b"], zero)
            ok.append(("T14 a missing gold file EXCLUDES and does not crash on model 2", "G6" in o["excluded"]))
        finally:
            os.rename(bak, hidden)
        csvp = os.path.join(tmp, "per_case.csv")
        with open(csvp, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["case", "format_validity", "day_accuracy"])
            w.writerows([["c1", "True", "1.0"], ["c2", "True", "0.9677"], ["c3", "False", ""], ["c4", "True", "1.0"]])
        b = baseline_from_file(csvp)
        ok.append(("T15 baseline from per_case.csv counts error documents, an unusable case counting as one",
                   b["errors"] == 2 and b["documents"] == 4))
        for name, path, want in (("claude-sonnet-5", os.path.join(REPO, "results", "per_case.csv"), 0),
                                 ("claude-haiku-4-5", os.path.join(REPO, "results_haiku", "per_case.csv"), 9)):
            if os.path.isfile(path):
                ok.append((f"T16 published {name} synthetic run: {want}/40 error documents (Amendment 01 §3)",
                           baseline_from_file(path) == {"errors": want, "documents": 40, "src": path}))
    finally:
        KIT = saved; shutil.rmtree(tmp, ignore_errors=True)
    for name, res in ok:
        print(f"  {name:100} -> {'PASS' if res else 'FAIL'}")
    if all(r for _, r in ok):
        print(f"\nPROBE-B SELFTEST PASS — {len(ok)}/{len(ok)}."); return 0
    print("\nPROBE-B SELFTEST FAIL"); return 1


def _baseline_arg(s):
    arm, path = s.split("=", 1)
    return arm, baseline_from_file(path, arm_id=arm)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-kit", action="store_true"); ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mock", action="store_true"); ap.add_argument("--error-docs", type=int, default=0)
    ap.add_argument("--pair-errors", type=int, default=0); ap.add_argument("--parse-fail-doc", default=None)
    ap.add_argument("--photos", default=""); ap.add_argument("--models", nargs="*", default=[])
    ap.add_argument("--arm-config"); ap.add_argument("--mmeval-root", default=REPO)
    ap.add_argument("--baseline", dest="baselines", action="append", type=_baseline_arg, default=[])
    ap.add_argument("--out", default="./probe_b_results")
    ap.add_argument("--amendment-02-frozen", dest="a02", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.make_kit:
        make_kit(); sys.exit(0)
    if not a.mock and not (a.arm_config and a.a02):
        sys.exit("REFUSING TO SCORE: a real run needs --arm-config (validated local arms) and --amendment-02-frozen, "
                 "asserted only once PROBE-AMENDMENT-02 is frozen and published. Nothing was sent.")
    run(a)
