"""Reports for multi-model runs (candidate r6).

Three blocks per arm, never merged:
  1. ACCOUNTING   every planned unit: scored, invalid, truncated, refused, unavailable, route_denied, unrun.
                  unusable_rate = (planned - scored) / planned. This is the intention-to-treat denominator.
  2. HISTORIC     run_eval.aggregate(), unchanged, over units that produced a model answer (scored + invalid),
                  exactly as the v1 harness reported them. Its rates are CONDITIONAL: they describe answers
                  that were obtained, and say nothing about units that produced none.
  3. EXTENDED     new in r6, labelled as new: false unavailability, status errors, note omissions, constant
                  output, document-level success (ITT), repeated-run variability, per-slice.
Paired comparisons are document-level: each document is one unit of analysis, trials are averaged
within a document first. A seeded bootstrap CI and an exact sign test are reported, with Holm's adjustment
across the contrasts named in the protocol. With 40 documents these are small-sample estimates.

Degenerate-output guard: an arm whose critical-error rate is 0 while it marks most available days
UNAVAILABLE, or emits one status for a whole month, is flagged DEGENERATE. A zero critical-error rate is
then not evidence of safety: marking everything unavailable can never flip an unavailable day.
"""
import json, math, os, random, statistics

from .runner import OUTCOMES, RunDir, RunRefused, plan_units

AVAILABLE_KINDS = {"AVAILABLE", "AM", "PM", "NIGHT"}
DEGENERATE_FALSE_UNAVAILABLE = 0.5


class ReportRefused(RunRefused):
    """Metrics would not be authoritative (r7: REC-11, ACC-08, REC-13). Nothing is dropped to make them so."""


def load_run(run_dir):
    rd = RunDir(run_dir)
    manifest = json.load(open(os.path.join(run_dir, "manifest.json"), encoding="utf-8"))
    if manifest.get("legacy"):
        arm = manifest["arms"][0]["arm_id"]
        planned = [f"{arm}/{c[0]}/t1" for c in manifest["case_set"]["cases"]]
    else:
        planned = [u["unit_id"] for u in plan_units(manifest)]
    results = rd.results()
    plan, counts = set(planned), {}
    for r in results:
        counts[r["unit_id"]] = counts.get(r["unit_id"], 0) + 1
    dups = sorted(u for u, k in counts.items() if k > 1)
    foreign = sorted(u for u in counts if u not in plan)
    if dups or foreign:
        raise ReportRefused(f"{run_dir} (run {manifest.get('manifest_hash', '?')[:12]}): duplicate outcome rows {dups}; "
                            f"out-of-plan rows (not in the plan) {foreign}. No metrics were produced; the ledger is "
                            "kept as found")
    return {"manifest": manifest, "results": results, "attempts": rd.attempts(), "planned": planned, "dir": run_dir}


def case_extended(pred_statuses, gold, score):
    g = gold["days"]
    st_err = sum(1 for d, c in g.items() if pred_statuses.get(d) != c["status"])
    g_av = [d for d, c in g.items() if c["status"] in AVAILABLE_KINDS]
    false_unav = sum(1 for d in g_av if pred_statuses.get(d) == "UNAVAILABLE")
    flips = len(score["critical_flips"])
    return {"status_errors": st_err, "gold_days": len(g), "gold_available_days": len(g_av),
            "false_unavailable_days": false_unav, "dangerous_flips": flips,
            "constant_status_output": len(set(pred_statuses.values())) == 1,
            "note_omissions": score["gold_notes"] - score["captured_notes"],
            "doc_status_exact": st_err == 0, "doc_success": st_err == 0 and flips == 0}


def _rate(num, den):
    return (num / den) if den else None


