#!/usr/bin/env python3
"""test_ft1_scripted.py -- FT1-D1 checks with NO sockets, NO child processes and NO file writes (ORCA-ED-DELIVER-NOW-20261103-r1).

The visible check of the guarded local repair unit (ops/guard_run.py refuses sockets, processes and writes outside the job folder).
Every check drives the REAL http.client.HTTPResponse over a scripted raw stream (the same BufferedReader path as a socket's
makefile), patched in as the transport's opener. The full test_r73.py (real loopback sockets) is the host acceptance.
Edition 2 adds CTRL-FT1-I/J/K, the hidden acceptance checks that the Qwen R2 edition failed (edition 1 is the unit's visible test).

    python -B test_ft1_scripted.py <tree>
"""
import http.client, io, json, os, sys
from unittest.mock import patch

TREE = os.path.abspath(sys.argv[1])
sys.path.insert(0, TREE)
sys.dont_write_bytecode = True
from mmeval import transport as T  # noqa: E402
from mmeval.transport import HttpTransport, TransportError  # noqa: E402

PART = b'{"choices": [{"message": {"content": "' + b"x" * 61 + b'"'      # 100 bytes of a body announced as 1000
OK_BODY = json.dumps({"choices": [{"message": {"content": "y" * 150000}, "finish_reason": "stop"}], "model": "loop"}).encode()
CL_HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
CH_HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
RES = []


def check(cid, name, ok, observed):
    RES.append((cid, ok))
    print(f"{'PASS' if ok else 'FAIL'} {cid} {name}  [{json.dumps(observed, default=str)[:240]}]")


class ScriptedRaw(io.RawIOBase):
    """Returns the scripted byte pieces one per read, then raises `end` (or returns b'' for an orderly close)."""
    def __init__(self, pieces, end):
        self.pieces, self.end = list(pieces), end

    def readable(self):
        return True

    def readinto(self, b):
        if self.pieces:
            c = self.pieces.pop(0)
            n = min(len(b), len(c))
            b[:n] = c[:n]
            if n < len(c):
                self.pieces.insert(0, c[n:])
            return n
        if self.end is None:
            return 0
        raise self.end


class ScriptedSock:
    def __init__(self, pieces, end):
        self.pieces, self.end = pieces, end

    def makefile(self, mode, *a, **k):
        return io.BufferedReader(ScriptedRaw(self.pieces, self.end))


def send(pieces, end):
    """One HttpTransport.send whose response is the real HTTPResponse over the scripted pieces: (result, error)."""
    def opener(req, timeout=None):
        r = http.client.HTTPResponse(ScriptedSock(pieces, end), method="POST")
        r.begin()
        return r
    a = {"arm_id": "loc", "role": "test", "provider": "openai_compatible_local", "route": "local",
         "endpoint": "http://127.0.0.1:9/v1/chat/completions", "credential_env": None}
    with patch.object(T.OPENER, "open", side_effect=opener):
        try:
            return HttpTransport().send(a, a["endpoint"], {}, {"x": 1}, 1), None
        except TransportError as ex:
            return None, ex


def facts(ex):
    return ex and {"status": ex.status, "transient": ex.transient, "ambiguous": ex.ambiguous, "malformed": ex.malformed,
                   "body_len": None if ex.body is None else len(ex.body), "msg": str(ex)[:140]}


def kept(ex, names):
    return (ex is not None and ex.malformed and not ex.transient and not ex.ambiguous and ex.status == 200
            and ex.body == PART.decode() and any(n in str(ex) for n in names))


def chunked(body, size):
    return b"".join(b"%x\r\n" % len(body[i:i + size]) + body[i:i + size] + b"\r\n" for i in range(0, len(body), size))


TIMEOUT = TimeoutError("timed out")
RESET = ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")

_, ex = send([CL_HEAD % 1000 + PART], TIMEOUT)
check("FT1-A", "Content-Length 1000: 100 body bytes arrive, then the read times out: the 100 bytes are the malformed body, status "
      "200, non-transient, not ambiguous, the message names TimeoutError", kept(ex, ("TimeoutError",)), facts(ex))
