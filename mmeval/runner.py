"""Run engine for multi-model comparisons (r7.2).

One UNIT is (arm, case, trial). A unit has one or more ATTEMPTS. Every attempt is appended to
attempts.jsonl before the next one starts; nothing is overwritten. A unit ends in exactly one terminal
OUTCOME, appended to results.jsonl:

  scored        the answer parsed and passed the schema check; it was scored
  invalid       the answer did not parse (after the allowed repair attempt) or failed the schema check
  truncated     the provider stopped at the output-token limit; the text is kept, never scored
  refused       the provider reported a refusal / content filter (an abstention)
  unavailable   no model answer: transport or provider failure after the allowed attempts
  route_denied  the transport refused the destination (should be impossible after validation; recorded)
A planned unit with no terminal row is UNRUN. Reports count every planned unit.

Retries are bounded and explicit:
  - a transient transport failure (HTTP 408/409/429/5xx/529, network error) may be retried, with backoff,
    up to limits.max_attempts_per_trial attempts in total for the unit
  - an unparseable answer gets protocol.content_repair_retries extra attempts with the historic repair
    suffix (run_eval.RETRY_SUFFIX). The historic harness used 1. A schema-invalid answer is not repaired.
No attempt replaces an earlier one: the unit's outcome comes from its last attempt, and all attempts stay.

One writer: a run takes run.lock (O_EXCL) and releases it at the end; a second process is refused.

Write-ahead and reconciliation (r7, 2026-10-30; REC-05/06/07): before every send an INTENT record is appended to
intents.jsonl. On (re)start, before anything is sent, reconcile() compares intents, attempt records, saved raw responses
and outcome rows for every planned unit:
  - a saved raw response with no attempt record is turned into an attempt record (recovered: from_raw); no resend;
  - an intent with neither a raw response nor an attempt record is UNRESOLVED (a request may have reached the
    provider): the run is refused before any send and every file is kept; the owner decides. No exactly-once claim;
  - duplicate or out-of-plan outcome rows, and duplicate attempt records, refuse the run.
A unit whose last recorded attempt is terminal (non-transient transport error, provider-shape error, route denial, a
transient error with no attempts left) ends from that record without a send. Only a transient error with attempts
left, or an unparseable answer with a repair left, is retried.

r7.2 (ORCA-COLOUR-TO-OPERATIONS-20261101-r1, DESIGN-r2 and BLACK-DISPOSITION):
  - a 2xx whose body cannot be read or decoded is MALFORMED: its raw record (kind malformed_2xx, the bytes that arrived) is
    saved, the attempt is bad_provider_shape and the unit ends unavailable. It is never retried (Red R-3);
  - a send that may have reached the provider without a status line is AMBIGUOUS: by default it is not resent and the unit
    ends unavailable; the owner may set protocol.ambiguous_resend true (it is part of the manifest), and each such resend is
    marked ambiguous_resend in its attempt row;
  - a transport that declares bind_identity(unit_id, attempt) is told which attempt each send is (replay identity, D1);
  - run.lock records the host instance; an owner is released only when it is positively identified as dead on THIS host
    instance (Red R-2, Black). Unknown is not dead.

Resume: a run directory holds manifest.json. A new invocation with a different manifest hash is refused.
With the same hash, units that already have a terminal outcome are skipped; a unit with attempts but no
outcome continues, and its earlier attempts count toward its limit.

Dispatch: the default transport denies every send. A live transport is built only by live_transport(),
which re-validates every arm for dispatch and needs the config flag, the CLI flag and an acknowledgement
environment variable that names this manifest's hash. Credentials are read at send time from the
environment variable the arm names, and never written anywhere.
"""
import datetime, hashlib, json, os, random, re, socket, time, uuid

from . import config as C
from .adapters import AdapterError, build_request, parse_response
from .transport import DenyTransport, HttpTransport, TransportDenied, TransportError, _scrub_payload

MANIFEST_SCHEMA = "mmeval-manifest/1"
OUTCOMES = ("scored", "invalid", "truncated", "refused", "unavailable", "route_denied")
ACK_ENV = "MMEVAL_DISPATCH_ACK"
# r7.2-p3 (Red R-ED-3, R2-ED-1): r7.2 changed the retry policy (an ambiguous send is not resent by default). The policy is part of
# the hashed manifest, so a run is resumed only under the policy that started it, in BOTH directions: r7.2 refuses an r7.1-started
# directory, and r7.1 (which builds a manifest without this key) refuses an r7.2-started one. Change the string whenever the retry or
# ambiguity policy changes. Replay writes a new directory and compares manifests without this key (mm_run.py cmd_replay).
RUNNER_EDITION = "mmeval-runner r7.2"
RUNNER_POLICY = "mmeval-runner r7.2: an ambiguous send is resent only under protocol.ambiguous_resend; a malformed 2xx is never resent"


SETTLEMENT_DECISIONS = ("count_unavailable", "resend_authorized")   # r7.1 (O-1)


class RunRefused(RuntimeError):
    """The run must not start (manifest mismatch, missing acknowledgement, caps, credentials)."""


def proc_identity(pid):
    """r7.1: (alive, creation-time string) for a pid; (None, None) when it cannot be checked. Standard library only."""
    if not isinstance(pid, int) or pid <= 0:
        return False, None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        h = k.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return (False, None) if ctypes.get_last_error() == 87 else (None, None)   # 87: no such process
        try:
            code = wintypes.DWORD()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return None, None
            c, e_, kt, ut = (wintypes.FILETIME() for _ in range(4))
            if not k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e_), ctypes.byref(kt), ctypes.byref(ut)):
                return None, None
            return code.value == 259, str((c.dwHighDateTime << 32) | c.dwLowDateTime)     # 259: STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        with open(f"/proc/{pid}/stat") as f:
            return True, f.read().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return False, None
    except OSError:
        return None, None