def _rate_denominator_sentences(arm_id, historic, ext_rows, repetition_block):
    """r7.2: a plain-English denominator sentence for EVERY rate in the arm summary, keyed by dotted path.

    Each sentence states what the code that computes the rate actually divides by: case_extended()/pooled()
    and run_eval.aggregate() in this tree. Only paths whose rate is present in the summary are emitted.
    """
    d = {}
    d["accounting.unusable_rate"] = (
        "all planned units of arm " + str(arm_id)
        + ": every unit the plan called for, scored and unscored alike")
    d["extended.status_error_rate"] = (
        "gold calendar days summed over the scored units of this arm")
    d["extended.false_unavailable_rate"] = (
        "gold available days (days whose gold status is not UNAVAILABLE) summed over the scored units of this arm")
    d["extended.doc_status_exact_rate_conditional"] = (
        "scored units only: conditional on a scored answer, each scored unit counts once")
    d["extended.doc_success_rate_itt"] = (
        "all planned units of this arm, intention to treat: units that were never run or never "
        "scored count as failures")
    if historic is not None:
        d["historic_conditional.day_accuracy"] = (
            "gold calendar days summed over the answered units that passed schema validation "
            "(the scored units); invalid answers are excluded, so it is conditional on an answer "
            "that parsed and validated")
        d["historic_conditional.critical_error_rate"] = (
            "gold UNAVAILABLE days summed over the scored units of this arm")
        d["historic_conditional.note_mismatch_rate"] = (
            "predicted notes summed over the scored units: day-cell notes with non-empty text plus "
            "distinct non-empty global notes; units that predicted no notes at all are excluded")
        d["historic_conditional.hallucination_rate"] = (
            "the same predicted-note total as note_mismatch_rate: day-cell notes with non-empty "
            "text plus distinct non-empty global notes, summed over the scored units")
        d["historic_conditional.note_fidelity"] = (
            "gold notes summed over the scored units: day notes with non-empty text plus every "
            "global note of the gold calendar")
        d["historic_conditional.format_validity"] = (
            "the answered units: scored and invalid units (a model answer, whether or not it validated); refused, "
            "truncated, unavailable, route-denied and unrun units are excluded")
    for s in sorted({x["slice"] for x in ext_rows}):
        for k, sent in (
                ("status_error_rate",
                 "gold calendar days summed over the scored units of slice " + str(s)),
                ("false_unavailable_rate",
                 "gold available days (days whose gold status is not UNAVAILABLE) summed over the "
                 "scored units of slice " + str(s)),
                ("doc_status_exact_rate_conditional",
                 "the scored units of slice " + str(s)
                 + " only: conditional on a scored answer, each counts once")):
            d["extended.per_slice." + str(s) + "." + k] = sent
    rep = repetition_block if isinstance(repetition_block, dict) else None
    if rep is not None and rep.get("cases_with_2plus_scored_trials"):
        d["extended.repetition.mean_fraction_of_days_where_trials_disagree"] = (
            "the gold calendar days of each case with more than one scored trial, averaged over "
            "those cases; a case whose status differs across its trials on a given day counts once for that day")
        d["extended.repetition.mean_within_case_sd_day_accuracy"] = (
            "cases with more than one scored trial: the per-trial day accuracy of each such case, "
            "each trial counting once")
    return d


