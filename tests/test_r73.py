#!/usr/bin/env python3
"""test_r73.py (edition 2) -- focused regressions for the r7.3 successor, v1.2rc3 (ORCA-ED-DELIVER-NOW-20261103-r1).

Each check states the CORRECT behaviour. On the v1.2rc2 tree the r7.3 checks (FT1-A, FT1-B, FT1-G, FT1-I) are expected to FAIL
(failing-first evidence); checks named CTRL-* are controls and must pass on both trees.

    python -B test_r73.py <tree> [--json out.json]

FT1-D1 (OPEN-DEFECTS-v1.2rc2.md): mmeval/transport.py promises (docstring lines 16-17) that after a 2xx status, when the body
cannot be read, "whatever bytes arrived are kept for the raw record". v1.2rc2 kept them only for IncompleteRead: a timeout or a
reset during the body read lost the bytes already received. The classification must not change: malformed, non-transient,
never ambiguous, status kept, one POST, outcome unavailable.

Edition 2 (host finding, 2026-11-03): on the Windows host of this commission a layer below the application withholds the body of
a Content-Length HTTP response on loopback until it is complete or the connection closes (a raw-socket probe receives the 41
header bytes but not the 100 body bytes that were sent with them; the same bytes as non-HTTP traffic arrive at once). So:
  FT1-A, FT1-B   drive the REAL http.client.HTTPResponse over a scripted socket that delivers 100 body bytes and then times out or
                 resets: deterministic on every host.
  FT1-G, FT1-I   real loopback sockets with a chunked body (delivered as it arrives on this host).
  FT1-A2, FT1-B2 real loopback Content-Length stall and reset: run when the probe shows partial bodies reach the application,
                 otherwise reported UNVERIFIED with the probe result (never PASS).
Offline except LOOPBACK sockets on 127.0.0.1 (local servers started and stopped by this script).
"""
import http.client, http.server, io, json, os, shutil, socket, socketserver, struct, sys, tempfile, threading, time
from unittest.mock import patch

TREE = os.path.abspath(sys.argv[1])
OUT = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
sys.path.insert(0, TREE)
sys.dont_write_bytecode = True
import run_eval as e  # noqa: E402
from mmeval import casesets as CS, runner as RN  # noqa: E402
from mmeval import transport as T  # noqa: E402
from mmeval.transport import HttpTransport, TransportError  # noqa: E402

TMP = tempfile.mkdtemp(prefix="r73-")
RES = []
PART = b'{"choices": [{"message": {"content": "' + b"x" * 61 + b'"'      # 100 bytes of a body announced as 1000
assert len(PART) == 100
HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n\r\n"


def check(cid, name, ok, observed):
    RES.append({"id": cid, "check": name, "result": "PASS" if ok else "FAIL", "observed": observed})
    print(f"{'PASS' if ok else 'FAIL'} {cid} {name}  [{json.dumps(observed, default=str)[:260]}]")


def unverified(cid, name, why):
    RES.append({"id": cid, "check": name, "result": "UNVERIFIED", "observed": why})
    print(f"UNVERIFIED {cid} {name}  [{json.dumps(why, default=str)[:260]}]")


def guarded(cid, name, fn):
    """Run one check body; an unexpected exception is a FAIL of that check, never a crash of the script."""
    try:
        fn()
    except Exception as ex:  # noqa: BLE001
        check(cid, name, False, "CRASH %s: %s" % (type(ex).__name__, str(ex)[:200]))


CASES_ALL = CS.build_case_manifest(os.path.join(TREE, "data"), "published-40", 7)
GOLDS = {c["case_id"]: json.load(open(c["gold_path"], encoding="utf-8")) for c in CASES_ALL}
ONE = [c for c in CASES_ALL if c["case_id"] == "sample_02_rotated"]
OK_BODY = json.dumps({"choices": [{"message": {"content": "y" * 150000}, "finish_reason": "stop"}], "model": "loop"}).encode()


def local_arm(url, attempts=3):
    return {"arm_id": "loc", "role": "test", "provider": "openai_compatible_local", "route": "local", "endpoint": url,
            "model_requested": "loop", "modalities": ["text", "image"], "image_capability_verified": True, "credential_env": None,
            "max_output_tokens": 256, "sampling": {}, "thinking": None, "image_detail": None, "image_preprocessing": "none",
            "allowed_data_classes": ["public_synthetic"], "status": "ready", "dispatch_enabled": True,
            "limits": {"max_calls": 100, "max_attempts_per_trial": attempts, "timeout_s": 1}}