def host_identity():
    """r7.2 (R-2, Black): the instance whose process table a pid belongs to: {"name": hostname, "id": instance id or None}.
    Windows: the machine GUID. POSIX: machine-id | boot id | pid namespace (a sandbox and its host never match)."""
    name = socket.gethostname()
    ident = None
    if os.name == "nt":
        try:
            import winreg
            access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access) as k:
                ident = "win:" + str(winreg.QueryValueEx(k, "MachineGuid")[0])
        except OSError:
            ident = None
    else:
        parts = []
        for path in ("/etc/machine-id", "/proc/sys/kernel/random/boot_id"):
            try:
                with open(path) as f:
                    parts.append(f.read().strip())
            except OSError:
                parts.append("")
        try:
            parts.append(os.readlink("/proc/self/ns/pid"))
        except OSError:
            parts.append("")
        ident = ("posix:" + "|".join(parts)) if all(parts[1:]) else None
    return {"name": name, "id": ident}


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(unit_id):
    return re.sub(r"[^A-Za-z0-9._-]", "_", unit_id)


# ---------------------------------------------------------------- manifest and plan
def build_manifest(cfg, arms, cases, *, prompt, retry_suffix, scorer_sha256, renderer_sha256, data_class):
    proto = cfg["protocol"]
    m = {
        "schema": MANIFEST_SCHEMA,
        "protocol": proto,
        "prompt_sha256": sha256_bytes(prompt.encode()),
        "retry_suffix_sha256": sha256_bytes(retry_suffix.encode()),
        "scorer_sha256": scorer_sha256,           # run_eval.py: prompt, parser, schema check, scorer
        "renderer_sha256": renderer_sha256,       # generate_dataset.py
        "data_class": data_class,
        "case_set": {"id": cfg["case_set"]["id"],
                     "cases": sorted([c["case_id"], c["png_sha256"], c["truth_hash"]] for c in cases)},
        "arms": [C.arm_identity(a) for a in arms],
        "runner_policy": RUNNER_POLICY,           # r7.2-p3 (R2-ED-1)
    }
    m["manifest_hash"] = C.canonical_hash(m)
    return m


def plan_units(manifest):
    """Trial-major, then a seeded shuffle of cases, then every arm: each case is read by every arm close
    together in time, so provider drift during a run does not fall on one arm only."""
    proto = manifest["protocol"]
    case_ids = [c[0] for c in manifest["case_set"]["cases"]]
    arm_ids = [a["arm_id"] for a in manifest["arms"]]
    units = []
    for t in range(1, int(proto["trials"]) + 1):
        order = list(case_ids)
        random.Random(f"{proto['order_seed']}:{t}").shuffle(order)
        for cid in order:
            for aid in arm_ids:
                units.append({"unit_id": f"{aid}/{cid}/t{t}", "arm_id": aid, "case_id": cid, "trial": t})
    return units