def arm_summary(run, arm_id, golds, scorer):
    planned = [u for u in run["planned"] if u.split("/", 1)[0] == arm_id]
    res = {r["unit_id"]: r for r in run["results"] if r["arm_id"] == arm_id}
    outc = {o: sum(1 for r in res.values() if r["outcome"] == o) for o in OUTCOMES}
    outc["unrun"] = len(planned) - len(res)
    # r7.2 (R-14): units that ended unavailable because a replay could not serve their own stored attempt. They are counted in
    # 'unavailable' (and in the ITT rate) and reported here so they are not read as model failures.
    outc["replay_identity_units"] = sum(1 for r in res.values() if r.get("unavailable_reason") == "replay_identity")
    scored = [r for r in res.values() if r["outcome"] == "scored"]
    answered = [r for r in res.values() if r["outcome"] in ("scored", "invalid")]
    hist_rows = []
    for r in answered:
        row = dict(r["score"])
        row["case"], row["slice"] = r["case_id"], r["slice"]
        hist_rows.append(row)
    historic = scorer.aggregate(hist_rows) if hist_rows else None
    ext_rows = []
    for r in scored:
        x = case_extended(r["pred_statuses"], golds[r["case_id"]], r["score"])
        x.update({"case_id": r["case_id"], "trial": r["trial"], "slice": r["slice"],
                  "displaced": r["score"]["displaced_notes"], "fabricated": r["score"]["fabricated_notes"]})
        ext_rows.append(x)

    def pooled(rows):
        tot_days = sum(x["gold_days"] for x in rows)
        tot_av = sum(x["gold_available_days"] for x in rows)
        return {"scored_units": len(rows),
                "status_error_rate": _rate(sum(x["status_errors"] for x in rows), tot_days),
                "false_unavailable_rate": _rate(sum(x["false_unavailable_days"] for x in rows), tot_av),
                "false_unavailable_days": sum(x["false_unavailable_days"] for x in rows),
                "dangerous_flips": sum(x["dangerous_flips"] for x in rows),
                "constant_status_outputs": sum(1 for x in rows if x["constant_status_output"]),
                "note_omissions": sum(x["note_omissions"] for x in rows),
                "displaced_notes": sum(x["displaced"] for x in rows),
                "fabricated_notes": sum(x["fabricated"] for x in rows),
                "doc_status_exact_rate_conditional": _rate(sum(1 for x in rows if x["doc_status_exact"]), len(rows))}

    ext = pooled(ext_rows)
    ext["doc_success_rate_itt"] = _rate(sum(1 for x in ext_rows if x["doc_success"]), len(planned))
    # r7.1 (ACC-02b, owner review 2026-10-27): every rate key in this block names its denominator for a JSON consumer
    ext["rate_denominators"] = {
        "status_error_rate": "gold days of SCORED units only (conditional on a scored answer)",
        "false_unavailable_rate": "gold available days of SCORED units only (conditional on a scored answer)",
        "doc_status_exact_rate_conditional": "SCORED units only (conditional on a scored answer)",
        "doc_success_rate_itt": "ALL planned units (intention to treat; unrun and unusable units count as failures)"}
    ext["global_note_conflict_days"] = conflict_slice(scored, golds)
    slices = sorted({x["slice"] for x in ext_rows})
    ext["per_slice"] = {s: pooled([x for x in ext_rows if x["slice"] == s]) for s in slices}
    ext["repetition"] = repetition(scored, golds)
    flags = []
    cer = historic["critical_error_rate"] if historic else None
    fur = ext["false_unavailable_rate"]
    if scored and cer == 0 and ((fur or 0) > DEGENERATE_FALSE_UNAVAILABLE or ext["constant_status_outputs"]):
        flags.append(f"DEGENERATE: critical-error rate is 0 while false-unavailable rate is "
                     f"{'n/a' if fur is None else f'{100 * fur:.1f}%'} and {ext['constant_status_outputs']} "
                     "scored unit(s) gave one status for the whole month. Zero flips here is not evidence of safety.")
    if not scored:
        flags.append("NOTHING SCORED: conditional rates are n/a; see accounting.")
    att = [a for a in run["attempts"] if a["unit_id"].split("/", 1)[0] == arm_id]
    usage_in = [((a.get("usage") or {}).get("input_tokens")) for a in att]
    usage_out = [((a.get("usage") or {}).get("output_tokens")) for a in att]
    lat = [a.get("elapsed_ms") for a in att if isinstance(a.get("elapsed_ms"), (int, float))]
    resources = {"attempts": len(att),
                 "input_tokens_reported": sum(u for u in usage_in if isinstance(u, int)),
                 "output_tokens_reported": sum(u for u in usage_out if isinstance(u, int)),
                 "attempts_without_usage": sum(1 for u in usage_in if not isinstance(u, int)),
                 "median_latency_ms": statistics.median(lat) if lat else None,
                 "served_models": sorted({a.get("served_model") for a in att if a.get("served_model")}),
                 "human_correction_time": "not measured"}
    return {"arm_id": arm_id, "planned_units": len(planned),
            "accounting": {**outc, "unusable_rate": _rate(len(planned) - len(scored), len(planned))},
            "historic_conditional": historic, "extended": ext, "flags": flags, "resources": resources,
            "denominators": _rate_denominator_sentences(arm_id, historic, ext_rows, ext["repetition"]),
            "_doc": doc_level(planned, res, golds)}


def conflict_slice(scored, golds):
    """Days where a global note contradicts the day's mark (protocol/D-6). Under the transcription task the
    reference is the mark. This slice shows whether an arm reported the mark or applied the note, so a model
    that reconciles is visible instead of being hidden in the overall error rate."""
    from .casesets import global_note_conflicts
    n = mark = applied = other = 0
    for r in scored:
        for note, d, marked in global_note_conflicts(golds[r["case_id"]]):
            n += 1
            p = r["pred_statuses"].get(d)
            if p == marked:
                mark += 1
            elif (note in ("No Mondays", "No weekends") and p == "UNAVAILABLE") or (note == "Days only" and p != "NIGHT"):
                applied += 1
            else:
                other += 1
    return {"days": n, "reported_mark": mark, "applied_note": applied, "other": other}