def facts(ex):
    return ex and {"status": ex.status, "transient": ex.transient, "ambiguous": ex.ambiguous, "malformed": ex.malformed,
                   "body_len": None if ex.body is None else len(ex.body), "msg": str(ex)[:150]}


def kept(ex, exc_names):
    """The 2xx classification is unchanged and the 100 bytes that arrived are the raw body; the message names the real cause."""
    return (ex is not None and ex.malformed and not ex.transient and not ex.ambiguous and ex.status == 200
            and ex.body == PART.decode() and not ex.body_truncated and any(n in str(ex) for n in exc_names))


# ----- a scripted socket under the REAL http.client.HTTPResponse (the same BufferedReader path as a socket's makefile)
class ScriptedRaw(io.RawIOBase):
    def __init__(self, chunks, end):
        self.chunks, self.end = list(chunks), end

    def readable(self):
        return True

    def readinto(self, b):
        if self.chunks:
            c = self.chunks.pop(0)
            n = min(len(b), len(c))
            b[:n] = c[:n]
            if n < len(c):
                self.chunks.insert(0, c[n:])
            return n
        if self.end is None:
            return 0                                     # an orderly close
        raise self.end


class ScriptedSock:
    def __init__(self, chunks, end):
        self.chunks, self.end = chunks, end

    def makefile(self, mode, *a, **k):
        return io.BufferedReader(ScriptedRaw(self.chunks, self.end))


def scripted_send(chunks, end):
    """One HttpTransport.send whose response is the real HTTPResponse over the scripted bytes; returns (result, error, opens)."""
    opens = []

    def opener(req, timeout=None):
        opens.append(req.full_url)
        r = http.client.HTTPResponse(ScriptedSock(chunks, end), method="POST")
        r.begin()
        return r
    a = local_arm("http://127.0.0.1:9/v1/chat/completions")
    with patch.object(T.OPENER, "open", side_effect=opener):
        try:
            return HttpTransport().send(a, a["endpoint"], {}, {"x": 1}, 1), None, opens
        except TransportError as ex:
            return None, ex, opens


for cid, end, names in (("FT1-A", TimeoutError("timed out"), ("TimeoutError", "timed out")),
                        ("FT1-B", ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host"),
                         ("ConnectionResetError",))):
    def body(cid=cid, end=end, names=names):
        _, ex, opens = scripted_send([HEAD + PART], end)
        check(cid, "a 2xx (Content-Length 1000) whose body read ends by %s after 100 bytes keeps those bytes as the malformed body; "
              "status 200, non-transient, not ambiguous, the message names the cause (real HTTPResponse, scripted socket)"
              % type(end).__name__, kept(ex, names) and len(opens) == 1, facts(ex))
    guarded(cid, "scripted partial body", body)


def ctrl_scripted_close():
    _, ex, _ = scripted_send([HEAD + PART], None)
    check("CTRL-FT1-C2", "a scripted early close after 100 bytes keeps them and names IncompleteRead with 900 more expected",
          kept(ex, ("IncompleteRead",)) and "900 more expected" in str(ex), facts(ex))
guarded("CTRL-FT1-C2", "scripted close", ctrl_scripted_close)


