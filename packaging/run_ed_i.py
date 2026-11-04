"""run_ed_i.py -- the ED (i) availability-intake evaluation, internal edition v1.2rc4 (ORCA-ED-DELIVER-NOW-20261103-r1).

No API key, no model call and no network are used by any command here.
  python -B run_ed_i.py verify   every offline check of the harness on a TEMPORARY copy of tree/ (about 3 minutes):
                                 test_harness (--allow-unverified), test_r71, test_r72, test_r73, test_ft1_scripted, test_unlock_race,
                                 test_resume_reporting. Exit 0 only when no check FAILS and the installation manifest matches before and after.
  python -B run_ed_i.py plan     the multi-model runner's dry run on a temporary copy: verify-config, check-cases and a request plan
                                 packet for configs/arms.capability-check.json (sends nothing)
Each command writes runs/<UTC time>-<command>/ with logs and SUMMARY.md, and checks tree/ against INSTALL-MANIFEST.json before and
after. The published results are in tree/README.md, tree/results/summary.md and tree/results_haiku/summary.md."""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE, RUNS = HERE / "tree", HERE / "runs"
SUITES = [("test_harness", ["tests/test_harness.py", "--allow-unverified"]), ("test_r71", ["tests/test_r71.py", "{T}"]),
          ("test_r72", ["tests/test_r72.py", "{T}"]), ("test_r73", ["tests/test_r73.py", "{T}"]),
          ("test_ft1_scripted", ["tests/test_ft1_scripted.py", "{T}"]), ("test_unlock_race", ["tests/test_unlock_race.py", "{T}"]),
          ("test_resume_reporting", ["tests/test_resume_reporting.py", "{T}"]),
          ("test_r74", ["tests/test_r74.py", "{T}"]),
          ("test_probe_dispatch", ["tests/test_probe_dispatch.py", "{T}"]),
          ("test_release_wrapper", [str(HERE / "tests/test_release_wrapper.py"), str(HERE / "run_ed_i.py")])]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def installed_ok():
    try:
        man = json.loads((HERE / "INSTALL-MANIFEST.json").read_text(encoding="utf-8"))
        if not isinstance(man["files"], list) or not man["files"]:
            raise ValueError("manifest contains no files")
        bad = []
        for row in man["files"]:
            p = (HERE / row["path"]).resolve()
            if not p.is_relative_to(HERE.resolve()) or not p.is_file() or sha(p) != row["sha256"]:
                bad.append(row["path"])
        return {"files": len(man["files"]), "mismatched": bad}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"files": 0, "mismatched": ["INSTALL-MANIFEST.json: " + str(exc)]}


def call(args, cwd, log):
    p = subprocess.run([sys.executable, "-B", "-X", "utf8"] + [str(a) for a in args], cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=2400,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))
    Path(log).write_text("# %s\n# exit %s\n%s\n--- stderr ---\n%s" % (args, p.returncode, p.stdout, p.stderr), encoding="utf-8")
    return p.returncode, p.stdout + p.stderr


def run_cmd(name, body):
    before = installed_ok()
    d = RUNS / ("%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"), name))
    d.mkdir(parents=True)
    if before["mismatched"]:
        message = "# REFUSED: installation integrity check failed\n\nNo command executed. Mismatched files: %s\n" % before["mismatched"]
        (d / "SUMMARY.md").write_text(message, encoding="utf-8")
        print(message)
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="ed-i-%s-" % name))
    try:
        t = tmp / "tree"
        shutil.copytree(TREE, t, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        code, lines = body(t, d)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    after = installed_ok()
    if after["mismatched"]:
        code = 1
        lines += ["FAIL: installed files changed during execution; the result is not accepted."]
    text = ["# ED (i) v1.2rc4 internal edition: %s" % name, "", "Run folder: `%s`" % d, "Python: %s" % sys.version.split()[0], ""] + lines + [
        "", "Installed files checked before: %d, mismatched %s; after: mismatched %s. Temporary copy removed: %s." % (
            before["files"], before["mismatched"] or "none", after["mismatched"] or "none", not tmp.exists())]
    (d / "SUMMARY.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    print("\n".join(text))
    return code


def verify(t, d):
    rows, worst = ["| Suite | Exit | Final line |", "|---|---|---|"], 0
    for name, args in SUITES:
        code, out = call([t / args[0]] + [a.replace("{T}", str(t)) for a in args[1:]], t, d / ("%s.log" % name))
        last = [l for l in out.splitlines() if re.search(r"\d+ PASS", l)]
        rows.append("| %s | %s | %s |" % (name, code, (last[-1].strip() if last else "no summary line (crash?)")[:150]))
        worst = max(worst, 1 if code != 0 else 0)
    return worst, ["Every check runs offline on a temporary copy. UNVERIFIED lines are checks this computer cannot run (for example "
                   "re-scoring needs raw answers that are not shipped, and the network layer here withholds partial HTTP bodies); they "
                   "are not failures. Exit %s." % worst, ""] + rows


def plan(t, d):
    steps = [("verify-config", ["mm_run.py", "verify-config", "--config", "configs/arms.capability-check.json"]),
             ("check-cases", ["mm_run.py", "check-cases", "--data", "data"]),
             ("plan", ["mm_run.py", "plan", "--config", "configs/arms.capability-check.json", "--data", "data", "--out", d / "packet.json"])]
    rows, worst = ["| Step | Exit | Last line |", "|---|---|---|"], 0
    for name, args in steps:
        code, out = call(args, t, d / ("%s.log" % name))
        tail = [l for l in out.splitlines() if l.strip()]
        rows.append("| %s | %s | %s |" % (name, code, (tail[-1].strip() if tail else "")[:150]))
        worst = max(worst, 0 if code == 0 else 1)
    return worst, ["Dry run only: no transport is built and nothing is sent. `packet.json` is the plan of every request the "
                   "capability-check arms would make, with one scrubbed example per arm. Exit %s." % worst, ""] + rows


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("verify", "plan"):
        print(__doc__); return 2
    return run_cmd(sys.argv[1], {"verify": verify, "plan": plan}[sys.argv[1]])


if __name__ == "__main__":
    sys.exit(main())
