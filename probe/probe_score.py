#!/usr/bin/env python3
"""probe_score.py — Arm A of the probe, scored with a TYPED error classifier.  CANDIDATE A02-r1 (2026-10-26).

Changes from the 2026-09-12 file (ed-eval-probe/probe_score.py, sha256 2d1d8f4c…, preserved unchanged there):
  * decisions are made at the DOCUMENT level by probe_decide.decide_arm_a (docs/PROBE-AMENDMENT-01.md §4);
    cell counts are reported as descriptive statistics and decide nothing
  * CLOSE is retired: no code path can print it
  * Stage 1 (3 documents per arm) is a PILOT and prints no verdict
  * photographs are scored ONLY by a LOCAL vision model (founder ruling D-1, Amendment 01 §4b; PROBE-AMENDMENT-02):
    the cloud adapters are removed, and an arm must be a validated local mmeval arm that allows private_local_only data
  * a single-family run is stated as such (the Claude-only lockout now gates no branch; Amendment 01 §4)
  * PROCEED no longer instructs recruiting twelve writers: that corpus is closed by ruling R-3
  * JSON parsing rejects conflicting duplicate keys and NaN/Infinity, as the v1 harness does since r4

Usage (on the machine that holds the photos and runs the local model):
    python3 probe_score.py --kit ./kit --photos ./photos --arm-config <local arms .json> --mmeval-root <repo> [--out ./probe_results]
    python3 probe_score.py --selftest          # the cell classifier and the document-level rules; no model, no images

Photos: JPG or PNG named by doc_id (A-copy-1.jpg, B-auth-2.jpg, ...). Phone photo, normal light, not flatbed.
Gold:   kit/spec_<doc>.gold.json for copyist docs; kit/intent_<doc>.gold.json for authored docs (made by intent_to_gold.py).

Typed status errors (per cell, descriptive):
    OK · CRITICAL_FLIP (gold UNAVAILABLE, predicted available) · DISPLACED (equals an adjacent cell's gold) · MISREAD · MISSING
Typed note errors: NOTE_OK · NOTE_OMISSION · NOTE_DISPLACED · NOTE_FABRICATED

Decision rule of record (Amendment 01 §4, Arm A): PROCEED when the two-sided Fisher exact test on error documents per arm
gives p < 0.05, authored > copyist, and the two Wilson 95% intervals do not overlap; CONTINUE otherwise. A document is an
error document if it has at least one status error. Documents whose month is misread or with more than half the cells
MISSING are parse failures and are excluded from the decision and listed (PROBE.md, unchanged).
"""
import os, sys, io, json, re, math, base64, argparse, datetime, warnings
from pathlib import Path
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # shared validation is available to standalone selftests and kit commands
sys.path.insert(0, HERE)
import probe_decide as PD  # noqa: E402

LEGAL = {"AVAILABLE", "AM", "PM", "NIGHT", "UNAVAILABLE"}
AVAILABLE_KINDS = {"AVAILABLE", "AM", "PM", "NIGHT"}
TASK_PROMPT = (
    'This image is a filled-in monthly staff availability calendar. '
    'Legend: ✓=available any shift, AM, PM, NOC=night shift, X=unavailable. '
    'Extract it to JSON with exactly this schema: '
    '{"month": "YYYY-MM", "days": {"YYYY-MM-DD": {"status": "AVAILABLE|AM|PM|NIGHT|UNAVAILABLE", "note": ""}}, '
    '"global_notes": []}. Every day of the month must appear. NOC maps to NIGHT; ✓ maps to AVAILABLE; '
    'X maps to UNAVAILABLE. Transcribe notes exactly as written; do not invent notes. Output ONLY the JSON.'
)
RETRY_SUFFIX = " Your previous output was not valid JSON. Output ONLY a single valid JSON object, no prose, no code fences."
wilson, fisher_2x2 = PD.wilson, PD.fisher_2x2          # one implementation, shared with Arm B