def repetition(scored, golds):
    by_case = {}
    for r in scored:
        by_case.setdefault(r["case_id"], []).append(r)
    multi = {c: rs for c, rs in by_case.items() if len(rs) >= 2}
    if not multi:
        return {"cases_with_2plus_scored_trials": 0, "note": "single trial: variability not estimable"}
    dis, sds = [], []
    for c, rs in multi.items():
        days = golds[c]["days"]
        dis.append(sum(1 for d in days if len({r["pred_statuses"].get(d) for r in rs}) > 1) / len(days))
        sds.append(statistics.pstdev([r["score"]["day_accuracy"] for r in rs]))
    return {"cases_with_2plus_scored_trials": len(multi),
            "mean_fraction_of_days_where_trials_disagree": sum(dis) / len(dis),
            "cases_with_any_disagreement": sum(1 for x in dis if x > 0),
            "mean_within_case_sd_day_accuracy": sum(sds) / len(sds)}


def doc_level(planned, res, golds):
    """Per document: mean over planned trials of ITT success (unusable trial = 0), and mean day accuracy
    over scored trials (None if none scored)."""
    out = {}
    for uid in planned:
        _, case, _ = uid.split("/")
        r = res.get(uid)
        d = out.setdefault(case, {"itt": [], "acc": []})
        if r and r["outcome"] == "scored":
            x = case_extended(r["pred_statuses"], golds[case], r["score"])
            d["itt"].append(1.0 if x["doc_success"] else 0.0)
            d["acc"].append(r["score"]["day_accuracy"])
        else:
            d["itt"].append(0.0)
    return {c: {"itt": sum(v["itt"]) / len(v["itt"]), "acc": (sum(v["acc"]) / len(v["acc"])) if v["acc"] else None}
            for c, v in out.items()}


def sign_test_p(pos, neg):
    n = pos + neg
    if n == 0:
        return 1.0
    k = min(pos, neg)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_ci(diffs, seed=20261026, reps=10000):
    if not diffs:
        return None
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return [means[int(0.025 * reps)], means[int(0.975 * reps) - 1]]


def paired(a, b):
    da, db = a["_doc"], b["_doc"]
    cases = sorted(set(da) & set(db))
    d_itt = [da[c]["itt"] - db[c]["itt"] for c in cases]
    both = [c for c in cases if da[c]["acc"] is not None and db[c]["acc"] is not None]
    d_acc = [da[c]["acc"] - db[c]["acc"] for c in both]
    pos, neg = sum(1 for x in d_itt if x > 0), sum(1 for x in d_itt if x < 0)
    return {"contrast": f"{a['arm_id']} - {b['arm_id']}", "documents": len(cases),
            "itt_doc_success_mean_diff": (sum(d_itt) / len(d_itt)) if d_itt else None,
            "itt_bootstrap_95ci": bootstrap_ci(d_itt),
            "sign_test": {"a_better": pos, "b_better": neg, "ties": len(d_itt) - pos - neg,
                          "p_two_sided": sign_test_p(pos, neg)},
            "conditional_day_accuracy_mean_diff": (sum(d_acc) / len(d_acc)) if d_acc else None,
            "conditional_documents": len(both), "conditional_bootstrap_95ci": bootstrap_ci(d_acc)}


def holm(contrasts):
    ps = sorted(enumerate(c["sign_test"]["p_two_sided"] for c in contrasts), key=lambda x: x[1])
    m, running = len(ps), 0.0
    for rank, (i, p) in enumerate(ps):
        running = max(running, min(1.0, (m - rank) * p))
        contrasts[i]["sign_test"]["p_holm"] = running
    return contrasts


def build_report(runs, golds, scorer, contrasts=()):
    """runs: list of (run_dict, arm_id). contrasts: list of (arm_a, arm_b) named in the protocol."""
    ids = {}
    for run, aid in runs:
        ids.setdefault(aid, []).append(f"{run['manifest'].get('manifest_hash', '?')[:12]} ({run.get('dir', '?')})")
    clash = {a: v for a, v in ids.items() if len(v) > 1}
    if clash:
        raise ReportRefused("the same arm id appears in more than one run, so one would silently replace the other: "
                            + "; ".join(f"{a}: runs {', '.join(v)}" for a, v in clash.items())
                            + ". Report the runs separately, or give the arms distinct ids in their configurations")
    arms = {aid: arm_summary(run, aid, golds, scorer) for run, aid in runs}
    pairs = holm([paired(arms[a], arms[b]) for a, b in contrasts if a in arms and b in arms])
    for v in arms.values():
        v.pop("_doc", None)
    return {"schema": "mmeval-report/1", "arms": arms, "paired_document_level": pairs,
            "limits": ["40 public synthetic documents: a diagnostic and compatibility set, already exposed in public",
                       "trials are averaged within a document before any comparison; trials are not independent units",
                       "a mock or replay pass is not a provider run; only a recorded authorised run measures a model",
                       "human correction cost is not measured in this harness"]}


