"""Offline replay (r7.2). No network: these paths never construct a network transport.

ReplayTransport   feeds a NEW run the provider responses stored by an EARLIER run, so the whole run state machine
                  (repairs, retries, outcomes) is re-executed offline. Stored transport failures are replayed as
                  failures.
                  r7.2 (D1, Red R-5/R-14, Black): a stored attempt is served only to the SAME unit and attempt number,
                  and only when its recorded request hash equals the new request's hash. The runner names each send
                  through bind_identity(unit_id, attempt); a binding is used once. A send without a binding, a missing
                  record, or a hash mismatch raises a non-transient TransportError with reason 'replay_identity'; the
                  unit ends unavailable and its outcome row is marked unavailable_reason=replay_identity. It never
                  receives another unit's or another attempt's answer (r7.1 served a FIFO queue keyed by request hash).
                  A source with a duplicate (unit, attempt) record, or with an intent or raw file that has no attempt
                  record (an unreconciled run), is refused when the replay is built.
                  Owner-settled attempts replay their settlement (V1); a malformed 2xx replays as malformed (R-13).
import_legacy     turns a historical single-trial results*/raw/ folder (run_eval.py v1 layout:
                  <case>.txt, <case>.retry.txt, <case>[.retry].truncated.txt) into a run directory that the
                  report can read. It is labelled legacy: no manifest-bound configuration, no usage data.
"""
import glob, json, os

from . import config as C
from .runner import OUTCOMES, RunDir, RunRefused, _safe, now_utc
from .transport import TransportError, _scrub_payload

REPLAY_IDENTITY = "replay_identity"


def _identity_error(message):
    return TransportError("replay_identity: " + message + "; nothing was served", transient=False, reason=REPLAY_IDENTITY)


class ReplayTransport:
    name = "replay"

    def __init__(self, src_run_dir):
        rd = RunDir(src_run_dir)
        self.src = src_run_dir
        self.by_key = {}
        for a in rd.attempts():
            key = (a.get("unit_id"), a.get("attempt"))
            if key in self.by_key:
                raise RunRefused(f"replay source {src_run_dir}: duplicate attempt record {key}; reconcile the source run before "
                                 "replaying it")
            self.by_key[key] = a
        loose = sorted(f"{i.get('unit_id')} attempt {i.get('attempt')} (intent)" for i in rd.intents()
                       if (i.get("unit_id"), i.get("attempt")) not in self.by_key)
        referenced = {a.get("raw_file") for a in self.by_key.values() if a.get("raw_file")}
        if os.path.isdir(rd.raw):
            loose += sorted(f"raw/{f} (raw file)" for f in os.listdir(rd.raw) if ("raw/" + f) not in referenced)
        if loose:
            raise RunRefused(f"replay source {src_run_dir} is not reconciled (records without an attempt row: "
                             f"{'; '.join(loose[:5])}{' …' if len(loose) > 5 else ''}). Run or reconcile the source first; "
                             "nothing was replayed")
        self.bound = None
        self.served = 0

    def bind_identity(self, unit_id, attempt):
        """Called by the runner before each send: the next send is attempt `attempt` of unit `unit_id`. Used once."""
        self.bound = (unit_id, int(attempt))

    def send(self, arm, url, headers, payload, timeout_s):
        key, self.bound = self.bound, None
        if key is None:
            raise _identity_error("a send without a bound unit and attempt")
        a = self.by_key.get(key)
        if a is None:
            raise _identity_error(f"the source has no attempt {key[1]} for {key[0]}")
        want = C.canonical_hash(_scrub_payload(payload))
        if a.get("request_sha256") != want:
            raise _identity_error(f"stored attempt {key[1]} of {key[0]} was made by a different request "
                                  f"(stored {str(a.get('request_sha256'))[:12]}, new {want[:12]})")
        self.served += 1
        res = a.get("result")
        if res == "transport_error":
            raise TransportError(a.get("error", "stored transport error"), status=a.get("http_status"),
                                 transient=bool(a.get("transient")), ambiguous=bool(a.get("ambiguous")), reason=a.get("reason"))
        if res == "route_denied":
            raise TransportError("replay: the stored attempt was route-denied", transient=False)
        if res == "owner_settled":            # r7.2 (V1): reproduce the owner's settlement; there is no stored answer
            who = "by %s: %s" % (a.get("settled_by"), a.get("settled_reason"))
            if a.get("decision") == "count_unavailable":
                raise TransportError(f"replay: attempt {key[1]} was settled by the owner (count_unavailable) {who}", transient=False)
            raise TransportError(f"replay: attempt {key[1]} was settled by the owner (resend_authorized) {who}; the next stored "
                                 "attempt is replayed", transient=True)
        if not a.get("raw_file"):
            raise _identity_error(f"stored attempt {key[1]} of {key[0]} ({res}) has no raw response")
        # r7.2-p3 (Red R-ED-1): the raw file must be this unit's and this attempt's, by name and by its own record; a row that
        # points at another trial's raw file (equal request hashes across trials) is never served
        canonical = f"raw/{_safe(key[0])}.a{key[1]}.json"
        if str(a["raw_file"]).replace("\\", "/") != canonical:
            raise _identity_error(f"stored attempt {key[1]} of {key[0]} names raw file {a['raw_file']}, not {canonical}")
        try:
            stored = json.load(open(os.path.join(self.src, a["raw_file"]), encoding="utf-8"))
        except (OSError, ValueError) as ex:
            raise _identity_error(f"the raw file of stored attempt {key[1]} of {key[0]} cannot be read ({type(ex).__name__})")
        if isinstance(stored, dict) and (stored.get("unit_id") not in (None, key[0]) or stored.get("attempt") not in (None, key[1])):
            raise _identity_error(f"the raw file of stored attempt {key[1]} of {key[0]} records unit {stored.get('unit_id')} "
                                  f"attempt {stored.get('attempt')}")
        if isinstance(stored, dict) and stored.get("kind") == "malformed_2xx":      # r7.2 (R-13)
            raise TransportError(stored.get("error") or "replay: stored malformed 2xx", status=stored.get("status"), transient=False,
                                 malformed=True, body=stored.get("body_text"), body_truncated=bool(stored.get("body_truncated")))
        if not isinstance(stored, dict) or "provider_json" not in stored:
            raise _identity_error(f"stored attempt {key[1]} of {key[0]} has no provider response in its raw file")
        return {"json": stored["provider_json"], "elapsed_ms": a.get("elapsed_ms"), "http_status": a.get("http_status")}