# ---------------------------------------------------------------- the local route (D-1; Amendment 02)
ARMS = {}             # arm_id -> validated local arm, filled by load_local_arms()
TRUSTED = ()
CALLS = Counter()
MAX_PHOTO_BYTES = 32 * 1024 * 1024
MAX_PHOTO_PIXELS = 40_000_000


def photo_name(name):
    """A private map names one JPEG/PNG within --photos, never an arbitrary path."""
    if (not isinstance(name, str) or len(name) > 255 or name in ("", ".", "..")
            or any(c in name for c in '/\\:*?"<>|') or any(ord(c) < 32 for c in name)
            or Path(name).suffix.lower() not in (".jpg", ".jpeg", ".png")):
        raise ValueError("photo must be a single JPEG or PNG filename within --photos")
    return name


def photo_path(directory, name):
    base = Path(directory).resolve()
    path = (base / photo_name(name)).resolve()
    if not path.is_relative_to(base):
        raise ValueError("photo resolves outside --photos; linked external files are refused")
    return str(path)


def load_local_arms(path, mmeval_root):
    """Every arm must validate for dispatch with data class private_local_only. mmeval refuses that data class on
    any cloud arm, refuses a non-loopback endpoint for a local arm unless it is listed as trusted, and has no
    fallback field. Nothing is sent here."""
    global ARMS, TRUSTED, CALLS
    ARMS, TRUSTED, CALLS = {}, (), Counter()
    sys.path.insert(0, mmeval_root)
    from mmeval import config as C
    cfg = C.load_config(path)
    TRUSTED = tuple(cfg.get("trusted_local_hosts") or [])
    out = {}
    for a in cfg["arms"]:
        v = C.validate_arm(a, task_needs_image=True, data_class="private_local_only", trusted_local_hosts=TRUSTED,
                           for_dispatch=True)
        if v["route"] != "local":
            sys.exit(f"REFUSED: {v['arm_id']} is not a local arm; photographed documents are scored locally only (D-1)")
        out[v["arm_id"]] = v
    if (cfg.get("dispatch") or {}).get("enabled") is not True:
        raise C.ConfigError("probe dispatch.enabled must be true before a real run")
    ARMS = out
    return out


def load_image_b64(path, max_side=2000):
    """Phone photos are 3-4k px; downscale to <=max_side and send as JPEG. Returns (b64, media_type)."""
    from PIL import Image, ImageOps
    if os.path.getsize(path) > MAX_PHOTO_BYTES:
        raise ValueError("photo file size exceeds 32 MiB limit")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path, formats=("JPEG", "PNG")) as original:
            if original.width * original.height > MAX_PHOTO_PIXELS:
                raise ValueError("photo pixel count exceeds 40 million limit")
            im = ImageOps.exif_transpose(original).convert("RGB")  # honour phone rotation metadata
    if im.width > im.height:
        print(f"WARNING: {os.path.basename(path)} is LANDSCAPE after EXIF correction; the forms are portrait. The image is being sent sideways — rotate it and re-run.")
    if max(im.size) > max_side:
        s = max_side / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)))
    buf = io.BytesIO(); im.save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def call_vision(model, key, img_path, prompt):
    """The local arm selects its optional credential environment variable; the legacy key argument is unused."""
    arm = ARMS.get(model)
    if arm is None:
        sys.exit(f"REFUSED: no validated local arm named {model!r}. Photographed documents are scored only by a local "
                 "vision model (D-1; PROBE-AMENDMENT-01 §4b). Pass --arm-config. Nothing was sent.")
    credential = os.environ.get(arm.get("credential_env") or "")
    if arm.get("credential_env") and not credential:
        raise RuntimeError(f"{model}: credential variable {arm['credential_env']} is not set; nothing was sent")
    if CALLS[model] >= arm["limits"]["max_calls"]:
        raise RuntimeError(f"{model}: local probe call limit reached; nothing was sent")
    from mmeval.adapters import build_request, parse_response
    from mmeval.transport import HttpTransport
    b64, mt = load_image_b64(img_path)
    url, headers, payload = build_request(arm, base64.b64decode(b64), mt, prompt, credential=credential)
    CALLS[model] += 1
    resp = HttpTransport(trusted_local_hosts=TRUSTED).send(arm, url, headers, payload, arm["limits"]["timeout_s"])
    parsed = parse_response(arm, resp["json"])
    if parsed["finish"] == "length":
        raise RuntimeError(f"{model}: answer truncated at the output limit")
    return parsed["text"]