_, ex = send([CL_HEAD % 1000 + PART], RESET)
check("FT1-B", "Content-Length 1000: 100 body bytes arrive, then the connection is reset: the 100 bytes are kept, the message "
      "names ConnectionResetError", kept(ex, ("ConnectionResetError",)), facts(ex))
_, ex = send([CH_HEAD + chunked(PART, 4096)], TIMEOUT)
check("FT1-G", "chunked: one 100-byte chunk arrives, then the read times out: the 100 bytes are kept, the message names TimeoutError",
      kept(ex, ("TimeoutError",)), facts(ex))
_, ex = send([CL_HEAD % 1000 + PART], None)
check("CTRL-FT1-C2", "Content-Length 1000: 100 bytes, then an orderly close: kept, and the message is the unchanged IncompleteRead "
      "with 900 more expected", kept(ex, ("IncompleteRead",)) and "900 more expected" in str(ex), facts(ex))
nonjson = b"this is not json " * 3
_, ex = send([CL_HEAD % len(nonjson) + nonjson], None)
check("CTRL-FT1-D", "a complete non-JSON body is kept whole and named JSONDecodeError (unchanged)",
      ex is not None and ex.malformed and ex.status == 200 and ex.body == nonjson.decode() and "JSONDecodeError" in str(ex), facts(ex))
pieces = [CL_HEAD % len(OK_BODY)] + [OK_BODY[i:i + 19000] for i in range(0, len(OK_BODY), 19000)]
got, ex = send(pieces, None)
check("CTRL-FT1-E", "a valid Content-Length body of %d bytes arriving in %d pieces is returned whole" % (len(OK_BODY), len(pieces) - 1),
      ex is None and got and got["json"] == json.loads(OK_BODY) and got["http_status"] == 200, facts(ex))
got, ex = send([CH_HEAD, chunked(OK_BODY, 4096), b"0\r\n\r\n"], None)
check("CTRL-FT1-F", "a valid chunked body of %d bytes is returned whole" % len(OK_BODY),
      ex is None and got and got["json"] == json.loads(OK_BODY) and got["http_status"] == 200, facts(ex))


class ReadOnly:
    """test_r72's double: read() only (no read1, no length)."""
    status = 200

    def read(self):
        raise RESET

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


with patch.object(T.OPENER, "open", side_effect=lambda req, timeout=None: ReadOnly()):
    ex = None
    try:
        HttpTransport().send({"arm_id": "loc", "route": "local", "provider": "openai_compatible_local", "credential_env": None,
                              "endpoint": "http://127.0.0.1:9/v1/chat/completions"}, "http://127.0.0.1:9/v1/chat/completions", {}, {}, 1)
    except TransportError as e:
        ex = e
check("CTRL-FT1-H", "a response object with read() only still works: a reset is malformed, status 200, never ambiguous",
      ex is not None and ex.malformed and not ex.ambiguous and ex.status == 200 and ex.body == "", facts(ex))

# edition 2: the hidden acceptance checks written after the byte review of the Qwen R2 edition (it failed all three; v1.2rc2 passes)
_, ex = send([CH_HEAD + chunked(PART, 4096)], None)
check("CTRL-FT1-I", "chunked: the connection closes after one 100-byte chunk (http.client raises IncompleteRead inside the read): "
      "the 100 bytes are kept, the message names IncompleteRead, no unrelated error", ex is not None and ex.malformed
      and ex.status == 200 and ex.body == PART.decode() and "IncompleteRead" in str(ex) and "AttributeError" not in str(ex), facts(ex))
_, ex = send([CL_HEAD % 1000 + PART], TIMEOUT)
check("CTRL-FT1-J", "timeout: the recorded message names the real exception type first, not an internal wrapper",
      ex is not None and "(TimeoutError: " in str(ex), facts(ex))
_, ex = send([CL_HEAD % 1000 + PART], RESET)
check("CTRL-FT1-K", "reset: the recorded message names the real exception type first, not an internal wrapper",
      ex is not None and "(ConnectionResetError: " in str(ex), facts(ex))

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n{n_pass} PASS · {len(RES) - n_pass} FAIL  (tree: {TREE})")
sys.exit(0 if n_pass == len(RES) else 1)