def import_legacy(raw_dir, data_dir, out_dir, *, arm_id, model_label, scorer, cases):
    """Build a run directory from a v1 raw folder. One trial per case; the v1 harness repaired an
    unparseable answer once with RETRY_SUFFIX, and that is reproduced from the stored .retry.txt.

    r7.2 (V3, Red R-16): a refusal leaves an accurate status. The earlier run_status.json is preserved, never deleted, as
    run_status.before-refusal-<UTC>.json; a new run_status.json says IMPORT_REFUSED and names it; the refusal is appended to
    import-refusals.jsonl. The refusal is then raised as before."""
    rd = RunDir(out_dir)
    rd.lock()
    try:
        try:
            return _import_legacy(rd, raw_dir, arm_id=arm_id, model_label=model_label, scorer=scorer, cases=cases)
        except RunRefused as ex:
            if getattr(rd, "_import_opened", False):    # r7.2-p3 (Red R-ED-8): never write into a directory rd.open refused
                _record_refusal(rd, ex)
            raise
    finally:
        rd.unlock()


def _record_refusal(rd, ex):
    # r7.2-p3 (Red R-ED-2): everything that can fail (a torn results line) is read BEFORE the old status is moved, so a refusal
    # always leaves a run_status.json
    try:
        results_now = len(rd.results()) if os.path.exists(os.path.join(rd.path, "results.jsonl")) else 0
    except RunRefused:
        results_now = None
    stamp = now_utc().replace(":", "").replace("-", "")
    sp = os.path.join(rd.path, "run_status.json")
    kept = None
    if os.path.exists(sp):
        kept = f"run_status.before-refusal-{stamp}.json"
        n = 1
        while os.path.exists(os.path.join(rd.path, kept)):
            n += 1
            kept = f"run_status.before-refusal-{stamp}-{n}.json"
        os.replace(sp, os.path.join(rd.path, kept))
    row = {"at": now_utc(), "reason": str(ex)[:1000], "results_rows_now": results_now, "previous_status_file": kept}
    rd.append("import-refusals.jsonl", row)
    rd.write_status({"run_status": "IMPORT_REFUSED", "legacy": True, "refused_at": row["at"], "reason": row["reason"],
                     "previous_status_file": kept, "refusal_log": "import-refusals.jsonl", "results_rows_now": results_now,
                     "note": "the last import attempt was refused; nothing was deleted. The previous status is kept under "
                             "previous_status_file; the run's rows are as listed in results.jsonl"})


