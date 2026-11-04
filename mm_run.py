#!/usr/bin/env python3
"""Multi-model comparison runner (r7.2). Dry-run is the default; dispatch is disabled.

    python3 mm_run.py verify-config --config configs/arms.queued.json
    python3 mm_run.py check-cases   --data data
    python3 mm_run.py plan          --config configs/arms.queued.json --data data --out packet.json
    python3 mm_run.py run           --config C --data data --run-dir mm_runs/<id> --dispatch   (refused unless every gate passes)
    python3 mm_run.py replay        --config C --data data --from mm_runs/<old> --run-dir mm_runs/<new>
    python3 mm_run.py import-legacy --raw results/raw --data data --run-dir mm_runs/legacy-x --arm-id x --label <model>
    python3 mm_run.py report        --data data --run mm_runs/<id> [--run ...] [--contrast a:b] --out report_dir
    python3 mm_run.py settle        --run-dir mm_runs/<id> --unit <arm/case/tN> --attempt N
                                    --decision count_unavailable|resend_authorized --by <who> --reason <why>
    python3 mm_run.py unlock        --run-dir mm_runs/<id> --by <who> --reason <why>

Nothing in plan, verify-config, check-cases, replay, import-legacy, report, settle or unlock constructs a network
transport. settle records the owner's decision for ONE unresolved send (an intent with no response and no attempt
record); unlock moves aside a run.lock whose owner is positively identified as gone on this host instance. Both refuse,
exit 2 and print one REFUSED line, for anything else, including malformed run state (r7.2).
`run` builds a network transport only through mmeval.runner.live_transport(), which requires: --dispatch; config
dispatch.enabled true; every arm status ready, dispatch_enabled true, a real model name, image capability
verified and positive limits; run_caps.max_calls_total; the arm's credential variable set; and
MMEVAL_DISPATCH_ACK equal to the first 12 characters of this run's manifest hash.

Exit: 0 done · 2 refused or invalid configuration (nothing sent) · 3 run stopped or incomplete · 1 error.
The legacy single-model harness, run_eval.py, is unchanged and still reproduces the v1 results.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True

import run_eval as scorer  # noqa: E402
from mmeval import casesets as CS  # noqa: E402
from mmeval import config as C  # noqa: E402
from mmeval import report as R  # noqa: E402
from mmeval import runner as RN  # noqa: E402
from mmeval.replay import ReplayTransport, import_legacy  # noqa: E402


def _load(cfg_path, data_dir):
    cfg = C.load_config(cfg_path)
    dc = cfg["case_set"].get("data_class", "public_synthetic")
    arms = [C.validate_arm(a, task_needs_image=True, data_class=dc,
                           trusted_local_hosts=tuple(cfg.get("trusted_local_hosts") or [])) for a in cfg["arms"]]
    cases = CS.build_case_manifest(data_dir, cfg["case_set"]["id"], cfg["case_set"].get("seed_base"))
    inc = cfg["case_set"].get("include")
    if inc:                                   # a named subset (capability check); every name must exist
        missing = sorted(set(inc) - {c["case_id"] for c in cases})
        if missing:
            raise C.ConfigError(f"case_set.include names cases that are not in {data_dir}: {missing}")
        cases = [c for c in cases if c["case_id"] in set(inc)]
    errs = CS.check_set(cases)
    if errs:
        raise C.ConfigError("case set problems: " + "; ".join(errs[:5]))
    if not cases:
        raise C.ConfigError(f"no cases in {data_dir}")
    golds = {c["case_id"]: json.load(open(c["gold_path"], encoding="utf-8")) for c in cases}
    manifest = RN.build_manifest(cfg, arms, cases, prompt=scorer.TASK_PROMPT, retry_suffix=scorer.RETRY_SUFFIX,
                                 scorer_sha256=RN.sha256_file(os.path.join(HERE, "run_eval.py")),
                                 renderer_sha256=RN.sha256_file(os.path.join(HERE, "generate_dataset.py")),
                                 data_class=dc)
    return cfg, arms, cases, golds, manifest


def cmd_verify(a):
    cfg = C.load_config(a.config)
    dc = cfg["case_set"].get("data_class", "public_synthetic")
    out = []
    for arm in cfg["arms"]:
        C.validate_arm(arm, data_class=dc, trusted_local_hosts=tuple(cfg.get("trusted_local_hosts") or []))
        try:
            C.validate_arm(arm, data_class=dc, trusted_local_hosts=tuple(cfg.get("trusted_local_hosts") or []),
                           for_dispatch=True)
            disp = "dispatchable"
        except C.ConfigError as ex:
            disp = str(ex).split(": not dispatchable: ", 1)[-1]
        out.append({"arm_id": arm["arm_id"], "provider": arm["provider"], "route": arm["route"],
                    "endpoint": arm.get("endpoint"), "status": arm["status"], "valid": True, "dispatch": disp})
    print(json.dumps({"config": a.config, "dispatch_enabled": (cfg.get("dispatch") or {}).get("enabled"),
                      "arms": out}, indent=1))
    return 0


def cmd_check_cases(a):
    cases = CS.build_case_manifest(a.data, "check", a.seed_base)
    out = {"cases": len(cases), "set_hash": CS.set_hash(cases), "set_errors": CS.check_set(cases)}
    if a.generator:
        import importlib.util, tempfile
        spec = importlib.util.spec_from_file_location("gen_under_check", a.generator)
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        out["truth_regenerates"] = sum(CS.regenerate_truth_check(c, g) for c in cases)
        with tempfile.TemporaryDirectory() as td:
            res = [CS.render_check(c, g, td) for c in cases]
        out["render_match"] = sum(1 for r in res if r["result"] == "MATCH")
        out["render_mismatch_cases"] = [c["case_id"] for c, r in zip(cases, res) if r["result"] != "MATCH"]
    conf = {c["case_id"]: CS.global_note_conflicts(json.load(open(c["gold_path"], encoding="utf-8"))) for c in cases}
    out["global_note_conflicts"] = {"cases": sum(1 for v in conf.values() if v),
                                    "days": sum(len(v) for v in conf.values())}
    print(json.dumps(out, indent=1))
    return 0 if not out["set_errors"] and not out.get("render_mismatch_cases") else 3


def cmd_plan(a):
    cfg, arms, cases, golds, manifest = _load(a.config, a.data)
    pkt = RN.dry_run_packet(manifest, cfg, arms, cases, prompt=scorer.TASK_PROMPT)
    pkt["manifest"] = manifest
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(pkt, f, indent=1)
    print(f"dry-run packet written: {a.out}  manifest {manifest['manifest_hash'][:12]}  "
          f"{pkt['planned_units_total']} planned units. Nothing was sent.")
    return 0


def cmd_run(a):
    cfg, arms, cases, golds, manifest = _load(a.config, a.data)
    try:
        transport = RN.live_transport(cfg, arms, manifest, cli_dispatch=a.dispatch)
    except (RN.RunRefused, C.ConfigError) as ex:
        print(f"REFUSED before any call: {ex}", file=sys.stderr)
        return 2
    st = RN.execute(manifest, cfg, arms, cases, golds, a.run_dir, transport, scorer,
                    prompt=scorer.TASK_PROMPT, retry_suffix=scorer.RETRY_SUFFIX)
    print(json.dumps(st, indent=1))
    return 0 if st["run_status"] == "COMPLETE" else 3


def cmd_replay(a):
    cfg, arms, cases, golds, manifest = _load(a.config, a.data)
    src = json.load(open(os.path.join(getattr(a, "from"), "manifest.json"), encoding="utf-8"))
    # r7.2-p3 (R2-ED-1): replay writes a new run directory, so the runner policy of the source is not compared; a source started
    # by an earlier runner with an otherwise identical manifest replays as identical
    strip = lambda m: {k: v for k, v in m.items() if k not in ("manifest_hash", "runner_policy")}
    same = src.get("manifest_hash") == manifest["manifest_hash"] or C.canonical_hash(strip(src)) == C.canonical_hash(strip(manifest))
    if not same and not a.allow_changed_scorer:
        print("REFUSED: the source run used a different manifest. Pass --allow-changed-scorer only to re-score "
              "stored answers with a changed scorer; the new run directory then records both hashes.", file=sys.stderr)
        return 2
    if not same:
        # r7.2 (R-15): the flag covers a changed scorer only. Any other difference (arms, protocol, trials, case set, prompt,
        # renderer, data class) would let stored answers stand for a different configuration.
        diff = sorted(k for k in set(src) | set(manifest)
                      if k not in ("manifest_hash", "scorer_sha256", "replayed_from", "runner_policy") and src.get(k) != manifest.get(k))
        if diff:
            print("REFUSED: --allow-changed-scorer re-scores stored answers with a changed scorer only, but the source manifest "
                  "also differs in: " + ", ".join(diff) + ". Nothing was replayed.", file=sys.stderr)
            return 2
    manifest = dict(manifest, replayed_from=src.get("manifest_hash"))
    manifest.pop("manifest_hash")
    manifest["manifest_hash"] = C.canonical_hash(manifest)
    st = RN.execute(manifest, cfg, arms, cases, golds, a.run_dir, ReplayTransport(getattr(a, "from")), scorer,
                    prompt=scorer.TASK_PROMPT, retry_suffix=scorer.RETRY_SUFFIX, sleep=lambda s: None)
    print(json.dumps(st, indent=1))
    return 0 if st["run_status"] == "COMPLETE" else 3


def cmd_settle(a):
    """r7.1 (O-1 / F17): owner settlement of one UNRESOLVED send. Sends nothing; the next `run` applies it."""
    rd = RN.RunDir(a.run_dir)
    try:
        man = json.load(open(os.path.join(a.run_dir, "manifest.json"), encoding="utf-8"))
        units = {u["unit_id"] for u in RN.plan_units(man)}
        rec = rd.settle(a.unit, a.attempt, a.decision, a.by, a.reason, units=units)
    except RN.RunRefused as ex:
        print(f"REFUSED: {ex}", file=sys.stderr)
        return 2
    except (LookupError, TypeError, ValueError, AttributeError, OSError, ArithmeticError) as ex:   # r7.2-p3 (Red R-ED-10)
        print(f"REFUSED: malformed run state ({type(ex).__name__}: {ex})", file=sys.stderr)
        return 2
    print(json.dumps(rec, indent=1))
    return 0


def cmd_unlock(a):
    """r7.1 (F17): release a run.lock left by a crashed run, only when its process is gone (identity-checked)."""
    try:
        moved = RN.RunDir(a.run_dir).release_stale_lock(a.by, a.reason)
    except RN.RunRefused as ex:
        print(f"REFUSED: {ex}", file=sys.stderr)
        return 2
    except (LookupError, TypeError, ValueError, AttributeError, OSError, ArithmeticError) as ex:   # r7.2-p3 (Red R-ED-10)
        print(f"REFUSED: malformed run state ({type(ex).__name__}: {ex})", file=sys.stderr)
        return 2
    print(f"stale lock moved to {moved}; the action is logged in owner-actions.jsonl")
    return 0


def cmd_import_legacy(a):
    cases = CS.build_case_manifest(a.data, "published-40", 7)
    m = import_legacy(a.raw, a.data, a.run_dir, arm_id=a.arm_id, model_label=a.label, scorer=scorer, cases=cases)
    print(json.dumps(json.load(open(os.path.join(a.run_dir, "run_status.json"))), indent=1))
    return 0


def cmd_report(a):
    cases = CS.build_case_manifest(a.data, "report", None)
    golds = {c["case_id"]: json.load(open(c["gold_path"], encoding="utf-8")) for c in cases}
    runs = []
    for spec in a.run:
        run = R.load_run(spec)
        for arm in run["manifest"]["arms"]:
            runs.append((run, arm["arm_id"]))
    contrasts = [tuple(x.split(":", 1)) for x in (a.contrast or [])]
    rep = R.build_report(runs, golds, scorer, contrasts)
    os.makedirs(a.out, exist_ok=True)
    json.dump(rep, open(os.path.join(a.out, "report.json"), "w", encoding="utf-8"), indent=1)
    open(os.path.join(a.out, "report.md"), "w", encoding="utf-8").write(R.render_markdown(rep))
    print(R.render_markdown(rep))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("verify-config"); p.add_argument("--config", required=True); p.set_defaults(fn=cmd_verify)
    p = sp.add_parser("check-cases"); p.add_argument("--data", required=True)
    p.add_argument("--seed-base", type=int, default=7); p.add_argument("--generator"); p.set_defaults(fn=cmd_check_cases)
    p = sp.add_parser("plan"); p.add_argument("--config", required=True); p.add_argument("--data", required=True)
    p.add_argument("--out", required=True); p.set_defaults(fn=cmd_plan)
    p = sp.add_parser("run"); p.add_argument("--config", required=True); p.add_argument("--data", required=True)
    p.add_argument("--run-dir", required=True); p.add_argument("--dispatch", action="store_true"); p.set_defaults(fn=cmd_run)
    p = sp.add_parser("replay"); p.add_argument("--config", required=True); p.add_argument("--data", required=True)
    p.add_argument("--from", required=True); p.add_argument("--run-dir", required=True)
    p.add_argument("--allow-changed-scorer", action="store_true"); p.set_defaults(fn=cmd_replay)
    p = sp.add_parser("import-legacy"); p.add_argument("--raw", required=True); p.add_argument("--data", required=True)
    p.add_argument("--run-dir", required=True); p.add_argument("--arm-id", required=True)
    p.add_argument("--label", required=True); p.set_defaults(fn=cmd_import_legacy)
    p = sp.add_parser("report"); p.add_argument("--data", required=True); p.add_argument("--run", action="append", required=True)
    p.add_argument("--contrast", action="append"); p.add_argument("--out", required=True); p.set_defaults(fn=cmd_report)
    p = sp.add_parser("settle", help="r7.1: owner settlement of one UNRESOLVED send (sends nothing)")
    p.add_argument("--run-dir", required=True); p.add_argument("--unit", required=True); p.add_argument("--attempt", type=int, required=True)
    p.add_argument("--decision", choices=RN.SETTLEMENT_DECISIONS, required=True); p.add_argument("--by", required=True)
    p.add_argument("--reason", required=True); p.set_defaults(fn=cmd_settle)
    p = sp.add_parser("unlock", help="r7.1: release a run.lock left by a crash (refused while its process lives)")
    p.add_argument("--run-dir", required=True); p.add_argument("--by", required=True); p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_unlock)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (C.ConfigError, RN.RunRefused) as ex:
        print(f"REFUSED: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