# ---------------------------------------------------------------- run directory (append-only)
class RunDir:
    def __init__(self, path):
        self.path = path
        self.raw = os.path.join(path, "raw")

    def lock(self):
        """One writer per run directory. A second process is refused. A lock left by a crashed run is not broken
        automatically: the owner checks that no run is live, then removes run.lock by hand."""
        os.makedirs(self.path, exist_ok=True)
        p = os.path.join(self.path, "run.lock")
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RunRefused(f"{p} exists: another run holds this directory, or a run crashed. Check that no run is "
                             "live, then remove run.lock and resume.") from None
        with os.fdopen(fd, "w") as f:   # r7.1: the process creation time makes a reused pid distinguishable later
            f.write(json.dumps({"pid": os.getpid(), "pid_start": proc_identity(os.getpid())[1], "since": now_utc(),
                                "host": host_identity()}))          # r7.2 (R-2): the instance the pid belongs to
        self._locked = p

    def release_stale_lock(self, by, reason):
        """r7.1 (F17): owner action for a lock left by a crash. The lock is moved aside (never deleted) and the action is logged.
        r7.2 (R-2, Black): released only when the owner is positively identified as gone: the lock parses, names an integer pid
        and the host instance it was written on, that instance is THIS one, and the process is dead or has a different creation
        time. Every other case is refused and the lock is kept as found: an unreadable, empty or torn lock; a non-integer pid; an
        r7.1-format lock without a host; another host instance (a Windows pid reads as dead from a Linux sandbox); a live pid
        without a recorded creation time. Unknown is not dead."""
        if not by or not reason:
            raise RunRefused("unlock needs --by (who) and --reason (why)")
        p = os.path.join(self.path, "run.lock")
        if not os.path.exists(p):
            raise RunRefused(f"{p} does not exist; nothing to release")
        keep = ("the owner of run.lock cannot be positively identified as gone, so the lock is kept as found. Check that no run "
                "is live, then remove run.lock by hand. Reason: ")
        try:
            with open(p, "rb") as f:
                raw = f.read()
        except OSError as ex:
            raise RunRefused(keep + f"the lock cannot be read ({type(ex).__name__})") from None
        try:
            rec = json.loads(raw.decode("utf-8"))
        except ValueError:
            rec = None
        if not isinstance(rec, dict) or type(rec.get("pid")) is not int:
            raise RunRefused(keep + "the lock is empty, torn, not JSON, or has no integer pid")
        here, h = host_identity(), rec.get("host")
        if not isinstance(h, dict) or not h.get("id"):
            raise RunRefused(keep + "the lock names no host instance (r7.1 format), so a live owner on another host cannot be "
                             "ruled out")
        if not here.get("id"):
            raise RunRefused(keep + "this host's instance id cannot be read")
        if (h.get("name"), h.get("id")) != (here["name"], here["id"]):
            raise RunRefused(keep + f"the lock was written on another host instance ({h.get('name')}), where pid {rec['pid']} "
                             "may be alive")
        alive, start = proc_identity(rec["pid"])
        if alive is None:
            raise RunRefused(keep + f"the process identity of pid {rec['pid']} cannot be checked")
        if alive and (rec.get("pid_start") is None or start == rec.get("pid_start")):
            raise RunRefused(keep + f"pid {rec['pid']} is alive" + ("" if rec.get("pid_start") else " (no creation time recorded, "
                             "so a reused pid cannot be told apart)"))
        # r7.2-p3 (Red R-ED-10, R2-ED-2): a unique name chosen without an exists test, so two releases never collide; then the moved
        # bytes are compared with the bytes that were checked. A lock that changed between the check and the move (a new run took it)
        # is put back if run.lock is free, and the release is refused naming both files.
        # BLACK-ED-r72 residual: the put-back never replaces an existing run.lock on any platform: os.link fails when the target
        # exists (rename would replace it and could destroy a third run's lock), so the moved file is kept beside it.
        moved = p + ".stale-" + now_utc().replace(":", "").replace("-", "")[:15] + "-" + uuid.uuid4().hex[:8]
        try:
            os.rename(p, moved)
        except OSError as ex:      # the lock could not be moved; say so, it is kept as found
            raise RunRefused(f"run.lock could not be moved aside ({type(ex).__name__}: {ex}); it is kept as found. Check that no "
                             "run is live, then move it by hand") from None
        try:
            with open(moved, "rb") as f:
                now_raw = f.read()
        except OSError:
            now_raw = None
        if now_raw != raw:
            back = False
            try:
                os.link(moved, p)               # fails when run.lock exists again; never replaces it
                os.remove(moved)
                back = True
            except OSError:
                back = False
            raise RunRefused("run.lock changed between the identity check and the move (another run may have taken it). "
                             + (f"It was put back as run.lock; nothing was released." if back else
                                f"It is now {os.path.basename(moved)} and could not be put back because run.lock exists again; "
                                "check both files by hand before any run continues."))
        try:
            self.append("owner-actions.jsonl", {"action": "release_stale_lock", "by": by, "reason": reason, "lock": rec,
                                                "process_alive": alive, "process_start_now": start,
                                                "moved_to": os.path.basename(moved), "at": now_utc()})
        except OSError as ex:      # r7.2 (D4/R-20): say what WAS written
            raise RunRefused(f"the lock WAS moved to {os.path.basename(moved)}, but recording the action in owner-actions.jsonl "
                             f"failed ({type(ex).__name__}: {ex}); record the release by hand") from None
        return moved

    def unlock(self):
        p = getattr(self, "_locked", None)
        if p and os.path.exists(p):
            os.remove(p)          # this process's own lock file only
        self._locked = None

    def open(self, manifest):
        os.makedirs(self.raw, exist_ok=True)
        mp = os.path.join(self.path, "manifest.json")
        if os.path.exists(mp):
            old = json.load(open(mp, encoding="utf-8"))
            strip = lambda m: {k: v for k, v in m.items() if k not in ("manifest_hash", "runner_policy")}
            if (old.get("manifest_hash") != manifest["manifest_hash"] and old.get("runner_policy") != manifest.get("runner_policy")
                    and C.canonical_hash(strip(old)) == C.canonical_hash(strip(manifest))):
                raise RunRefused(f"{self.path} was started under runner policy {old.get('runner_policy') or 'r7.1 or before (none recorded)'!r}; "
                                 f"this runner applies {manifest.get('runner_policy')!r}. Resume it with the runner that started it, or "
                                 "use a new run directory. Nothing was sent")
            if old.get("manifest_hash") != manifest["manifest_hash"]:
                raise RunRefused(f"{self.path} belongs to manifest {str(old.get('manifest_hash'))[:12]}; this run is "
                                 f"{manifest['manifest_hash'][:12]}. Resume needs an identical manifest; use a new "
                                 "run directory for a changed configuration")
        else:
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=1, sort_keys=True)

    def _read(self, name):
        p = os.path.join(self.path, name)
        if not os.path.exists(p):
            return []
        out = []
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:        # r7 edition 2 (colour review CR-01): name the file and line, refuse
                    raise RunRefused(f"{p} line {i} is not valid JSON (a write may have been cut off). Nothing was "
                                     "sent and the file is kept as found; the owner decides whether that line is a "
                                     "torn write before the run continues") from None
        return out

    def attempts(self):
        return self._read("attempts.jsonl")

    def results(self):
        return self._read("results.jsonl")

    def intents(self):
        return self._read("intents.jsonl")

    def settlements(self):
        return self._read("settlements.jsonl")

    def settle(self, unit_id, attempt, decision, by, reason, units=None):
        """r7.1 (O-1 / F17): owner settlement of ONE unresolved attempt (an intent with no saved response, no error and no attempt
        record). decision: 'count_unavailable' (the unit ends unavailable; nothing is sent) or 'resend_authorized' (the next run may
        send one new attempt for it, within the arm's attempt limit). Never automatic; refused for anything not unresolved."""
        if decision not in SETTLEMENT_DECISIONS:
            raise RunRefused(f"decision must be one of {SETTLEMENT_DECISIONS}")
        if not by or not str(by).strip() or not reason or not str(reason).strip():
            raise RunRefused("a settlement needs --by (who decided) and --reason (why)")
        if units is not None and unit_id not in units:
            raise RunRefused(f"{unit_id} is not a planned unit of this run")
        attempt = int(attempt)
        if not any(i["unit_id"] == unit_id and i["attempt"] == attempt for i in self.intents()):
            raise RunRefused(f"{unit_id} attempt {attempt} has no intent record; only an unresolved send can be settled")
        if any(a["unit_id"] == unit_id and a["attempt"] == attempt for a in self.attempts()):
            raise RunRefused(f"{unit_id} attempt {attempt} already has an attempt record; it is not unresolved")
        if attempt in _raw_attempts(self, unit_id):
            raise RunRefused(f"{unit_id} attempt {attempt} has a saved raw response; resume recovers it, no settlement needed")
        if any(r["unit_id"] == unit_id for r in self.results()):
            raise RunRefused(f"{unit_id} already has an outcome row")
        if any(s["unit_id"] == unit_id and s["attempt"] == attempt for s in self.settlements()):
            raise RunRefused(f"{unit_id} attempt {attempt} is already settled")
        rec = {"unit_id": unit_id, "attempt": attempt, "decision": decision, "by": str(by), "reason": str(reason), "at": now_utc()}
        self.append("settlements.jsonl", rec)
        return rec

    def append(self, name, rec):
        with open(os.path.join(self.path, name), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def save_raw(self, unit_id, attempt_no, obj):
        p = os.path.join(self.raw, f"{_safe(unit_id)}.a{attempt_no}.json")
        if os.path.exists(p):
            raise RunRefused(f"raw file already exists, refusing to overwrite: {p}")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)
        return os.path.relpath(p, self.path).replace(os.sep, "/")

    def write_status(self, status):
        with open(os.path.join(self.path, "run_status.json"), "w", encoding="utf-8") as f:
            json.dump(status, f, indent=1, sort_keys=True)


