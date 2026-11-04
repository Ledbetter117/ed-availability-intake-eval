"""Local authentication regressions. Uses synthetic responses and a temporary loopback server only."""
import http.server
import io
import json
import sys
import threading
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, sys.argv.pop(1))
from mmeval import config as C, runner as R, transport as T
from mmeval.adapters import build_request


def arm(endpoint="http://127.0.0.1:9/v1/chat/completions", credential="ED_LOCAL_API_KEY"):
    return {"arm_id": "local-test", "provider": "openai_compatible_local", "route": "local",
            "endpoint": endpoint, "model_requested": "synthetic-test", "modalities": ["text", "image"],
            "image_capability_verified": True, "allowed_data_classes": ["public_synthetic"],
            "credential_env": credential, "status": "ready", "dispatch_enabled": True,
            "limits": {"max_calls": 1, "max_attempts_per_trial": 1, "timeout_s": 3}}


class AuthenticationTests(unittest.TestCase):
    def test_reflected_long_and_short_credentials_never_reach_scoring(self):
        for token in ("synthetic-reflected-long-token", "tiny5"):
            response = io.BytesIO(json.dumps({"choices": [{"message": {"content": token}}], "usage": {"tokens": 7}}).encode())
            response.status = 200
            with patch.object(T.OPENER, "open", return_value=response):
                with self.assertRaises(T.TransportError) as ex:
                    T.HttpTransport().send(arm(), arm()["endpoint"], {"Authorization": "Bearer " + token}, {}, 1)
            error = ex.exception
            self.assertTrue(error.malformed)
            self.assertFalse(error.transient)
            self.assertEqual(error.reason, "credential_reflection")
            self.assertNotIn(token, str(error) + error.body)
            safe = json.loads(error.body)
            self.assertEqual(safe["choices"][0]["message"]["content"], "[REDACTED]")
            self.assertEqual(safe["usage"]["tokens"], 7)
            http_error = urllib.error.HTTPError(arm()["endpoint"], 401, "unauthorized", {}, io.BytesIO(token.encode()))
            with patch.object(T.OPENER, "open", side_effect=http_error):
                with self.assertRaises(T.TransportError) as ex:
                    T.HttpTransport().send(arm(), arm()["endpoint"], {"Authorization": "Bearer " + token}, {}, 1)
            self.assertNotIn(token, str(ex.exception))
            self.assertIn("[REDACTED]", str(ex.exception))

    def test_loopback_credential_and_unauthenticated_local(self):
        for host in ("127.0.0.1", "[::1]", "localhost"):
            self.assertEqual(C.validate_arm(arm(f"http://{host}:9/v1/chat/completions"))["credential_env"], "ED_LOCAL_API_KEY")
        self.assertIsNone(C.validate_arm(arm(credential=None))["credential_env"])

    def test_credential_cannot_leave_loopback(self):
        for host in ("192.168.1.20", "api.openai.com"):
            a = arm(f"http://{host}:9/v1/chat/completions")
            self.assertFalse(C.endpoint_allowed(a, a["endpoint"], ("192.168.1.20",)))
            with self.assertRaises(C.ConfigError):
                C.validate_arm(a, trusted_local_hosts=("192.168.1.20",))
            with patch.object(T.OPENER, "open") as opened:
                with self.assertRaises(T.TransportDenied):
                    T.HttpTransport(("192.168.1.20",)).send(a, a["endpoint"], {"Authorization": "Bearer synthetic-secret"}, {}, 1)
                opened.assert_not_called()

    def test_ollama_does_not_silently_drop_a_credential(self):
        with self.assertRaises(C.ConfigError):
            C.validate_arm(arm() | {"provider": "ollama_local"})

    def test_invalid_environment_variable_and_embedded_credentials_refused(self):
        for credential in ("not a variable", 7, ["key"]):
            with self.assertRaises(C.ConfigError):
                C.validate_arm(arm(credential=credential))
        with self.assertRaises(C.ConfigError):
            C.validate_arm(arm("http://user:secret@127.0.0.1:9/v1/chat/completions"))

    def test_missing_selected_local_credential_refuses_before_transport(self):
        a = arm()
        m = {"manifest_hash": "a" * 64, "data_class": "public_synthetic", "protocol": {}}
        cfg = {"dispatch": {"enabled": True}, "run_caps": {"max_calls_total": 1}}
        env = {R.ACK_ENV: "a" * 12}
        with patch.object(R, "HttpTransport") as transport:
            with self.assertRaisesRegex(R.RunRefused, "ED_LOCAL_API_KEY"):
                R.live_transport(cfg, [a], m, cli_dispatch=True, environ=env)
            transport.assert_not_called()
        self.assertIsInstance(R.live_transport(cfg, [a], m, cli_dispatch=True,
                              environ=env | {"ED_LOCAL_API_KEY": "synthetic-test-token"}), T.HttpTransport)

    def test_authenticated_loopback_request_and_error_redaction(self):
        received = []
        token = "synthetic-local-credential-012345"

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                body = (token if len(received) == 2 else json.dumps({"choices": [{"message": {"content": "synthetic response"}, "finish_reason": "stop"}]})).encode()
                self.send_response(401 if len(received) == 2 else 200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                a = C.validate_arm(arm(f"http://127.0.0.1:{server.server_port}/v1/chat/completions"))
                url, headers, payload = build_request(a, None, None, "synthetic test", token)
                response = T.HttpTransport().send(a, url, headers, payload, 3)
                self.assertEqual(response["http_status"], 200)
                self.assertEqual(received[0][0], "Bearer " + token)
                self.assertNotIn(token, json.dumps(payload))
                with self.assertRaises(T.TransportError) as ex:
                    T.HttpTransport().send(a, url, headers, payload, 3)
                self.assertNotIn(token, str(ex.exception))
                self.assertIn("[REDACTED]", str(ex.exception))
            finally:
                server.shutdown()
                thread.join(timeout=3)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AuthenticationTests))
    bad = len(result.failures) + len(result.errors)
    print(f"{result.testsRun - bad} PASS / {bad} FAIL / 0 UNVERIFIED (synthetic loopback; no model inference)")
    sys.exit(bool(bad))