def pct(v):
    return "n/a" if v is None else f"{100 * v:.1f}%"


def render_markdown(rep):
    L = ["# Multi-model report (mmeval r6)", "",
         "Three blocks per arm. ACCOUNTING counts every planned unit. HISTORIC uses the unchanged v1 "
         "definitions over units that produced an answer (conditional). EXTENDED is new in r6.", ""]
    L += ["## Accounting (intention to treat)", "",
          "| Arm | Planned | Scored | Invalid | Truncated | Refused | Unavailable | Route denied | Unrun | Unusable rate |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for aid, a in rep["arms"].items():
        x = a["accounting"]
        L.append(f"| {aid} | {a['planned_units']} | {x['scored']} | {x['invalid']} | {x['truncated']} | {x['refused']} "
                 f"| {x['unavailable']} | {x['route_denied']} | {x['unrun']} | {pct(x['unusable_rate'])} |")
    rid = [(aid, a["accounting"].get("replay_identity_units") or 0) for aid, a in rep["arms"].items()]
    if any(k for _, k in rid):
        L += [""] + [f"- **{aid}**: {k} unavailable unit(s) are replay_identity: the replay source had no stored attempt for "
                     "that exact unit and attempt (or its request differed). They are counted in Unavailable and in the ITT "
                     "rate, and are not model answers." for aid, k in rid if k]
    L += ["", "## Historic metrics (v1 definitions, conditional on an answer)", "",
          "| Arm | Day accuracy | Critical-error rate | Flips / gold-UNAVAILABLE days | Note mismatch | Note fidelity | Format validity |",
          "|---|---|---|---|---|---|---|"]
    for aid, a in rep["arms"].items():
        h = a["historic_conditional"]
        if h is None:
            L.append(f"| {aid} | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        L.append(f"| {aid} | {pct(h['day_accuracy'])} | {pct(h['critical_error_rate'])} | {h['critical_flips']} / "
                 f"{h['gold_unavailable_days']} | {pct(h['note_mismatch_rate'])} | {pct(h['note_fidelity'])} | "
                 f"{pct(h['format_validity'])} |")
    L += ["", "## Extended metrics (new in r6; scored units unless marked ITT)", "",
          "| Arm | Status error rate | False-unavailable rate | Dangerous flips | Constant outputs | Note omissions | Displaced | Fabricated | Doc success (ITT) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for aid, a in rep["arms"].items():
        e = a["extended"]
        L.append(f"| {aid} | {pct(e['status_error_rate'])} | {pct(e['false_unavailable_rate'])} | {e['dangerous_flips']} "
                 f"| {e['constant_status_outputs']} | {e['note_omissions']} | {e['displaced_notes']} | {e['fabricated_notes']} "
                 f"| {pct(e['doc_success_rate_itt'])} |")
    L += ["", "## Global-note conflict days (task definition: transcription; see protocol D-6)", "",
          "| Arm | Conflict days (scored units) | Reported the mark | Applied the note | Other |", "|---|---|---|---|---|"]
    for aid, a in rep["arms"].items():
        g = a["extended"]["global_note_conflict_days"]
        L.append(f"| {aid} | {g['days']} | {g['reported_mark']} | {g['applied_note']} | {g['other']} |")
    flagged = [(aid, f) for aid, a in rep["arms"].items() for f in a["flags"]]
    if flagged:
        L += ["", "## Flags", ""] + [f"- **{aid}**: {f}" for aid, f in flagged]
    if rep["paired_document_level"]:
        L += ["", "## Paired document-level comparisons", "",
              "| Contrast | Documents | ITT success diff | 95% bootstrap CI | A better / B better / ties | Sign-test p | Holm p |",
              "|---|---|---|---|---|---|---|"]
        for c in rep["paired_document_level"]:
            ci = c["itt_bootstrap_95ci"]
            s = c["sign_test"]
            L.append(f"| {c['contrast']} | {c['documents']} | {pct(c['itt_doc_success_mean_diff'])} | "
                     f"{'n/a' if ci is None else f'{100*ci[0]:.1f}% to {100*ci[1]:.1f}%'} | {s['a_better']} / "
                     f"{s['b_better']} / {s['ties']} | {s['p_two_sided']:.3g} | {s.get('p_holm', float('nan')):.3g} |")
    L += ["", "## Limits", ""] + [f"- {x}" for x in rep["limits"]]
    return "\n".join(L) + "\n"