# ---------------------------------------------------------------- dispatch gate
def live_transport(cfg, arms, manifest, *, cli_dispatch, environ=None, task_needs_image=True):
    """The only constructor of a network transport. Every condition is checked; the first failure refuses."""
    env = os.environ if environ is None else environ
    if not cli_dispatch:
        raise RunRefused("dispatch not requested on the command line (dry-run is the default)")
    if (cfg.get("dispatch") or {}).get("enabled") is not True:
        raise RunRefused("config dispatch.enabled is not true")
    ack = env.get(ACK_ENV, "")
    if ack != manifest["manifest_hash"][:12]:
        raise RunRefused(f"set {ACK_ENV} to this manifest's first 12 hash characters to acknowledge this exact run")
    trusted = tuple((cfg.get("trusted_local_hosts") or []))
    for a in arms:
        C.validate_arm(a, task_needs_image=task_needs_image, data_class=manifest["data_class"],
                       trusted_local_hosts=trusted, for_dispatch=True,
                       capability_check=bool(manifest["protocol"].get("capability_check")))
        if a.get("credential_env") and not env.get(a["credential_env"]):
            raise RunRefused(f"{a['arm_id']}: credential variable {a['credential_env']} is not set")
    caps = cfg.get("run_caps") or {}
    if not isinstance(caps.get("max_calls_total"), int) or caps["max_calls_total"] <= 0:
        raise RunRefused("run_caps.max_calls_total must be a positive integer before dispatch")
    if caps.get("max_usd") is not None and not cfg.get("prices_usd_per_mtok"):
        raise RunRefused("run_caps.max_usd is set but no prices are configured, so it cannot be enforced")
    return HttpTransport(trusted_local_hosts=trusted)


# ---------------------------------------------------------------- one unit
def _classify(scorer, gold, text, finish):
    """(outcome or None, pred, needs_repair). outcome None means 'parse failed; a repair may follow'."""
    if finish == "length":
        return "truncated", None, False
    if finish == "refusal":
        return "refused", None, False
    pred = scorer.parse_json(text)
    if pred is None:
        return None, None, True
    return ("scored" if scorer.schema_valid(pred, gold) else "invalid"), pred, False


def _raw_attempts(rd, unit_id):
    """{attempt number: relative raw path} for this unit's saved raw responses."""
    pat = re.compile("^" + re.escape(_safe(unit_id)) + r"\.a(\d+)\.json$")
    out = {}
    if os.path.isdir(rd.raw):
        for f in os.listdir(rd.raw):
            m = pat.match(f)
            if m:
                out[int(m.group(1))] = "raw/" + f
    return out


