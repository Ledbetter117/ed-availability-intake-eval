"""WIN-E-UNLOCKRACE visible test (BLACK-ED-r72 residual: the POSIX unlock restore can overwrite a third run's lock).

Two checks. The test gives os.rename POSIX semantics on every platform (rename onto an existing file replaces it), then makes a
third run create run.lock in the gap between the restore's existence check and its rename. The restore must never replace that
third run's lock: both files must survive, and release_stale_lock must refuse naming the moved file."""
import json, os, sys, tempfile, unittest
from unittest import mock

WORK = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
sys.path.insert(0, os.path.abspath(WORK))
from mmeval import runner as R   # noqa: E402
REAL_REPLACE = os.replace

PASS = FAIL = 0


def check(cid, label, ok, got=None):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS %s %s" % (cid, label))
    else:
        FAIL += 1
        print("FAIL %s %s -- got %r" % (cid, label, got))


def posix_rename(real):
    def rn(a, b, *args, **kw):
        if os.path.exists(b):
            return REAL_REPLACE(a, b)        # POSIX: rename onto an existing file replaces it
        return real(a, b, *args, **kw)
    return rn


def main():
    d = tempfile.mkdtemp(dir=os.path.join(os.path.abspath(WORK), "_tmp") if os.path.isdir(os.path.join(os.path.abspath(WORK), "_tmp")) else None)
    p = os.path.join(d, "run.lock")
    stale = json.dumps({"pid": 2 ** 22 + 12345, "pid_start": "x", "since": "2026-01-01T00:00:00Z", "host": R.host_identity()}).encode()
    open(p, "wb").write(stale)
    second = b'{"pid": 1, "note": "a second run took the lock between the check and the move"}'
    third = b'{"pid": 2, "note": "a third run took the lock in the restore gap"}'
    real_rename, real_link, real_exists = os.rename, getattr(os, "link", None), os.path.exists
    state = {"moved": False, "raced": False}

    def race(b):
        """The third run creates run.lock just before the restore touches it (the gap the restore cannot close)."""
        if state["moved"] and not state["raced"] and os.path.abspath(b) == os.path.abspath(p):
            state["raced"] = True
            if not real_exists(p):
                open(p, "wb").write(third)

    def rename(a, b, *args, **kw):
        if not state["moved"] and os.path.basename(a) == "run.lock":
            state["moved"] = True
            r = real_rename(a, b, *args, **kw)
            open(b, "wb").write(second)       # what was moved is now the second run's lock, so the release must put it back
            return r
        race(b)
        return posix_rename(real_rename)(a, b, *args, **kw)

    def link(a, b, *args, **kw):
        race(b)
        return real_link(a, b, *args, **kw)

    if not R.proc_identity(2 ** 22 + 12345)[0] is False:
        print("CRASH the dead-pid fixture is alive on this host"); return 2
    err = None
    with mock.patch.object(R.os, "rename", rename), mock.patch.object(R.os, "link", link):
        try:
            R.RunDir(d).release_stale_lock("test", "unlock race")
        except R.RunRefused as ex:
            err = str(ex)
    names = sorted(os.listdir(d))
    moved = [n for n in names if n.startswith("run.lock.stale-")]
    check("UR-A", "the third run's run.lock survives byte-equal after the refused restore",
          real_exists(p) and open(p, "rb").read() == third and err is not None, {"err": err, "files": names})
    check("UR-B", "the moved second-run lock survives under its moved name, and the refusal names it",
          len(moved) == 1 and open(os.path.join(d, moved[0]), "rb").read() == second and err is not None and moved[0] in err,
          {"err": err, "files": names})
    print("%d PASS · %d FAIL" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