class _Rejected(ValueError):
    pass


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out and out[k] != v:
            raise _Rejected(f"conflicting duplicate field {k!r}")
        out[k] = v
    return out


def _strict(s):
    return json.loads(s, object_pairs_hook=_pairs, parse_constant=lambda t: (_ for _ in ()).throw(_Rejected(t)))


def parse_json(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.MULTILINE).strip()
    try:
        return _strict(t)
    except (ValueError, RecursionError):
        m = re.search(r"\{.*\}", t, flags=re.DOTALL)
        if m:
            try:
                return _strict(m.group(0))
            except (ValueError, RecursionError):
                return None
    return None


# ---------------------------------------------------------------- typed scoring (unchanged from 2026-09-12)
def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def neighbours(day_iso, gold_days):
    d = datetime.date.fromisoformat(day_iso)
    out = []
    for delta in (-1, 1, -7, 7):
        k = (d + datetime.timedelta(days=delta)).isoformat()
        if k in gold_days:
            out.append(k)
    return out


def score_doc(pred, gold):
    gd = gold["days"]
    pd_ = pred.get("days", {}) if isinstance(pred, dict) else {}
    if not isinstance(pd_, dict):
        pd_ = {}
    month_mismatch = isinstance(pred, dict) and pred.get("month") not in (None, gold["month"])
    page_notes = {norm(c["note"]) for c in gd.values() if c["note"]} | {norm(g) for g in gold.get("global_notes", [])}
    status_types, note_types, details = Counter(), Counter(), []
    gold_g = [norm(g) for g in gold.get("global_notes", []) if norm(g)]
    pred_g_raw = pred.get("global_notes", []) if isinstance(pred, dict) else []
    pred_g = [norm(x) for x in (pred_g_raw if isinstance(pred_g_raw, list) else []) if norm(x)]
    for g in gold_g:
        note_types["NOTE_OK" if g in pred_g else "NOTE_OMISSION"] += 1
    for p in pred_g:
        if p not in gold_g:
            note_types["NOTE_DISPLACED" if p in page_notes else "NOTE_FABRICATED"] += 1
    for day, g in gd.items():
        p = pd_.get(day)
        ps_raw = p.get("status") if isinstance(p, dict) else None
        ps = str(ps_raw).strip().upper() if ps_raw is not None else None
        if ps not in LEGAL:
            status_types["MISSING"] += 1; details.append((day, g["status"], ps_raw, "MISSING")); continue
        if ps == g["status"]:
            t = "OK"
        elif g["status"] == "UNAVAILABLE" and ps in AVAILABLE_KINDS:
            t = "CRITICAL_FLIP"
        elif any(gd[n]["status"] == ps for n in neighbours(day, gd)):
            t = "DISPLACED"
        else:
            t = "MISREAD"
        status_types[t] += 1
        if t != "OK":
            details.append((day, g["status"], ps, t))
        gn, pn = norm(g["note"]), norm(p.get("note"))
        if gn and pn == gn:
            note_types["NOTE_OK"] += 1
        elif gn and not pn:
            note_types["NOTE_OMISSION"] += 1
        elif pn and pn != gn:
            note_types["NOTE_DISPLACED" if pn in page_notes else "NOTE_FABRICATED"] += 1
    n = len(gd)
    err = n - status_types["OK"]
    floors = []
    for day, g in gd.items():
        nb = {gd[k]["status"] for k in neighbours(day, gd)} - {g["status"]}
        floors.append(len(nb) / 4.0)
    disp_floor = sum(floors) / len(floors) if floors else 0.0
    parse_failure = month_mismatch or (status_types["MISSING"] > n / 2)
    return {"cells": n, "status_errors": err, "status_types": dict(status_types),
            "parse_failure": parse_failure, "month_mismatch": month_mismatch,
            "displaced_chance_floor": round(disp_floor, 3),
            "critical_flips": status_types["CRITICAL_FLIP"], "gold_unavailable": sum(1 for c in gd.values() if c["status"] == "UNAVAILABLE"),
            "note_types": dict(note_types), "error_details": details}