def _import_legacy(rd, raw_dir, *, arm_id, model_label, scorer, cases):
    manifest = {"schema": "mmeval-manifest/legacy-import", "legacy": True, "source_raw_dir": os.path.abspath(raw_dir),
                "model_label": model_label, "protocol": {"trials": 1, "order_seed": "legacy",
                                                          "content_repair_retries": 1},
                "case_set": {"id": "published-40", "cases": sorted([c["case_id"], c["png_sha256"], c["truth_hash"]]
                                                                     for c in cases)},
                "arms": [{"arm_id": arm_id, "model_requested": model_label, "provider": "historical"}],
                "data_class": "public_synthetic", "imported": now_utc()}
    manifest["manifest_hash"] = C.canonical_hash({k: v for k, v in manifest.items() if k != "imported"})
    rd.open(manifest)
    rd._import_opened = True
    # r7.1 (REC-14, owner review ED-R6-R28-QA-RECOVERY-ACCOUNTING-20261027-r1): r6/r7 returned at once when ANY outcome row existed,
    # so an import interrupted after the first case stayed incomplete forever with no run_status. Now an import resumes case by
    # case, append-only: a finished case is skipped; a case with partial records continues only if what exists matches the source
    # exactly (attempt kind, finish and raw text); any other state refuses by name. run_status is written at the end of a
    # completed import; a refusal is recorded by import_legacy (r7.2 V3). r7.2 (D2): the whole prior state of a case is validated
    # before any write for it (validation by Qwen unit R72-Q2-D2; owner correction: reuse, never delete, an interrupted raw).
    have_rows = set()
    for r in rd.results():
        if r["unit_id"] in have_rows:     # r7.2-p3 (Red R-ED-11)
            raise RunRefused(f"{r['unit_id']}: duplicate outcome rows; nothing was imported and every file is kept as found")
        have_rows.add(r["unit_id"])
    have_att = {}
    for a in rd.attempts():
        if a["attempt"] in have_att.get(a["unit_id"], {}):   # r7.2-p3 (Red R-ED-11): the last row no longer silently wins
            raise RunRefused(f"{a['unit_id']}: duplicate attempt records for attempt {a['attempt']}; nothing was imported and "
                             "every file is kept as found")
        have_att.setdefault(a["unit_id"], {})[a["attempt"]] = a
    plans = []    # r7.2-p3 (Red R-ED-11): pass 1 validates EVERY case; pass 2 writes. A refusal for any case writes nothing.
    for c in cases:
        base = c["case_id"]
        gold = json.load(open(c["gold_path"], encoding="utf-8"))
        uid = f"{arm_id}/{base}/t1"
        if uid in have_rows:
            continue
        first = os.path.join(raw_dir, base + ".txt")
        retry = os.path.join(raw_dir, base + ".retry.txt")
        trunc = [p for p in (os.path.join(raw_dir, base + ".truncated.txt"),
                             os.path.join(raw_dir, base + ".retry.truncated.txt")) if os.path.exists(p)]
        attempts = []
        if os.path.exists(first):
            attempts.append(("initial", open(first, encoding="utf-8").read(), "stop"))
        if os.path.exists(retry):
            attempts.append(("content_repair", open(retry, encoding="utf-8").read(), "stop"))
        for p in trunc:
            attempts.append(("content_repair" if ".retry." in p else "initial", open(p, encoding="utf-8").read(), "length"))
        if not attempts:
            continue                       # never attempted in the historical run: stays UNRUN
        # r7.2 (D2): validate the case's WHOLE prior state before writing anything for it. The prior attempt records must be
        # exactly attempts 1..k (k may be 0), each matching the source kind/finish/raw text and its raw file; a raw file with
        # no record is allowed only for attempt k+1 (an interrupted import) and only if its text equals the source text.
        # Anything else refuses by name with zero writes for this case. A valid prior state resumes exactly as before.
        prior = have_att.get(uid, {})
        n = len(attempts)
        if sorted(prior) != list(range(1, len(prior) + 1)) or len(prior) > n:
            raise RunRefused(f"{uid}: attempt records {sorted(prior)} do not form attempts 1..k of the {n} source attempt(s); "
                             "nothing was imported for it and every file is kept as found")
        k = len(prior)
        # Pass 1: validate the whole prior state for this case before writing anything for it.
        stale_raws = []   # (i, path): same-text raw of attempt k+1 left by an interrupted import; reused below
        for i in range(1, n + 1):
            kind, text, finish = attempts[i - 1]
            raw_path = os.path.join(rd.raw, f"{_safe(uid)}.a{i}.json")
            rf = os.path.relpath(raw_path, rd.path).replace(os.sep, "/") if os.path.exists(raw_path) else None
            if i in prior:                 # recorded attempt: its raw file must exist and match the source exactly
                if rf is None:
                    raise RunRefused(f"{uid} attempt {i} is recorded but its raw file is missing; nothing was imported for it")
                try:
                    stored = json.load(open(raw_path, encoding="utf-8"))
                except ValueError:
                    stored = None
                if not isinstance(stored, dict) or stored.get("text") != text:
                    raise RunRefused(f"{uid} attempt {i}: the raw file left by an earlier import differs from the source; "
                                     "nothing was imported for it and every file is kept as found")
                if (prior[i].get("kind"), prior[i].get("finish"), prior[i].get("raw_file")) != (kind, finish, rf):
                    raise RunRefused(f"{uid} attempt {i}: the existing attempt record differs from the source; nothing was "
                                     "imported for it")
                continue
            if rf is not None:             # raw with no record: allowed only at k+1 (interrupted import), same text only
                if i > k + 1:              # a later raw file exists without the record or raw file of attempt i-1
                    raise RunRefused(f"{uid} attempt {i}: a raw file exists without the record or raw file of attempt {i - 1}; "
                                     "nothing was imported for it and every file is kept as found")
                try:
                    stored = json.load(open(raw_path, encoding="utf-8"))
                except ValueError:
                    stored = None
                if not isinstance(stored, dict) or stored.get("text") != text:
                    raise RunRefused(f"{uid} attempt {i}: the raw file left by an earlier import differs from the source; "
                                     "nothing was imported for it and every file is kept as found")
                stale_raws.append((i, raw_path))
        plans.append((c, base, gold, uid, attempts, prior, n, stale_raws))
    for c, base, gold, uid, attempts, prior, n, stale_raws in plans:
        # Pass 2: the prior state is valid; write only what is missing. The same-text raw of attempt k+1 left by an interrupted
        # import is reused as found (owner correction at integration: the unit's delivery deleted and rewrote it; nothing is
        # deleted here, as in r7.1).
        reuse = {i: os.path.relpath(p, rd.path).replace(os.sep, "/") for i, p in stale_raws}
        for i in range(1, n + 1):
            if i in prior:                 # already recorded: the existing row and raw file are kept untouched
                continue
            kind, text, finish = attempts[i - 1]
            rf = reuse.get(i) or rd.save_raw(uid, i, {"text": text, "provider_json": None, "legacy_file": True})
            rd.append("attempts.jsonl", {"unit_id": uid, "attempt": i, "kind": kind, "result": "response",
                                         "finish": finish, "raw_file": rf, "ts": "legacy",
                                         "request_sha256": None, "usage": {}})
        kind, text, finish = attempts[-1]
        if finish == "length":
            outcome, pred = "truncated", None
        else:
            pred = scorer.parse_json(text)
            outcome = "scored" if (pred is not None and scorer.schema_valid(pred, gold)) else "invalid"
        row = {"unit_id": uid, "arm_id": arm_id, "case_id": base, "trial": 1, "slice": c["slice"],
               "outcome": outcome, "attempts": len(attempts), "served_model": None, "finish": finish,
               "repaired": len(attempts) > 1, "error": None, "legacy": True}
        if outcome in ("scored", "invalid"):
            row["score"] = scorer.evaluate_response(pred, gold)
        if outcome == "scored":
            row["pred_statuses"] = {d: x["status"] for d, x in pred["days"].items()}
            row["pred"] = pred
        rd.append("results.jsonl", row)
    res = rd.results()
    rd.write_status({"manifest_hash": manifest["manifest_hash"], "legacy": True, "planned_units": len(cases),
                     "terminal_units": len(res), "unrun_units": len(cases) - len(res),
                     "outcomes": {o: sum(1 for r in res if r["outcome"] == o) for o in OUTCOMES},
                     "run_status": "COMPLETE" if len(res) == len(cases) else "INCOMPLETE", "updated": now_utc()})
    return manifest