def _record_from_raw(rd, unit_id, n, rel, arm, intent, prev, scorer):
    """An attempt record rebuilt from a saved raw response, or None if the file does not support one."""
    try:
        stored = json.load(open(os.path.join(rd.path, rel), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(stored, dict) or stored.get("unit_id") not in (None, unit_id) or stored.get("attempt") not in (None, n):
        return None
    malformed = stored.get("kind") == "malformed_2xx"      # r7.2 (R-13): a 2xx whose body could not be read or decoded
    pj = stored.get("provider_json")
    if pj is None and not malformed:
        return None
    if intent:
        kind, variant = intent.get("kind"), intent.get("prompt_variant")
    elif n == 1:
        kind, variant = "initial", "task"
    elif prev and prev.get("result") == "response" and prev.get("parse") == "unparseable":
        kind, variant = "content_repair", "repair"
    elif prev and prev.get("result") == "transport_error":
        kind, variant = "transport_retry", prev.get("prompt_variant")
    else:
        return None                                    # cannot say which prompt produced it
    rec = {"unit_id": unit_id, "attempt": n, "kind": kind, "prompt_variant": variant, "ts": now_utc(),
           "request_sha256": (intent or {}).get("request_sha256"), "raw_file": rel, "recovered": "from_raw"}
    if malformed:
        rec.update({"result": "bad_provider_shape", "malformed": True, "http_status": stored.get("status"),
                    "error": str(stored.get("error") or "malformed 2xx response")[:300]})
        return rec
    try:
        parsed = parse_response(arm, pj)
    except AdapterError as ex:
        rec.update({"result": "bad_provider_shape", "error": str(ex)})
        return rec
    rec.update({"result": "response", "finish": parsed["finish"], "finish_raw": parsed["finish_raw"],
                "served_model": parsed["served_model"], "usage": parsed["usage"], "timing": parsed["timing"],
                "parse": "unparseable" if scorer.parse_json(parsed["text"]) is None else "ok"})
    return rec


def reconcile(rd, units, arms_by, scorer):
    """Before any send: make the ledger consistent or refuse. Returns {"recovered": [...]}; raises RunRefused."""
    planned = {u["unit_id"]: u for u in units}
    counts = {}
    for r in rd.results():
        counts[r["unit_id"]] = counts.get(r["unit_id"], 0) + 1
    dups = sorted(u for u, k in counts.items() if k > 1)
    foreign = sorted(u for u in counts if u not in planned)
    if dups or foreign:
        raise RunRefused(f"outcome ledger is inconsistent: duplicate outcome rows {dups}; out-of-plan rows {foreign}. "
                         "Nothing was sent; results.jsonl is kept as found")
    names = {}
    for uid in planned:
        names.setdefault(_safe(uid), []).append(uid)
    clash = [v for v in names.values() if len(v) > 1]
    if clash:
        raise RunRefused(f"unit ids collide in raw file names: {clash}")
    by_att = {}
    for a in rd.attempts():
        key = (a["unit_id"], a["attempt"])
        if key in by_att:
            raise RunRefused(f"duplicate attempt record {key}; nothing was sent")
        by_att[key] = a
    intents = {(i["unit_id"], i["attempt"]): i for i in rd.intents()}
    settled = {(s["unit_id"], s["attempt"]): s for s in rd.settlements()}      # r7.1 (O-1): owner decisions, never automatic
    recovered, unresolved = [], []
    for uid in planned:
        if uid in counts:
            continue
        raws = _raw_attempts(rd, uid)
        for n in sorted(set(raws) | {k[1] for k in intents if k[0] == uid}):
            if (uid, n) in by_att:
                continue
            if n in raws:
                if (uid, n) in settled:
                    raise RunRefused(f"{uid} attempt {n} was settled by the owner, but a raw response for it now exists; nothing "
                                     "was sent; the owner reconciles the settlement and the file")
                rec = _record_from_raw(rd, uid, n, raws[n], arms_by[planned[uid]["arm_id"]], intents.get((uid, n)),
                                       by_att.get((uid, n - 1)), scorer)
                if rec is None:
                    unresolved.append(f"{uid} attempt {n}: raw file present but it does not support one result")
                else:
                    recovered.append(rec)
                    by_att[(uid, n)] = rec
            elif (uid, n) in settled:   # r7.1: the owner's settlement closes the unresolved attempt; no send is made for it
                s = settled[(uid, n)]
                prev = by_att.get((uid, n - 1))
                rec = {"unit_id": uid, "attempt": n, "kind": (intents.get((uid, n)) or {}).get("kind", "initial"),
                       "result": "owner_settled", "decision": s["decision"], "settled_by": s["by"], "settled_reason": s["reason"],
                       "ts": now_utc(), "request_sha256": (intents.get((uid, n)) or {}).get("request_sha256"),
                       "note": "no response was saved for this send; the owner decided how it counts"}
                recovered.append(rec)
                by_att[(uid, n)] = rec
            else:
                unresolved.append(f"{uid} attempt {n}: a send was started (intent recorded) but no response or "
                                  "error was saved")
    if unresolved:
        raise RunRefused("UNRESOLVED attempts; nothing was sent and every file is kept as found. A request may have "
                         "reached the provider without a saved answer, so resending could duplicate it. The owner "
                         "decides how to settle each one: " + "; ".join(unresolved))
    for rec in recovered:
        rd.append("attempts.jsonl", rec)
    return {"recovered": [f"{r['unit_id']}#{r['attempt']}" for r in recovered]}


def run_unit(unit, arm, case, gold, *, rd, transport, scorer, prompt, retry_suffix, protocol, prior_attempts,
             budget, environ=None, sleep=time.sleep, image_bytes=None):
    """Run one unit to a terminal outcome, or return None if a budget stopped it first."""
    env = os.environ if environ is None else environ
    lim = arm.get("limits") or {}
    max_att = int(lim.get("max_attempts_per_trial") or 1)
    timeout_s = int(lim.get("timeout_s") or 120)
    repairs_allowed = int(protocol.get("content_repair_retries", 1))
    backoff = protocol.get("backoff_s", [2, 8, 30])
    mine = sorted((a for a in rd.attempts() if a["unit_id"] == unit["unit_id"]), key=lambda a: a["attempt"])
    n = max([a["attempt"] for a in mine], default=0)   # attempt numbers come from the ledger, not a count
    repairs_used = sum(1 for a in mine if a["kind"] == "content_repair")
    use_repair = repairs_used > 0      # a resumed unit keeps the prompt variant it had reached
    last = None
    last_res = mine[-1].get("result") if mine else None
    allow_ambiguous = protocol.get("ambiguous_resend") is True     # r7.2: an owner setting, part of the manifest
    after_ambiguous = bool(mine) and bool(mine[-1].get("ambiguous"))
    # r7: a terminal recorded attempt stays terminal after a stop (REC-06, REC-07); nothing is sent for it.
    if last_res == "transport_error" and not (mine[-1].get("transient") and n < max_att
                                              and (allow_ambiguous or not mine[-1].get("ambiguous"))):
        out = {"outcome": "unavailable", "attempts": n, "error": mine[-1].get("error"), "resumed_from_record": True}
        if mine[-1].get("reason"):
            out["unavailable_reason"] = mine[-1]["reason"]
        return out
    if last_res == "bad_provider_shape":
        return {"outcome": "unavailable", "attempts": n, "error": "provider response shape not understood",
                "resumed_from_record": True}
    if last_res == "route_denied":
        return {"outcome": "route_denied", "attempts": n, "resumed_from_record": True}
    if last_res == "owner_settled":   # r7.1 (O-1): the owner settled an unresolved send
        if mine[-1].get("decision") == "count_unavailable" or n >= max_att:
            return {"outcome": "unavailable", "attempts": n, "resumed_from_record": True,
                    "error": "owner settlement (%s) by %s: %s" % (mine[-1].get("decision"), mine[-1].get("settled_by"),
                                                                  mine[-1].get("settled_reason"))
                             + ("" if mine[-1].get("decision") == "count_unavailable" else "; no attempt left within the limit")}
        last = "transport"            # resend_authorized with attempts left: exactly the next attempt may be sent
        mine[-1] = dict(mine[-1], result="transport_error", transient=True)
        last_res = "transport_error"
    if last_res == "transport_error":
        last = "transport"                             # transient, attempts left: a legitimate retry follows
    elif last_res not in (None, "response") or (last_res == "response" and not mine[-1].get("raw_file")):
        raise RunRefused(f"{unit['unit_id']}: last attempt record has an unknown or incomplete result {last_res!r}; "
                         "nothing was sent")
    # Resumed after an answer was recorded but before its outcome was written: decide from the stored
    # answer instead of asking again (no silent replacement of an answer by a fresh one).
    if mine and mine[-1].get("result") == "response" and mine[-1].get("raw_file"):
        stored = json.load(open(os.path.join(rd.path, mine[-1]["raw_file"]), encoding="utf-8"))
        outcome, pred, needs_repair = _classify(scorer, gold, stored.get("text", ""), mine[-1].get("finish"))
        if outcome:
            return {"outcome": outcome, "attempts": n, "pred": pred, "text": stored.get("text", ""),
                    "served_model": mine[-1].get("served_model"), "finish": mine[-1].get("finish"),
                    "repaired": use_repair, "resumed_from_stored_answer": True}
        if not (repairs_used < repairs_allowed and n < max_att):
            return {"outcome": "invalid", "attempts": n, "pred": None, "text": stored.get("text", ""),
                    "served_model": mine[-1].get("served_model"), "finish": mine[-1].get("finish"),
                    "repaired": use_repair, "resumed_from_stored_answer": True}
        repairs_used += 1
        use_repair, last = True, "repair"
    img = image_bytes if image_bytes is not None else open(case["png_path"], "rb").read()
    while n < max_att:
        stop = budget.check(arm["arm_id"])
        if stop:
            return None
        n += 1
        kind = "initial" if n == 1 else ("content_repair" if use_repair and last == "repair" else "transport_retry")
        p = prompt + (retry_suffix if use_repair else "")
        cred = env.get(arm.get("credential_env") or "", None) if arm.get("credential_env") else None
        url, headers, payload = build_request(arm, img, "image/png", p, credential=cred)
        rec = {"unit_id": unit["unit_id"], "attempt": n, "kind": kind, "ts": now_utc(),
               "prompt_variant": "repair" if use_repair else "task",
               "request_sha256": C.canonical_hash(_scrub_payload(payload)), "endpoint": url}
        if after_ambiguous and kind == "transport_retry":
            rec["ambiguous_resend"] = True          # r7.2: an owner-authorized resend after an ambiguous send
        after_ambiguous = False
        budget.count_call(arm["arm_id"])
        rd.append("intents.jsonl", {k: rec[k] for k in ("unit_id", "attempt", "kind", "ts", "prompt_variant",
                                                         "request_sha256", "endpoint")})
        bind = getattr(transport, "bind_identity", None)
        if bind is not None:                        # r7.2 (D1, R-5): only a transport that declares it learns the identity
            bind(unit["unit_id"], n)
        try:
            resp = transport.send(arm, url, headers, payload, timeout_s)
        except TransportDenied as ex:
            rec.update({"result": "route_denied", "error": str(ex)[:300]})
            rd.append("attempts.jsonl", rec)
            return {"outcome": "route_denied", "attempts": n}
        except TransportError as ex:
            if getattr(ex, "malformed", False):     # r7.2 (V4, R-3, R-13): a 2xx whose body could not be read; never retried
                rec.update({"result": "bad_provider_shape", "malformed": True, "error": str(ex)[:300], "http_status": ex.status})
                rec["raw_file"] = rd.save_raw(unit["unit_id"], n, {
                    "unit_id": unit["unit_id"], "attempt": n, "kind": "malformed_2xx", "status": ex.status,
                    "body_text": getattr(ex, "body", None), "body_truncated": bool(getattr(ex, "body_truncated", False)),
                    "error": str(ex)[:300], "provider_json": None})
                rd.append("attempts.jsonl", rec)
                return {"outcome": "unavailable", "attempts": n, "error": "provider response could not be read (malformed 2xx)"}
            rec.update({"result": "transport_error", "error": str(ex)[:300], "http_status": ex.status,
                        "transient": ex.transient})
            if getattr(ex, "ambiguous", False):
                rec["ambiguous"] = True
            if getattr(ex, "reason", None):
                rec["reason"] = ex.reason
            rd.append("attempts.jsonl", rec)
            if ex.transient and n < max_att and (allow_ambiguous or not getattr(ex, "ambiguous", False)):
                last = "transport"
                after_ambiguous = bool(getattr(ex, "ambiguous", False))
                sleep(backoff[min(n - 1, len(backoff) - 1)])
                continue
            out = {"outcome": "unavailable", "attempts": n, "error": rec["error"]}
            if getattr(ex, "ambiguous", False) and ex.transient and n < max_att:
                out["error"] = rec["error"] + "; not resent: protocol.ambiguous_resend is not set"
            if getattr(ex, "reason", None):
                out["unavailable_reason"] = ex.reason
            return out
        try:
            parsed = parse_response(arm, resp["json"])
        except AdapterError as ex:
            rec.update({"result": "bad_provider_shape", "error": str(ex)})
            rec["raw_file"] = rd.save_raw(unit["unit_id"], n, {"unit_id": unit["unit_id"], "attempt": n,
                                                              "provider_json": resp["json"]})
            rd.append("attempts.jsonl", rec)
            return {"outcome": "unavailable", "attempts": n, "error": "provider response shape not understood"}
        budget.count_usage(arm["arm_id"], parsed["usage"])
        rec.update({"result": "response", "finish": parsed["finish"], "finish_raw": parsed["finish_raw"],
                    "served_model": parsed["served_model"], "usage": parsed["usage"], "timing": parsed["timing"],
                    "elapsed_ms": resp.get("elapsed_ms"), "http_status": resp.get("http_status")})
        rec["raw_file"] = rd.save_raw(unit["unit_id"], n, {"unit_id": unit["unit_id"], "attempt": n,
                                                          "text": parsed["text"], "provider_json": resp["json"]})
        outcome, pred, needs_repair = _classify(scorer, gold, parsed["text"], parsed["finish"])
        rec["parse"] = "unparseable" if needs_repair else ("ok" if pred is not None else "n/a")
        rd.append("attempts.jsonl", rec)
        if outcome:
            return {"outcome": outcome, "attempts": n, "pred": pred, "text": parsed["text"],
                    "served_model": parsed["served_model"], "finish": parsed["finish"], "repaired": use_repair}
        if repairs_used < repairs_allowed and n < max_att:
            repairs_used += 1
            use_repair, last = True, "repair"
            continue
        return {"outcome": "invalid", "attempts": n, "pred": None, "text": parsed["text"],
                "served_model": parsed["served_model"], "finish": parsed["finish"], "repaired": use_repair}
    return {"outcome": "unavailable", "attempts": n, "error": "attempt limit reached without an answer"}


# ---------------------------------------------------------------- budget
class Budget:
    """Counts calls, tokens and time against the arm limits and run caps. A cap stops the run cleanly:
    the current unit is left without an outcome (UNRUN) and the stop reason is recorded."""

    def __init__(self, cfg, arms, prior_attempts, clock=time.monotonic):
        self.caps = cfg.get("run_caps") or {}
        self.lim = {a["arm_id"]: (a.get("limits") or {}) for a in arms}
        self.calls = {a["arm_id"]: 0 for a in arms}
        self.tok_in = {a["arm_id"]: 0 for a in arms}
        self.tok_out = {a["arm_id"]: 0 for a in arms}
        for rec in prior_attempts:
            aid = rec["unit_id"].split("/", 1)[0]
            if aid in self.calls:
                self.calls[aid] += 1
                u = rec.get("usage") or {}
                self.tok_in[aid] += u.get("input_tokens") or 0
                self.tok_out[aid] += u.get("output_tokens") or 0
        self.clock, self.t0 = clock, clock()
        self.stop_reason = None

    def check(self, aid):
        lim, caps = self.lim[aid], self.caps
        rules = [
            (lim.get("max_calls"), self.calls[aid], f"{aid}: limits.max_calls"),
            (lim.get("max_input_tokens_total"), self.tok_in[aid], f"{aid}: limits.max_input_tokens_total"),
            (lim.get("max_output_tokens_total"), self.tok_out[aid], f"{aid}: limits.max_output_tokens_total"),
            (caps.get("max_calls_total"), sum(self.calls.values()), "run_caps.max_calls_total"),
            (caps.get("max_elapsed_s"), self.clock() - self.t0, "run_caps.max_elapsed_s"),
        ]
        for cap, used, name in rules:
            if isinstance(cap, (int, float)) and used >= cap:
                self.stop_reason = f"{name} reached ({used} of {cap})"
                return self.stop_reason
        return None

    def count_call(self, aid):
        self.calls[aid] += 1

    def count_usage(self, aid, usage):
        self.tok_in[aid] += (usage or {}).get("input_tokens") or 0
        self.tok_out[aid] += (usage or {}).get("output_tokens") or 0


# ---------------------------------------------------------------- the run
def execute(manifest, cfg, arms, cases, golds, out_dir, transport, scorer, *, prompt, retry_suffix,
            environ=None, sleep=time.sleep, clock=time.monotonic):
    """Run (or resume) every planned unit. Returns the run status dict."""
    rd = RunDir(out_dir)
    rd.lock()
    try:
        rd.open(manifest)
        return _execute(rd, manifest, cfg, arms, cases, golds, transport, scorer, prompt=prompt,
                        retry_suffix=retry_suffix, environ=environ, sleep=sleep, clock=clock)
    finally:
        rd.unlock()


def _execute(rd, manifest, cfg, arms, cases, golds, transport, scorer, *, prompt, retry_suffix, environ, sleep, clock):
    arms_by = {a["arm_id"]: a for a in arms}
    cases_by = {c["case_id"]: c for c in cases}
    units = plan_units(manifest)
    reconciled = reconcile(rd, units, arms_by, scorer)       # r7: before any send; refuses or recovers
    prior = rd.attempts()
    done = {r["unit_id"] for r in rd.results()}
    per_unit = {}
    for a in prior:
        per_unit[a["unit_id"]] = per_unit.get(a["unit_id"], 0) + 1
    budget = Budget(cfg, arms, prior, clock=clock)
    stopped = None
    for u in units:
        if u["unit_id"] in done:
            continue
        case = cases_by[u["case_id"]]
        res = run_unit(u, arms_by[u["arm_id"]], case, golds[u["case_id"]], rd=rd, transport=transport,
                       scorer=scorer, prompt=prompt, retry_suffix=retry_suffix, protocol=manifest["protocol"],
                       prior_attempts=per_unit.get(u["unit_id"], 0), budget=budget, environ=environ, sleep=sleep)
        if res is None:
            stopped = budget.stop_reason
            break
        row = {"unit_id": u["unit_id"], "arm_id": u["arm_id"], "case_id": u["case_id"], "trial": u["trial"],
               "slice": case["slice"], "outcome": res["outcome"], "attempts": res["attempts"],
               "served_model": res.get("served_model"), "finish": res.get("finish"),
               "repaired": res.get("repaired", False), "error": res.get("error"),
               # r7.1 (REC-04b): the row says when its outcome was decided from the ledger after a stop, not from a fresh answer
               "resumed_from_stored_answer": bool(res.get("resumed_from_stored_answer")),
               "resumed_from_record": bool(res.get("resumed_from_record"))}
        if res.get("unavailable_reason"):           # r7.2 (R-14): for example replay_identity; the report counts these
            row["unavailable_reason"] = res["unavailable_reason"]
        if res["outcome"] == "scored":
            row["score"] = scorer.evaluate_response(res["pred"], golds[u["case_id"]])
            row["pred_statuses"] = {d: c["status"] for d, c in res["pred"]["days"].items()}
            row["pred"] = res["pred"]
        elif res["outcome"] == "invalid":
            row["score"] = scorer.evaluate_response(res.get("pred"), golds[u["case_id"]])
        rd.append("results.jsonl", row)
        done.add(u["unit_id"])
    results = rd.results()
    status = {"manifest_hash": manifest["manifest_hash"], "planned_units": len(units),
              "terminal_units": len(results), "unrun_units": len(units) - len(results),
              "outcomes": {o: sum(1 for r in results if r["outcome"] == o) for o in OUTCOMES},
              "attempts_total": len(rd.attempts()), "stopped": stopped, "transport": transport.name,
              "recovered_from_raw": reconciled["recovered"], "runner_edition": RUNNER_EDITION, "updated": now_utc()}
    # As in the v1 harness: COMPLETE only when every planned unit produced a model answer (scored, invalid or an
    # explicit refusal). Units with no answer (unavailable, truncated, route-denied) leave the run INCOMPLETE even
    # though every unit has ended; units never attempted leave it STOPPED (a cap) or INCOMPLETE.
    no_answer = sum(status["outcomes"][o] for o in ("unavailable", "truncated", "route_denied"))
    status["units_without_answer"] = no_answer
    status["run_status"] = ("STOPPED" if stopped else
                            "COMPLETE" if status["unrun_units"] == 0 and no_answer == 0 else "INCOMPLETE")
    rd.write_status(status)
    return status


# ---------------------------------------------------------------- dry-run packet
def dry_run_packet(manifest, cfg, arms, cases, *, prompt, image_dims=None):
    """What a run WOULD send, without building a transport. One scrubbed example request per arm."""
    units = plan_units(manifest)
    example_case = cases[0]
    img = open(example_case["png_path"], "rb").read()
    per_arm = []
    for a in arms:
        url, headers, payload = build_request(a, img, "image/png", prompt, credential=None)
        n_units = sum(1 for u in units if u["arm_id"] == a["arm_id"])
        lim = a.get("limits") or {}
        per_arm.append({
            "arm_id": a["arm_id"], "role": a.get("role"), "provider": a["provider"], "route": a["route"],
            "endpoint": url, "model_requested": a.get("model_requested"), "status": a.get("status"),
            "dispatch_enabled": a.get("dispatch_enabled"), "planned_units": n_units,
            "max_calls_if_every_unit_uses_every_attempt": n_units * int(lim.get("max_attempts_per_trial") or 1),
            "example_request": {"url": url, "header_names": sorted(headers), "payload": _scrub_payload(payload)},
            "credential_env": a.get("credential_env"),
        })
    return {"schema": "mmeval-dry-run/1", "generated": now_utc(), "manifest_hash": manifest["manifest_hash"],
            "dispatch": "DISABLED in this packet: no transport was constructed and nothing was sent",
            "data_class": manifest["data_class"], "trials": manifest["protocol"]["trials"],
            "cases": len(cases), "planned_units_total": len(units), "arms": per_arm,
            "run_caps": cfg.get("run_caps"), "unit_order_first_6": [u["unit_id"] for u in units[:6]]}
