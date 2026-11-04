"""Security regressions using synthetic bytes only; no provider or model is called."""
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "probe")]
import run_eval as legacy
import probe_score as photo
import probe_b
from mmeval import config as C, transport as T
from PIL import Image

URL = "https://api.openai.com/v1/chat/completions"
ARM = {"arm_id": "security-test", "provider": "openai", "route": "cloud"}


def response(body):
    stream = io.BytesIO(body)
    stream.status = 200
    return stream


class PublicSecurityTests(unittest.TestCase):
    def test_legacy_success_reflection_rejected_for_short_and_long_credentials(self):
        for token in ("tiny5", "synthetic-security-credential-only"):
            body = json.dumps({token: {"content": token, "count": 7}}).encode()
            with patch.object(T.OPENER, "open", return_value=response(body)), patch.object(legacy.urllib.request, "urlopen", return_value=response(body)):
                with self.assertRaisesRegex(RuntimeError, "credential reflection") as error:
                    legacy._post(URL, {"Authorization": "Bearer " + token}, {}, tries=1)
            self.assertNotIn(token, str(error.exception))

    def test_legacy_error_reflection_redacted_for_short_credentials(self):
        token = "tiny5"
        error = urllib.error.HTTPError(URL, 401, "unauthorized", {}, io.BytesIO(token.encode()))
        with patch.object(T.OPENER, "open", side_effect=error), patch.object(legacy.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                legacy._post(URL, {"Authorization": "Bearer " + token}, {}, tries=1)
        self.assertNotIn(token, str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))

    def test_legacy_uses_no_redirect_no_proxy_transport(self):
        with patch.object(T.OPENER, "open", return_value=response(b'{"ok":true}')) as opened, patch.object(legacy.urllib.request, "urlopen", side_effect=AssertionError("unsafe default opener")):
            self.assertEqual(legacy._post(URL, {}, {}), {"ok": True})
            self.assertEqual(opened.call_count, 1)
        self.assertTrue(any(isinstance(h, T._RefuseRedirect) for h in T.OPENER.handlers))
        self.assertFalse(any(getattr(h, "proxies", {}) for h in T.OPENER.handlers))
        with self.assertRaises(urllib.error.HTTPError):
            T._RefuseRedirect().redirect_request(legacy.urllib.request.Request(URL), io.BytesIO(), 302, "redirect", {}, "https://example.invalid")

    def test_legacy_unknown_destination_is_refused_before_open(self):
        with patch.object(T.OPENER, "open") as opened, patch.object(legacy.urllib.request, "urlopen", side_effect=AssertionError("unsafe default opener")):
            with self.assertRaises(RuntimeError):
                legacy._post("https://example.invalid", {}, {})
            opened.assert_not_called()

    def test_large_success_and_error_bodies_are_bounded_and_discarded(self):
        for status in (200, 401):
            body = b"x" * 1025
            stream = response(body)
            error = urllib.error.HTTPError(URL, status, "error", {}, stream)
            with patch.object(T, "MAX_RESPONSE_BYTES", 1024, create=True), patch.object(T.OPENER, "open", **({"return_value": stream} if status == 200 else {"side_effect": error})):
                with self.assertRaises(T.TransportError) as caught:
                    T.HttpTransport().send(ARM, URL, {}, {}, 1)
            self.assertIsNone(caught.exception.body)
            self.assertIn("limit", str(caught.exception))
            self.assertFalse(caught.exception.transient)

    def test_arm_id_cannot_be_an_output_path(self):
        cfg = json.loads((ROOT / "configs/arms.queued.json").read_text(encoding="utf-8"))
        original = cfg["arms"][0]
        for ident in ("../escape", "x/../../escape", "C:\\escape", "../", ".", "CON", "name:stream", "a\nheading"):
            with self.assertRaises(C.ConfigError):
                C.validate_arm(original | {"arm_id": ident})
        self.assertEqual(C.validate_arm(original | {"arm_id": "local-1.ok"})["arm_id"], "local-1.ok")

    def test_photo_decoding_restricts_formats_despite_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "photo.jpg"
            Image.new("RGB", (16, 16)).save(fake, format="BMP")
            with self.assertRaises((ValueError, OSError)):
                photo.load_image_b64(fake)
            for fmt in ("PNG", "JPEG"):
                Image.new("RGB", (16, 16), "white").save(fake, format=fmt)
                data, kind = photo.load_image_b64(fake)
                self.assertEqual(kind, "image/jpeg")
                self.assertTrue(base64.b64decode(data).startswith(b"\xff\xd8"))

    def test_photo_input_size_and_pixels_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "photo.png"
            Image.new("RGB", (16, 16)).save(image)
            with patch.object(photo, "MAX_PHOTO_BYTES", 1, create=True), patch.object(Image, "open", wraps=Image.open) as opened:
                with self.assertRaisesRegex(ValueError, "size"):
                    photo.load_image_b64(image)
                opened.assert_not_called()
            with patch.object(photo, "MAX_PHOTO_PIXELS", 10, create=True):
                with self.assertRaisesRegex(ValueError, "pixel"):
                    photo.load_image_b64(image)

    def test_private_map_cannot_override_identity_or_escape_photo_folder(self):
        docs = [{"doc_id": "G1", "kind": "grid"}]
        base = {"month": "2026-07", "photo": "valid.jpg", "pair": None, "legend": "synthetic"}
        for bad in ({"doc_id": "../escaped"}, {"kind": "list"}, {"photo": "../private.jpg"}, {"photo": "C:\\private.jpg"}, {"pair": "a/b.jpg"}):
            with self.assertRaises(ValueError):
                probe_b.enrich(docs, {"G1": base | bad})
        self.assertEqual(probe_b.enrich(docs, {"G1": base})[0]["photo"], "valid.jpg")


if __name__ == "__main__":
    unittest.main(verbosity=2)