# ----- real loopback servers
class Srv:
    def __init__(self, mode):
        self.mode, self.posts = mode, 0
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                outer.posts += 1
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.behave(self)

        class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.srv = S(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/v1/chat/completions" % self.srv.server_address[1]

    def behave(self, h):
        m = self.mode
        if m in ("chunked-ok", "chunked-stall"):
            h.send_response(200); h.send_header("Transfer-Encoding", "chunked"); h.end_headers()
            body = OK_BODY if m == "chunked-ok" else PART
            for i in range(0, len(body), 4096):
                piece = body[i:i + 4096]
                h.wfile.write(b"%x\r\n" % len(piece) + piece + b"\r\n")
            h.wfile.flush()
            if m == "chunked-ok":
                h.wfile.write(b"0\r\n\r\n"); h.wfile.flush()
            else:
                time.sleep(3)
            return
        if m == "big-ok":
            h.send_response(200); h.send_header("Content-Length", str(len(OK_BODY))); h.end_headers(); h.wfile.write(OK_BODY)
            return
        if m == "nonjson":
            b = b"this is not json " * 3
            h.send_response(200); h.send_header("Content-Length", str(len(b))); h.end_headers(); h.wfile.write(b)
            return
        h.send_response(200); h.send_header("Content-Length", "1000"); h.end_headers(); h.wfile.write(PART); h.wfile.flush()
        if m == "partial-stall":
            time.sleep(3)
        elif m == "partial-close":
            h.close_connection = True
        elif m == "partial-reset":
            time.sleep(0.3)
            h.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            h.connection.close()

    def close(self):
        self.srv.shutdown()


def send_once(mode):
    s = Srv(mode)
    try:
        try:
            r = HttpTransport().send(local_arm(s.url), s.url, {"Content-Type": "application/json"}, {"x": 1}, 1)
            return {"returned": r, "error": None, "posts": s.posts}
        except TransportError as ex:
            return {"returned": None, "error": ex, "posts": s.posts}
    finally:
        s.close()


def partial_bodies_reach_the_application():
    """Host probe: a raw loopback server sends HEAD + PART in one write and stalls; does a raw client receive all 141 bytes?"""
    ls = socket.socket(); ls.bind(("127.0.0.1", 0)); ls.listen(1)

    def serve():
        c, _ = ls.accept()
        c.recv(65536); c.sendall(HEAD + PART); time.sleep(2); c.close()
    threading.Thread(target=serve, daemon=True).start()
    cl = socket.create_connection(ls.getsockname(), timeout=1.5)
    got = b""
    try:
        cl.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 2\r\n\r\n{}")
        while len(got) < len(HEAD + PART):
            b = cl.recv(65536)
            if not b:
                break
            got += b
    except OSError:
        pass
    finally:
        cl.close(); ls.close()
    return {"sent": len(HEAD + PART), "received_within_1_5s": len(got), "delivered": len(got) == len(HEAD + PART)}


def ft1_chunked_stall():
    r = send_once("chunked-stall")
    check("FT1-G", "a chunked 2xx whose body stalls after 100 bytes keeps those bytes as the malformed body; status 200, "
          "non-transient, not ambiguous, the message names the timeout (real loopback socket)",
          r["error"] is not None and kept(r["error"], ("TimeoutError", "timed out")) and r["posts"] == 1,
          {"posts": r["posts"], **(facts(r["error"]) or {})})
guarded("FT1-G", "chunked stall", ft1_chunked_stall)


PROBE = partial_bodies_reach_the_application()
print("PROBE host delivery of a partial Content-Length body on loopback: %s" % json.dumps(PROBE))
for mode, cid, names in (("partial-stall", "FT1-A2", ("TimeoutError", "timed out")),
                         ("partial-reset", "FT1-B2", ("ConnectionResetError", "ConnectionAbortedError"))):
    name = ("a real loopback 2xx (Content-Length 1000) whose body read ends by %s keeps the 100 bytes that reached the "
            "application" % mode)
    if not PROBE["delivered"]:
        unverified(cid, name, {"why": "this host withholds a partial Content-Length body from the application", "probe": PROBE})
        continue

    def body(mode=mode, cid=cid, names=names, name=name):
        r = send_once(mode)
        check(cid, name, r["error"] is not None and kept(r["error"], names) and r["posts"] == 1,
              {"posts": r["posts"], **(facts(r["error"]) or {})})
    guarded(cid, "real partial body " + mode, body)


def ctrl_close():
    r = send_once("partial-close")
    check("CTRL-FT1-C", "a real loopback 2xx whose connection closes early keeps the 100 bytes and names IncompleteRead "
          "(unchanged behaviour)", r["error"] is not None and kept(r["error"], ("IncompleteRead",))
          and "900 more expected" in str(r["error"]), facts(r["error"]))
guarded("CTRL-FT1-C", "partial close", ctrl_close)


def ctrl_nonjson():
    r = send_once("nonjson")
    ex = r["error"]
    check("CTRL-FT1-D", "a complete non-JSON 2xx body is kept whole and named a decode error (unchanged behaviour)",
          ex is not None and ex.malformed and not ex.transient and ex.status == 200 and ex.body == "this is not json " * 3
          and "JSONDecodeError" in str(ex), facts(ex))
guarded("CTRL-FT1-D", "non-JSON body", ctrl_nonjson)


def ctrl_valid_bodies():
    for mode, cid in (("big-ok", "CTRL-FT1-E"), ("chunked-ok", "CTRL-FT1-F")):
        r = send_once(mode)
        got = (r["returned"] or {}).get("json")
        check(cid, "a valid %s JSON body of %d bytes is returned whole (status 200), read in several pieces" % (mode, len(OK_BODY)),
              r["error"] is None and got == json.loads(OK_BODY) and r["returned"]["http_status"] == 200,
              {"error": facts(r["error"]), "content_len": len(((got or {}).get("choices") or [{}])[0].get("message", {}).get("content", ""))})
guarded("CTRL-FT1-E", "valid bodies", ctrl_valid_bodies)


class FakeResp:
    """test_r72's double: a response object with read() only (no read1, no length)."""
    def __init__(self, status, read):
        self.status, self._read = status, read

    def read(self):
        return self._read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def ctrl_read_only_double():
    def reset():
        raise ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")
    a = local_arm("http://127.0.0.1:9/v1/chat/completions")
    err = None
    with patch.object(T.OPENER, "open", side_effect=lambda req, timeout=None: FakeResp(200, reset)):
        try:
            HttpTransport().send(a, a["endpoint"], {}, {"x": 1}, 1)
        except TransportError as ex:
            err = ex
    check("CTRL-FT1-H", "a response object with read() only still works: a reset while reading a 200 body is malformed, status 200, "
          "never ambiguous (test_r72 P3-H double)", err is not None and err.malformed and not err.ambiguous and err.status == 200
          and err.body == "", facts(err))
guarded("CTRL-FT1-H", "read-only double", ctrl_read_only_double)


def cfg(arms):
    return {"case_set": {"id": "published-40", "data_class": "public_synthetic"},
            "protocol": {"protocol_id": "t", "trials": 1, "order_seed": "t", "content_repair_retries": 1, "backoff_s": [0]},
            "dispatch": {"enabled": True}, "run_caps": {"max_calls_total": 1000}, "arms": arms}


def ft1_runner_record():
    s = Srv("chunked-stall")
    try:
        rd = os.path.join(TMP, "ft1-i")
        a = local_arm(s.url)
        c = cfg([a])
        m = RN.build_manifest(c, [a], ONE, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX, scorer_sha256="t",
                              renderer_sha256="t", data_class="public_synthetic")
        err = None
        try:
            RN.execute(m, c, [a], ONE, GOLDS, rd, HttpTransport(), e, prompt=e.TASK_PROMPT, retry_suffix=e.RETRY_SUFFIX,
                       environ={}, sleep=lambda x: None)
        except Exception as ex:  # noqa: BLE001
            err = "%s: %s" % (type(ex).__name__, ex)
        read = lambda n: [json.loads(l) for l in open(os.path.join(rd, n), encoding="utf-8") if l.strip()] \
            if os.path.exists(os.path.join(rd, n)) else []
        att = [(x["attempt"], x["result"]) for x in read("attempts.jsonl")]
        res = [x["outcome"] for x in read("results.jsonl")]
        rawd = os.path.join(rd, "raw")
        raw = [json.load(open(os.path.join(rawd, f), encoding="utf-8")) for f in sorted(os.listdir(rawd))] if os.path.isdir(rawd) else []
        check("FT1-I", "through the runner (real loopback, chunked body stalling after 100 bytes): one POST, attempt "
              "bad_provider_shape, outcome unavailable (unchanged), and the raw malformed_2xx record holds the 100 bytes",
              err is None and s.posts == 1 and att == [(1, "bad_provider_shape")] and res == ["unavailable"] and len(raw) == 1
              and raw[0].get("kind") == "malformed_2xx" and raw[0].get("status") == 200 and raw[0].get("body_text") == PART.decode(),
              {"error": err, "posts": s.posts, "attempts": att, "outcomes": res,
               "raw_body_len": [len(x.get("body_text") or "") for x in raw], "raw_kind": [x.get("kind") for x in raw]})
    finally:
        s.close()
guarded("FT1-I", "runner raw record", ft1_runner_record)


n_pass = sum(1 for r in RES if r["result"] == "PASS")
n_fail = sum(1 for r in RES if r["result"] == "FAIL")
n_unv = sum(1 for r in RES if r["result"] == "UNVERIFIED")
print(f"\n{n_pass} PASS · {n_fail} FAIL · {n_unv} UNVERIFIED  (tree: {TREE})")
if OUT:
    json.dump({"tree": TREE, "probe": PROBE, "results": RES}, open(OUT, "w", encoding="utf-8"), indent=1)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if n_fail == 0 else 1)
