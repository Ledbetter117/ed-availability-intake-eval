"""Transport layer (r7.3). Three implementations:

  DenyTransport      the default. Any send() is an error: dry-runs and offline replay never touch a network.
  RecordedTransport  offline test double. Returns canned responses or raises canned exceptions, and keeps a
                     log of what would have been sent (image bytes replaced by their hash, secrets removed).
  HttpTransport      real HTTP. Constructed only by the dispatch gate in runner.py. It re-checks the
                     destination against the arm's route on every request, so a local arm cannot reach a
                     cloud host even if a request was built incorrectly.

A transport never retries on its own. Retries are attempts, and the runner records every attempt.

r7.2 (DESIGN-r2 V4, Red R-3, Black): HttpTransport classifies a failure by how far the exchange got.
  before the request was completely sent (connect or send error)   transient: safe to retry
  sent, but no valid status line came back (timeout, reset, close)  transient and AMBIGUOUS: the provider may have it;
                                                                    the runner resends only under protocol.ambiguous_resend
  2xx status received, then the body could not be read or decoded   MALFORMED: non-transient, never retried; whatever
                                                                    bytes arrived are kept for the raw record

r7.3 (FT1-D1, ORCA-ED-DELIVER-NOW-20261103-r1): the body is read with read1(), one system call at a time, so the bytes that
arrived before a timeout or a reset are kept, as promised above (r7.2 kept them only on IncompleteRead). The classification is
unchanged. Bytes that a network layer withholds from the application cannot be kept by any client.
"""
import hashlib, http.client, json, time, urllib.error, urllib.request

from .config import endpoint_allowed


class TransportDenied(RuntimeError):
    """A send was attempted where no transport is allowed (dry-run, replay, or a route violation)."""


class TransportError(RuntimeError):
    """The provider or network failed; no model answer was obtained.

    r7.2 fields (all optional, default off): ambiguous (the request may have reached the provider), malformed (a 2xx whose
    body could not be read or decoded; body/body_truncated hold what arrived, redacted), reason (a machine-readable cause,
    for example 'replay_identity')."""

    def __init__(self, message, *, status=None, transient=False, ambiguous=False, malformed=False, body=None,
                 body_truncated=False, reason=None):
        super().__init__(message)
        self.status, self.transient = status, transient
        self.ambiguous, self.malformed, self.reason = bool(ambiguous), bool(malformed), reason
        self.body, self.body_truncated = body, bool(body_truncated)


RAW_BODY_LIMIT = 65536            # characters of a malformed body kept in the raw record
READ_PIECE = 65536                # bytes asked of each read1() call while reading a body (r7.3, FT1-D1)
MAX_RESPONSE_BYTES = 16 * 1024 * 1024  # hard cap before JSON parsing; also applies to HTTP error bodies


TRANSIENT_HTTP = {408, 409, 429, 500, 502, 503, 504, 529}


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """r7.1 (F17, R-1): a redirect is a new destination. urllib's default handler follows 301/302/303 for a POST (as a GET)
    and re-sends every non-content header, including Authorization and x-api-key, to the new host without the route check.
    Here every redirect is refused; the response becomes an HTTP error the runner records as a terminal transport error."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused by the harness (not followed)", headers, fp)


# r7.1 (F17, R-1): no proxy from the environment or the system registry (HTTP_PROXY / HTTPS_PROXY would otherwise carry a local
# arm's images, or a cloud credential, through a third host), and no redirect following.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirect())


def secrets_in(headers):
    found = []
    for k, v in (headers or {}).items():
        if str(k).lower() in ("authorization", "x-api-key", "api-key") and isinstance(v, str) and v:
            found.append(v)
            if v.lower().startswith("bearer "):
                found.append(v[7:])
    return sorted({s for s in found if s}, key=len, reverse=True)


def redact(text, secrets):
    for s in secrets:
        text = text.replace(s, "[REDACTED]")
    return text


def _redact_response(obj, secrets):
    if isinstance(obj, str):
        return redact(obj, secrets)
    if isinstance(obj, dict):
        return {redact(k, secrets): _redact_response(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_response(v, secrets) for v in obj]
    return obj


def _scrub_payload(obj):
    """Copy of a request payload with base64 images replaced by a short hash, for logs and packets."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("data", "url", "image_url") and isinstance(v, str) and len(v) > 256:
                out[k] = "<image sha256=" + hashlib.sha256(v.encode()).hexdigest()[:16] + f" len={len(v)}>"
            elif k == "images" and isinstance(v, list):
                out[k] = ["<image sha256=" + hashlib.sha256(str(x).encode()).hexdigest()[:16] + ">" for x in v]
            else:
                out[k] = _scrub_payload(v)
        return out
    if isinstance(obj, list):
        return [_scrub_payload(x) for x in obj]
    return obj


class DenyTransport:
    name = "deny"

    def send(self, arm, url, headers, payload, timeout_s):
        raise TransportDenied("no transport is allowed in this mode (dry-run or offline replay)")


