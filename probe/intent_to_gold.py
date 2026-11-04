#!/usr/bin/env python3
"""intent_to_gold.py — turn a filled intent_*.csv (what you MEANT) into gold JSON.

Usage:  python3 intent_to_gold.py kit/intent_A-auth-1.csv
Writes kit/intent_A-auth-1.gold.json next to it. Refuses to write if any day is blank or has an illegal code.

Arm B (real, SPARSE documents — added 2026-09-06, PROBE-B.md §4):
  A row  DEFAULT_STATUS,<code>  states what an UNMARKED cell meant on that document. When present, blank days are
  filled with it and recorded as marked=false so the scorer can type blank-cell errors separately from marked-cell
  errors. Without it, a blank day still REFUSES — the sparse-document semantics must be stated, never assumed.
  Condition is inferred from the doc id: '-real-' -> "real", otherwise "authored".
"""
import sys, csv, json, os, re

LEGAL = {"AVAILABLE", "AM", "PM", "NIGHT", "UNAVAILABLE"}
# Generic aliases only. A writer's OWN shorthand (shift-time strings, personal letters) is loaded at run time
# from kit-B/private-map.json["_aliases"], which never ships — check-six 2026-09-07: hardcoding one writer's
# encodings in public code publishes them, which is the disclosure the pre-registration was de-identified to avoid.
ALIASES = {"✓": "AVAILABLE", "ANY": "AVAILABLE", "AVAIL": "AVAILABLE", "A": "AVAILABLE",
           "NOC": "NIGHT", "N": "NIGHT", "X": "UNAVAILABLE", "OFF": "UNAVAILABLE", "U": "UNAVAILABLE"}

def _load_private_aliases():
    import os, json as _j
    for c in ("kit-B/private-map.json", os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit-B", "private-map.json")):
        if os.path.isfile(c):
            try: return {k.strip().upper(): v for k, v in _j.load(open(c, encoding="utf-8")).get("_aliases", {}).items()}
            except Exception: return {}
    return {}
ALIASES.update(_load_private_aliases())


def norm_status(s):
    s = (s or "").strip().upper()
    return ALIASES.get(s, s)


def build(rows, doc_id):
    """Pure function so it can be self-tested without files. Returns (gold, bad_list)."""
    days, gnotes, bad, default, legend = {}, [], [], None, ""
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        key = r[0].strip()
        if key == "GLOBAL_NOTES":
            txt = (r[1] if len(r) > 1 else "").strip()
            gnotes = [t.strip() for t in re.split(r"[;|]", txt) if t.strip()]
            continue
        if key == "DEFAULT_STATUS":
            default = norm_status(r[1] if len(r) > 1 else "")
            if default not in LEGAL:
                bad.append(("DEFAULT_STATUS", r[1] if len(r) > 1 else ""))
                default = None
            continue
        if key == "LEGEND":
            legend = (r[1] if len(r) > 1 else "").strip()
            continue
        raw = (r[1] if len(r) > 1 else "").strip()
        note = (r[2] if len(r) > 2 else "").strip()
        days[key] = {"raw": raw, "note": note}
    for d, c in days.items():
        if c["raw"]:
            st = norm_status(c["raw"]); marked = True
        elif default:
            st = default; marked = False
        else:
            st = ""; marked = False
        if st not in LEGAL:
            bad.append((d, c["raw"]))
        c["status"] = st; c["marked"] = marked; del c["raw"]
    month = next(iter(days))[:7] if days else ""
    # Condition is derived from the SHEET, not the filename. A DEFAULT_STATUS row exists only on a sparse
    # real document (PROBE-B.md §4), so its presence is what marks Arm B. Keying on a doc-id substring
    # broke silently when documents were renamed to abstract IDs — check-six 2026-09-07.
    condition = "real" if default is not None else "authored"
    gold = {"month": month, "days": days, "global_notes": gnotes, "doc_id": doc_id,
            "condition": condition, "geometry": doc_id.split("-")[0],
            "blank_default": default, "legend": legend,
            "provenance": ("author self-report of INTENT for a REAL past document; unmarked cells filled from the "
                           "author's stated DEFAULT_STATUS and flagged marked=false" if condition == "real" else
                           "author self-report of INTENT, typed after writing; as-written layer = author's own reading of the photo")}
    return gold, bad


def main(path):
    rows = list(csv.reader(open(path, encoding="utf-8")))
    doc_id = os.path.basename(path).replace("intent_", "").replace(".csv", "")
    gold, bad = build(rows, doc_id)
    if bad:
        print("REFUSING to write gold — blank or illegal status on:")
        for d, v in bad:
            print(f"   {d}: {v!r}")
        if gold["condition"] == "real" and not gold["blank_default"]:
            print("   (Arm B: add a DEFAULT_STATUS row stating what an UNMARKED cell meant on this document — PROBE-B.md §4)")
        sys.exit(1)
    op = path.replace(".csv", ".gold.json")
    json.dump(gold, open(op, "w"), indent=2, ensure_ascii=False)
    nm = sum(1 for c in gold["days"].values() if c["marked"])
    print(f"wrote {op}  ({len(gold['days'])} days, {nm} marked, {len(gold['days']) - nm} from default={gold['blank_default']}, "
          f"{sum(1 for c in gold['days'].values() if c['note'])} notes, {len(gold['global_notes'])} global)")


def selftest():
    hdr = ["date", "status", "note"]
    # 1. blank day, no default -> REFUSE (the original discipline must survive)
    g, bad = build([hdr, ["2099-01-01", "NIGHT", ""], ["2099-01-02", "", ""]], "G9")
    assert bad and bad[0][0] == "2099-01-02", "blank without default must refuse"
    # 2. blank day WITH default -> filled, marked=false
    g, bad = build([hdr, ["2099-01-01", "NIGHT", ""], ["2099-01-02", "", ""], ["DEFAULT_STATUS", "AVAILABLE", ""]], "G9")
    assert not bad and g["days"]["2099-01-02"]["status"] == "AVAILABLE" and g["days"]["2099-01-02"]["marked"] is False
    assert g["days"]["2099-01-01"]["status"] == "NIGHT" and g["days"]["2099-01-01"]["marked"] is True, "marked day must survive"
    assert g["condition"] == "real" and g["blank_default"] == "AVAILABLE"
    # 3. illegal default -> refuse
    g, bad = build([hdr, ["2099-01-01", "", ""], ["DEFAULT_STATUS", "MAYBE", ""]], "G9")
    assert bad, "illegal DEFAULT_STATUS must refuse"
    # 4. Arm A behaviour unchanged: no default row, all days filled -> authored, all marked
    g, bad = build([hdr, ["2026-07-01", "AM", ""], ["2026-07-02", "X", "no call"]], "A-auth-1")
    # 5. condition is derived from the SHEET, not the filename (regression: abstract IDs broke the old rule)
    g5, _ = build([hdr, ["2099-01-01", "AM", ""], ["DEFAULT_STATUS", "AVAILABLE", ""]], "ANY-ID-AT-ALL")
    assert g5["condition"] == "real", "a DEFAULT_STATUS row must mark the sheet as a real sparse document"
    assert not bad and g["condition"] == "authored" and all(c["marked"] for c in g["days"].values())
    assert g["days"]["2026-07-02"]["status"] == "UNAVAILABLE" and g["days"]["2026-07-02"]["note"] == "no call"
    print("intent_to_gold selftest PASS — 5/5: blank-without-default refuses · default fills and flags · illegal default refuses · Arm A unchanged · condition derived from the sheet, not the filename")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        selftest(); sys.exit(0)
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
