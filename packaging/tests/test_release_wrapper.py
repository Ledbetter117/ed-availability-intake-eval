"""Integrity gates on isolated fixtures; imports the wrapper without running its suites."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("release_wrapper", sys.argv.pop(1))
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tree = self.root / "tree"
        self.tree.mkdir()
        self.file = self.tree / "fixture.txt"
        self.file.write_text("known content", encoding="utf-8")
        (self.root / "INSTALL-MANIFEST.json").write_text(json.dumps({"files": [{"path": "tree/fixture.txt", "sha256": hashlib.sha256(self.file.read_bytes()).hexdigest()}]}), encoding="utf-8")
        for name, value in (("HERE", self.root), ("TREE", self.tree), ("RUNS", self.root / "runs")):
            p = patch.object(wrapper, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_clean_control_executes_once(self):
        calls = []
        result = wrapper.run_cmd("control", lambda t, d: (calls.append(t) or 0, ["synthetic control"]))
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0].exists())

    def test_changed_preimage_prevents_execution(self):
        self.file.write_text("changed", encoding="utf-8")
        calls = []
        self.assertNotEqual(wrapper.run_cmd("tampered", lambda t, d: (calls.append(t) or 0, [])), 0)
        self.assertEqual(calls, [])
        self.assertIn("REFUSED", next((self.root / "runs").glob("*/SUMMARY.md")).read_text(encoding="utf-8"))

    def test_change_during_execution_forces_failure(self):
        def changed(t, d):
            self.file.write_text("changed during run", encoding="utf-8")
            return 0, ["body returned zero"]
        self.assertNotEqual(wrapper.run_cmd("changed", changed), 0)

    def test_bad_manifest_refuses_execution(self):
        (self.root / "INSTALL-MANIFEST.json").write_text("{}", encoding="utf-8")
        calls = []
        self.assertNotEqual(wrapper.run_cmd("manifest", lambda t, d: (calls.append(t) or 0, [])), 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WrapperTests))
    bad = len(result.failures) + len(result.errors)
    print(f"{result.testsRun - bad} PASS / {bad} FAIL / 0 UNVERIFIED")
    sys.exit(bool(bad))