class RecordedTransport:
    """Offline double. `script` is a list; each item is a response dict, or an Exception to raise."""
    name = "recorded"

    def __init__(self, script, trusted_local_hosts=()):
        self.script = list(script)
        self.sent = []
        self.trusted = tuple(trusted_local_hosts)

    def send(self, arm, url, headers, payload, timeout_s):
        if not endpoint_allowed(arm, url, self.trusted):
            raise TransportDenied(f"route violation: {arm.get('arm_id')} may not send to {url}")
        self.sent.append({"arm_id": arm.get("arm_id"), "url": url,
                          "headers": sorted(k for k in headers),            # names only, never values
                          "payload": _scrub_payload(payload)})
        if not self.script:
            raise TransportError("recorded transport exhausted", transient=False)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return {"json": item, "elapsed_ms": 1, "http_status": 200}


class HttpTransport:
    name = "http"

    def __init__(self, trusted_local_hosts=()):
        self.trusted = tuple(trusted_local_hosts)

    def send(self, arm, url, headers, payload, timeout_s):
        if not endpoint_allowed(arm, url, self.trusted):
            raise TransportDenied(f"route violation: {arm.get('arm_id')} may not send to {url}")
        secrets = secrets_in(headers)
        body = json.dumps(payload).encode()
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            r = OPENER.open(req, timeout=timeout_s)          # r7.1: no proxy, no redirect (see OPENER); returns after the status line
        except urllib.error.HTTPError as e:
            try:
                raw_error = e.read(MAX_RESPONSE_BYTES + 1)
                if len(raw_error) > MAX_RESPONSE_BYTES:
                    raise TransportError(f"HTTP {e.code}: response size limit exceeded; body discarded",
                                         status=e.code, reason="response_size_limit") from None
                detail = redact(raw_error.decode(errors="replace"), secrets)[:300]
            except (OSError, http.client.HTTPException):
                detail = "(the error body could not be read)"
            finally:
                e.close()
            raise TransportError(f"HTTP {e.code}: {detail}", status=e.code, transient=e.code in TRANSIENT_HTTP) from None
        except urllib.error.URLError as e:
            # urllib raises URLError only while connecting or sending: the request was not completely sent
            # r7.2-p3 (Red R-ED-9): "not completely sent": the server may have the request line, never the whole body
            raise TransportError(f"network error before the request was completely sent: {redact(str(e.reason), secrets)}",
                                 transient=True) from None
        except (OSError, http.client.HTTPException) as e:
            # the request was sent and no valid status line came back: the provider may have received it
            raise TransportError(f"network error after the request was sent, before any status line ({type(e).__name__}: "
                                 f"{redact(str(e), secrets)[:200]}); the provider may have received it",
                                 transient=True, ambiguous=True) from None
        with r:
            status = r.status
            pieces = []
            received = 0
            try:
                read1 = getattr(r, "read1", None)
                if read1 is None:                     # a response object without read1 (a test double): one read, as in r7.2
                    pieces.append(r.read(MAX_RESPONSE_BYTES + 1))
                    received = len(pieces[0])
                else:
                    # r7.3 (FT1-D1): read1 returns what one system call delivered, so the bytes that arrived before a timeout or a
                    # reset are already kept; r.read() lost them with the exception
                    while True:
                        piece = read1(min(READ_PIECE, MAX_RESPONSE_BYTES + 1 - received))
                        if not piece:
                            break
                        pieces.append(piece)
                        received += len(piece)
                        if received > MAX_RESPONSE_BYTES:
                            break
                    if received > MAX_RESPONSE_BYTES:
                        raise TransportError("response size limit exceeded; body discarded", status=status,
                                             malformed=True, reason="response_size_limit")
                    left = getattr(r, "length", None)
                    if isinstance(left, int) and left > 0:       # closed before Content-Length was met: the r7.2 IncompleteRead
                        raise http.client.IncompleteRead(b"".join(pieces), left)
                if received > MAX_RESPONSE_BYTES:
                    raise TransportError("response size limit exceeded; body discarded", status=status,
                                         malformed=True, reason="response_size_limit")
                data = json.loads(b"".join(pieces))
            except TransportError:
                raise
            except Exception as e:  # noqa: BLE001 -- anything after the status line is a malformed answer, never a retry
                raw = b"".join(pieces)
                if isinstance(e, http.client.IncompleteRead) and len(e.partial or b"") > len(raw):
                    raw = e.partial
                text = redact(raw.decode("utf-8", errors="replace"), secrets)
                raise TransportError(f"HTTP {status}: the response body could not be read or decoded ({type(e).__name__}: "
                                     f"{redact(str(e), secrets)[:160]}); recorded as malformed, not retried", status=status,
                                     transient=False, malformed=True, body=text[:RAW_BODY_LIMIT],
                                     body_truncated=len(text) > RAW_BODY_LIMIT) from None
        scrubbed = _redact_response(data, secrets)
        if scrubbed != data:
            text = json.dumps(scrubbed, ensure_ascii=False)
            raise TransportError("credential reflection in a successful response; redacted and excluded from scoring",
                                 status=status, malformed=True, transient=False, reason="credential_reflection",
                                 body=text[:RAW_BODY_LIMIT], body_truncated=len(text) > RAW_BODY_LIMIT)
        return {"json": data, "elapsed_ms": int((time.monotonic() - t0) * 1000), "http_status": status}
