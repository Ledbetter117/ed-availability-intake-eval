"""Run public offline software checks; refuse a failed child on every platform.

Missing private raw responses and unavailable reference environments remain
explicit UNVERIFIED outcomes in the test output, not inferred passes.
No model endpoint or paid provider is invoked. Some tests use synthetic localhost HTTP.
"""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
commands = [["tests/test_harness.py", "--allow-unverified"]]
commands += [[f"tests/{name}.py", "."] for name in (
    "test_r71", "test_r72", "test_r73", "test_ft1_scripted", "test_unlock_race",
    "test_resume_reporting", "test_r74", "test_probe_dispatch",
)]
commands += [["packaging/tests/test_release_wrapper.py", "packaging/run_ed_i.py"]]
commands += [["tests/test_public_security.py"]]
commands += [["tests/test_parse_response_bounds.py"]]
failed = []
for args in commands:
    print("CHECK " + " ".join(args), flush=True)
    try:
        code = subprocess.run([sys.executable, "-B", "-X", "utf8", *args], cwd=root, timeout=180).returncode
    except subprocess.TimeoutExpired:
        code = "TIMEOUT (180 seconds)"
    if code:
        failed.append({"command": args, "exit_code": code})
if failed:
    print("FAILED CHILD CHECKS:", failed)
    raise SystemExit(1)
print("All child commands completed without a reported failure. Read UNVERIFIED limits above.")
