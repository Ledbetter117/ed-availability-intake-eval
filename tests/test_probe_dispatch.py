"""Probe controls use synthetic inputs only; no provider or local model is called."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TREE = Path(sys.argv.pop(1))
sys.path[:0] = [str(TREE), str(TREE / "probe")]
import probe_score as P
import probe_b as B
from mmeval import config as C, transport as T


def arm():
    return {"arm_id": "probe-test", "provider": "openai_compatible_local", "route": "local",
            "endpoint": "http://127.0.0.1:9/v1/chat/completions", "model_requested": "synthetic-test",
            "modalities": ["text", "image"], "image_capability_verified": True,
            "credential_env": "ED_LOCAL_API_KEY", "allowed_data_classes": ["public_synthetic", "private_local_only"],
            "status": "ready", "dispatch_enabled": True,
            "limits": {"max_calls": 1, "max_attempts_per_trial": 1, "timeout_s": 1}}


class ProbeTests(unittest.TestCase):
    def test_authentication_reaches_shared_transport_and_cap_is_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            config = Path(d) / "config.json"
            config.write_text(json.dumps({"dispatch": {"enabled": True}, "arms": [arm()]}), encoding="utf-8")
            P.load_local_arms(str(config), str(TREE))
            with patch.dict(os.environ, {"ED_LOCAL_API_KEY": "synthetic-local-token"}), patch.object(P, "load_image_b64", return_value=(base64.b64encode(b"fake").decode(), "image/jpeg")):
                response = {"json": {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}}
                with patch.object(T.HttpTransport, "send", return_value=response) as send:
                    self.assertEqual(P.call_vision("probe-test", None, "not-read", "synthetic"), "{}")
                    self.assertEqual(send.call_args.args[2]["Authorization"], "Bearer synthetic-local-token")
                    with self.assertRaisesRegex(RuntimeError, "call limit"):
                        P.call_vision("probe-test", None, "not-read", "synthetic")
                    self.assertEqual(send.call_count, 1)

    def test_missing_credential_refuses_before_reading_photo(self):
        P.ARMS = {"probe-test": arm()}
        P.CALLS.clear()
        with patch.dict(os.environ, {}, clear=True), patch.object(P, "load_image_b64") as read:
            with self.assertRaisesRegex(RuntimeError, "credential variable"):
                P.call_vision("probe-test", None, "not-read", "synthetic")
            read.assert_not_called()

    def test_disabled_configuration_clears_previous_arms(self):
        with tempfile.TemporaryDirectory() as d:
            config = Path(d) / "config.json"
            config.write_text(json.dumps({"dispatch": {"enabled": False}, "arms": [arm()]}), encoding="utf-8")
            with self.assertRaises(C.ConfigError):
                P.load_local_arms(str(config), str(TREE))
            self.assertEqual(P.ARMS, {})

    def test_baseline_selects_one_arm_and_rejects_duplicate_or_incomplete_cases(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            cases = [f"case-{i:02}" for i in range(40)]
            identity = C.arm_identity(arm())
            (path / "manifest.json").write_text(json.dumps({"data_class": "public_synthetic", "arms": [identity], "case_set": {"id": "published-40", "cases": [[c, "png", "truth"] for c in cases]}}), encoding="utf-8")
            rows = [{"arm_id": "probe-test", "case_id": c, "trial": 1, "outcome": "scored", "score": {"day_accuracy": 1}} for c in cases]
            other = [{"arm_id": "other", "case_id": c, "trial": 1, "outcome": "invalid"} for c in cases]
            results = path / "results.jsonl"
            results.write_text("\n".join(json.dumps(r) for r in rows + other), encoding="utf-8")
            baseline = B.baseline_from_file(d, "probe-test")
            self.assertEqual((baseline["errors"], baseline["documents"], baseline["arm_identity"]), (0, 40, identity))
            for invalid in (rows[:-1], rows[:-1] + [rows[0]]):
                results.write_text("\n".join(json.dumps(r) for r in invalid), encoding="utf-8")
                with self.assertRaises(ValueError):
                    B.baseline_from_file(d, "probe-test")

    def test_probe_output_refusal_preserves_previous_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "previous.txt"
            marker.write_text("preserve", encoding="utf-8")
            with patch.object(sys, "argv", ["probe_score.py", "--arm-config", "unused", "--amendment-02-frozen", "--out", d]), patch.object(P, "selftest", return_value=0):
                with self.assertRaisesRegex(SystemExit, "not empty"):
                    P.main()
            class Args:
                mock = False
                out = d
            with self.assertRaisesRegex(SystemExit, "not empty"):
                B.run(Args())
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProbeTests))
    bad = len(result.failures) + len(result.errors)
    print(f"{result.testsRun - bad} PASS / {bad} FAIL / 0 UNVERIFIED")
    sys.exit(bool(bad))
