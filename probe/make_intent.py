#!/usr/bin/env python3
"""make_intent.py — an intent sheet for a REAL past calendar of your own (optional seventh document).

Your own old availability sheet, written months ago with no timer and no experiment in mind, is the truest
"authored" condition there is. Photograph it (only if it contains no one else's data — your own sheet, your own hand),
then record what you MEANT per day here. It scores as condition "real" alongside copyist and authored.

Usage:  python3 make_intent.py --month 2026-06 --doc A-real-1   [--kit ./kit]
Then:   fill kit/intent_A-real-1.csv · python3 intent_to_gold.py kit/intent_A-real-1.csv · photo as photos/A-real-1.jpg
The manifest is updated so probe_score.py picks it up. Geometry letter: A if it is a month grid, B if a list, C if anything else.
"""
import argparse, os, json, calendar, csv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True); ap.add_argument("--doc", required=True); ap.add_argument("--kit", default="./kit")
    a = ap.parse_args()
    y, m = map(int, a.month.split("-")); nd = calendar.monthrange(y, m)[1]
    p = os.path.join(a.kit, f"intent_{a.doc}.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "status  (AVAILABLE|AM|PM|NIGHT|UNAVAILABLE)", "note (exactly what you meant, or blank)"])
        for i in range(nd):
            w.writerow([f"{y:04d}-{m:02d}-{i + 1:02d}", "", ""])
        w.writerow(["GLOBAL_NOTES", "", "(anything written at the top, or blank)"])
    mp = os.path.join(a.kit, "MANIFEST.json"); man = json.load(open(mp))
    man["documents"] = [d for d in man["documents"] if d["doc_id"] != a.doc]
    man["documents"].append({"doc_id": a.doc, "geometry": a.doc.split("-")[0], "condition": "real",
                             "template": "(your own real form)", "photo_expected": f"{a.doc}.jpg",
                             "intent_csv": f"intent_{a.doc}.csv", "gold": f"intent_{a.doc}.gold.json (made by intent_to_gold.py)",
                             "month": a.month})
    json.dump(man, open(mp, "w"), indent=2)
    print(f"wrote {p} ({nd} days) and added {a.doc} (condition=real, month={a.month}) to MANIFEST.json")


if __name__ == "__main__":
    main()