# ---------------------------------------------------------------- self-test (positive controls)
def selftest():
    print("SELF-TEST — the cell classifier, then the document-level rules (probe_decide).")
    gold = {"month": "2026-10", "global_notes": ["No weekends"], "days": {}}
    st = ["AM", "AM", "PM", "UNAVAILABLE", "AVAILABLE", "NIGHT", "UNAVAILABLE", "PM"] * 4
    for i in range(31):
        gold["days"][f"2026-10-{i + 1:02d}"] = {"status": st[i], "note": "charge only" if i == 6 else ""}
    clean = score_doc(json.loads(json.dumps(gold)), gold)
    ok0 = clean["status_errors"] == 0 and clean["note_types"].get("NOTE_OK") == 2 and not clean["parse_failure"]
    pred = json.loads(json.dumps(gold))
    pred["days"]["2026-10-04"]["status"] = "AM"
    pred["days"]["2026-10-02"]["status"] = "PM"
    pred["days"]["2026-10-01"]["status"] = "NIGHT"
    del pred["days"]["2026-10-31"]
    pred["days"]["2026-10-10"]["note"] = "float OK"
    pred["days"]["2026-10-11"]["note"] = "charge only"
    pred["days"]["2026-10-07"]["note"] = ""
    pred["global_notes"] = ["Prefer ICU"]
    r = score_doc(pred, gold)
    exp = {"CRITICAL_FLIP": 1, "DISPLACED": 1, "MISREAD": 1, "MISSING": 1}
    got = {k: r["status_types"].get(k, 0) for k in exp}
    expn = {"NOTE_FABRICATED": 2, "NOTE_DISPLACED": 1, "NOTE_OMISSION": 2}
    gotn = {k: r["note_types"].get(k, 0) for k in expn}
    ok1 = got == exp and gotn == expn and r["status_errors"] == 4
    pf1 = score_doc({"month": "2026-11", "days": json.loads(json.dumps(gold))["days"]}, gold)["parse_failure"]
    pf2 = score_doc({"month": "2026-10", "days": None}, gold)["parse_failure"]
    ok1 = ok1 and pf1 and pf2
    ok2 = parse_json('{"month": "2026-10", "month": "2026-11"}') is None and parse_json('{"x": NaN}') is None
    print(f"  gold-as-prediction: {clean['status_errors']} status errors   -> {'PASS' if ok0 else 'FAIL'}")
    print(f"  injected: status {got}; notes {gotn}; parse-failure guard {pf1}/{pf2}   -> {'PASS' if ok1 else 'FAIL'}")
    print(f"  strict JSON: conflicting duplicate key and NaN rejected   -> {'PASS' if ok2 else 'FAIL'}")
    ok3 = PD.selftest() == 0
    if ok0 and ok1 and ok2 and ok3:
        print("SELF-TEST PASS — the checks can fail, and they did not.")
        return 0
    print("*** SELF-TEST FAIL — do not use this scorer. ***")
    return 2


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default="./kit"); ap.add_argument("--photos", default="./photos")
    ap.add_argument("--models", default="", help="test doubles only; a real run names its arms in --arm-config")
    ap.add_argument("--arm-config"); ap.add_argument("--mmeval-root", default=os.path.dirname(HERE))
    ap.add_argument("--out", default="./probe_results")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--amendment-02-frozen", dest="a02", action="store_true",
                    help="The founder asserts that docs/PROBE-AMENDMENT-02.md is frozen and published. Required for a real run.")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if selftest() != 0:
        sys.exit("Refusing to run: the scorer's own positive control failed.")
    if a.arm_config and not a.a02:
        sys.exit("REFUSING TO SCORE: PROBE-AMENDMENT-02 (local route, synthetic baseline) must be frozen and published before "
                 "any probe image is scored (D-1; Amendment 01 §4b). Pass --amendment-02-frozen only when that is true.")
    if a.arm_config:
        if os.path.isdir(a.out) and os.listdir(a.out):
            sys.exit("REFUSED: output directory is not empty; choose a new --out to preserve earlier attempts")
        models = list(load_local_arms(a.arm_config, a.mmeval_root))
    else:
        models = [m.strip() for m in a.models.split(",") if m.strip()]
    if not models:
        sys.exit("No arms: pass --arm-config with validated local arms. Nothing was sent.")
    man = json.load(open(os.path.join(a.kit, "MANIFEST.json")))
    from mmeval.config import safe_identifier
    if not all(safe_identifier(d.get("doc_id")) for d in man["documents"]) or not all(safe_identifier(m) for m in models):
        raise ValueError("document and arm IDs must be portable filename identifiers")
    if len({d["doc_id"] for d in man["documents"]}) != len(man["documents"]):
        raise ValueError("duplicate document ID in probe manifest")
    per_arm = Counter(d["condition"] for d in man["documents"])
    stage = 2 if min(per_arm.get("copy", 0), per_arm.get("auth", 0)) >= 7 else 1
    os.makedirs(os.path.join(a.out, "raw"), exist_ok=True)

    results = []
    for doc in man["documents"]:
        did = doc["doc_id"]
        photo = next((photo_path(a.photos, did + ext) for ext in (".jpg", ".jpeg", ".png", ".JPG", ".PNG")
                      if os.path.exists(photo_path(a.photos, did + ext))), None)
        gold_path = os.path.join(a.kit, f"spec_{did}.gold.json" if doc["condition"] == "copy" else f"intent_{did}.gold.json")
        if not photo or not os.path.exists(gold_path):
            print(f"SKIP {did}: {'no photo' if not photo else 'no gold (run intent_to_gold.py first)'}"); continue
        gold = json.load(open(gold_path))
        for m in models:
            raw = call_vision(m, None, photo, TASK_PROMPT)
            open(os.path.join(a.out, "raw", f"{did}__{m}__attempt1.txt"), "x", encoding="utf-8").write(raw)
            pred = parse_json(raw); retried = False
            if pred is None:
                raw = call_vision(m, None, photo, TASK_PROMPT + RETRY_SUFFIX)
                open(os.path.join(a.out, "raw", f"{did}__{m}__attempt2.txt"), "x", encoding="utf-8").write(raw)
                pred = parse_json(raw); retried = True
            open(os.path.join(a.out, "raw", f"{did}__{m}.txt"), "w", encoding="utf-8").write(raw)
            s = score_doc(pred if pred is not None else {}, gold)
            s.update({"doc_id": did, "condition": {"copy": "copyist", "auth": "authored"}.get(doc["condition"], doc["condition"]),
                      "geometry": doc["geometry"], "model": m, "retried": retried, "parsed": pred is not None})
            results.append(s)
            print(f"{did:10s} {m:22s} cells={s['cells']:3d} errors={s['status_errors']:3d} flips={s['critical_flips']} types={s['status_types']}")

    flagged = [r for r in results if r.get("parse_failure")]
    for r in flagged:
        print(f"PARSE FAILURE excluded from the decision: {r['doc_id']} / {r['model']} "
              f"({'month mismatch' if r['month_mismatch'] else 'more than half the cells MISSING'})")
    agg = defaultdict(lambda: {"docs": 0, "error_docs": 0, "cells": 0, "errors": 0, "flips": 0, "gold_unavail": 0,
                               "types": Counter()})
    for r in results:
        if r.get("parse_failure"):
            continue
        g = agg[(r["model"], r["condition"])]
        g["docs"] += 1; g["error_docs"] += int(PD.error_document(r["status_errors"]))
        g["cells"] += r["cells"]; g["errors"] += r["status_errors"]; g["flips"] += r["critical_flips"]
        g["gold_unavail"] += r["gold_unavailable"]; g["types"].update(r["status_types"])
    families = sorted(set(models))
    lines = ["# Probe results — Arm A, authoring conditions", "",
             f"Arms (local only): {models}. Stage {stage}" + (" (pilot)" if stage == 1 else "") + ".", "",
             f"*{'Single-family run: these results describe one model family only.' if len(families) == 1 else 'Families: ' + ', '.join(families) + '.'}*", "",
             "| arm | condition | documents | error documents | Wilson 95% (documents) | cells (descriptive) | status errors (descriptive) | critical flips / gold-UNAVAIL |",
             "|---|---|---|---|---|---|---|---|"]
    best = None
    for m in models:
        row = {}
        for cond in ("copyist", "authored", "real"):
            g = agg.get((m, cond))
            if not g or g["docs"] == 0:
                continue
            lo, hi = wilson(g["error_docs"], g["docs"])
            row[cond] = g
            lines.append(f"| {m} | {cond} | {g['docs']} | {g['error_docs']} | [{100*lo:.1f}%, {100*hi:.1f}%] | {g['cells']} | "
                         f"{g['errors']} | {g['flips']} / {g['gold_unavail']} |")
        if "copyist" in row and "authored" in row:
            key = row["authored"]["error_docs"] / row["authored"]["docs"]
            if best is None or key < best[1]:
                best = (m, key)
    lines.append("")
    if not best:
        lines += ["## RUN INVALID — no verdict", "",
                  "No arm has BOTH a scored copyist arm and a scored authored arm. Causes: photos missing or misnamed, intent gold not "
                  "built, every document flagged as a parse failure, or no arm ran. **Nothing here can be acted on.**"]
        open(os.path.join(a.out, "PROBE-RESULTS.md"), "w", encoding="utf-8").write("\n".join(lines))
        print("\n".join(lines)); print("\n*** RUN INVALID — no verdict. Exit 1. ***"); sys.exit(1)
    m = best[0]
    ga, gc = agg[(m, "authored")], agg[(m, "copyist")]
    d = PD.decide_arm_a(ga["error_docs"], ga["docs"], gc["error_docs"], gc["docs"], stage)
    if stage == 1:
        verdict = f"**PILOT — no verdict.** {d['label']} Stage 2 writes four more documents per condition, same protocol."
    elif d["verdict"] == "PROCEED":
        verdict = ("**PROCEED** — an authoring effect is detectable at the document level at this scale. What follows is a "
                   "founder decision; the twelve-writer corpus remains closed by ruling R-3.")
    else:
        verdict = "**CONTINUE** — the data did not decide. No authoring effect is demonstrated at this sample size."
    lines += [f"## Decision against the amended rule (Amendment 01 §4; best arm on authored: {m})", "",
              "| quantity | value | threshold |", "|---|---|---|",
              f"| authored error documents | {ga['error_docs']}/{ga['docs']}, Wilson {d['wilson_authored']} | |",
              f"| copyist error documents | {gc['error_docs']}/{gc['docs']}, Wilson {d['wilson_copyist']} | |",
              f"| Fisher exact, two-sided, on error documents | p = {d['fisher_p_two_sided']} | p < 0.05, authored > copyist |",
              f"| Wilson intervals overlap | {d['intervals_overlap']} | must not overlap |", "",
              verdict, "",
              "*CLOSE is retired (Amendment 01 §3): it needs 189 documents per arm and cannot be reached by one writer.*", "",
              (f"*{len(flagged)} document(s) excluded as parse failures: {', '.join(r['doc_id'] + '/' + r['model'] for r in flagged)}.*"
               if flagged else "*No parse failures.*"), "",
              "*Cell counts are descriptive only. n = 1 writer bounds everything.*"]
    lines.append("")
    open(os.path.join(a.out, "PROBE-RESULTS.md"), "w", encoding="utf-8").write("\n".join(lines))
    json.dump({"arms": models, "stage": stage, "decision": d, "per_doc": results}, open(os.path.join(a.out, "probe_results.json"), "w"),
              indent=2, default=str)
    print("\n".join(lines))
    print(f"\nwrote {a.out}/PROBE-RESULTS.md, probe_results.json, raw/")


if __name__ == "__main__":
    main()
