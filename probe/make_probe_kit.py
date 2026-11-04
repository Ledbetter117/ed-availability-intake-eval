#!/usr/bin/env python3
"""make_probe_kit.py — builds everything for the 2-hour authoring-conditions probe.

WHAT THE PROBE TESTS (pre-registered 2026-09-03, REDESIGN §8):
    Does a frontier VLM make status errors on REAL handwriting, and does it make
    more of them when the document is AUTHORED under realistic conditions than
    when it is carefully COPIED from a spec?

DECISION RULE (pre-registered, amended 2026-09-03 BEFORE any data — the authoritative text is written into
kit/MANIFEST.json by this script and implemented in probe_score.py). CANDIDATE A02-r1 (2026-10-26): the rule of record is
PROBE-AMENDMENT-01 §4 at the DOCUMENT level (PROCEED / CONTINUE; CLOSE retired; Stage 1 is a pilot). The 2026-09-03 rule is kept
in the manifest under decision_rule_as_preregistered_2026-09-03.
PREDICTION (stated before any data): copyist below authored; authored 2-10%, concentrated in shift codes,
    self-corrections and out-of-cell writing. The critical-flip prediction was removed — undecidable at this n.

OUTPUT (all in ./kit/):
    template_A_grid.png        month-grid form, 300 dpi letter, big cells      (geometry A)
    template_B_list.png        one-row-per-day list form, 300 dpi letter        (geometry B)
    spec_copy_*.png/.json      what to COPY for the 3 copyist documents + their gold
    intent_auth_*.csv          what you MEANT, typed after writing the 3 authored docs
    coding_behaviour.csv       the authoring-behaviour mediator, coded by eye from the photos
    MANIFEST.json              which file is which condition/geometry, plus the decision rule of record

Usage:  python3 make_probe_kit.py [--out ./kit] [--month 2026-10]
100% synthetic content. No PHI. The only real thing is the hand.
"""
import os, json, csv, random, argparse, calendar, datetime, sys
from PIL import Image, ImageDraw, ImageFont

STATUSES = ["AVAILABLE", "AM", "PM", "NIGHT", "UNAVAILABLE"]
CODE = {"AVAILABLE": "✓", "AM": "AM", "PM": "PM", "NIGHT": "NOC", "UNAVAILABLE": "X"}
NOTES = ["no call", "post-nights off", "back from PTO", "float OK", "charge only", "early out"]
GLOBAL = ["No weekends", "Days only", "Max 3 shifts/wk", "No Mondays", "Prefer ICU"]

DPI = 300
W, H = int(8.5 * DPI), int(11 * DPI)          # US Letter portrait
INK = (30, 30, 30)

# Six documents. AMENDED 2026-09-03 (PhD committee item 1c, before any data existed):
# geometry is now BALANCED WITHIN CONDITION — A appears twice in each condition, B once in each —
# so a copyist/authored difference cannot be a grid-vs-list difference in disguise.
# (Was: copy A,A,B / auth A,B,B — geometry confounded with condition.)
PLAN = [
    ("A", "copy", 1), ("A", "copy", 2), ("B", "copy", 1),
    ("A", "auth", 1), ("A", "auth", 2), ("B", "auth", 1),
]

# Authoring-behaviour mediator (PhD committee, human-factors member): C-IV is a mediation claim
# — design constrains authoring behaviour, which reduces error — and nothing measured the middle link.
# These are coded by eye from the founder's own photos, ~2 min per document.
CODING_FIELDS = [
    "doc_id", "elapsed_seconds",
    "cells_with_ink_outside_the_cell", "self_corrections_strikethrough_or_overwrite",
    "crammed_cells_ink_fills_most_of_cell", "abbreviations_not_in_the_printed_legend",
    "cells_left_blank_unintentionally", "notes_written_across_two_cells", "notes",
]


def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "C:/Windows/Fonts/arial.ttf", "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def gen_truth(year, month, seed):
    """Same content model as v1 generate_dataset.gen_truth — with run structure added
    (statuses persist 1-4 days) so the spec reads like a real month, not a coin flip per day."""
    r = random.Random(seed)
    ndays = calendar.monthrange(year, month)[1]
    days = {}
    d = 1
    while d <= ndays:
        wd = datetime.date(year, month, d).weekday()
        w = [0.18, 0.10, 0.12, 0.10, 0.50] if wd >= 5 else [0.30, 0.18, 0.20, 0.12, 0.20]
        status = r.choices(STATUSES, weights=w)[0]
        run = r.choice([1, 1, 2, 2, 3, 4])
        for k in range(run):
            if d > ndays:
                break
            note = r.choice(NOTES) if r.random() < 0.10 else ""
            days[f"{year:04d}-{month:02d}-{d:02d}"] = {"status": status, "note": note}
            d += 1
    gnotes = [r.choice(GLOBAL)] if r.random() < 0.6 else []
    return {"month": f"{year:04d}-{month:02d}", "days": days, "global_notes": gnotes}


# ------------------------------------------------------------------ templates
def template_grid(year, month, out):
    img = Image.new("RGB", (W, H), (255, 255, 255)); dr = ImageDraw.Draw(img)
    tf, hf, df, lf = font(64), font(40), font(44), font(30)
    dr.text((150, 120), "Staff Availability — Month: ____________________", font=tf, fill=INK)
    dr.text((150, 215), "Name: ____________________________     Unit: __________     Legend:  ✓ = any shift   AM   PM   NOC = night   X = unavailable",
            font=lf, fill=INK)
    dr.text((150, 275), "Notes / restrictions: ____________________________________________________________________", font=lf, fill=INK)
    cols, x0, y0 = 7, 150, 360
    cw = (W - 300) // cols            # ~321 px ≈ 1.07 in
    ch = 400                          # ≈ 1.33 in — room to write
    wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for c in range(cols):
        dr.rectangle([x0 + c * cw, y0, x0 + (c + 1) * cw, y0 + 70], outline=INK, width=3)
        dr.text((x0 + c * cw + 20, y0 + 12), wd[c], font=hf, fill=INK)
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    for ri, week in enumerate(weeks):
        for ci, day in enumerate(week):
            cx, cy = x0 + ci * cw, y0 + 70 + ri * ch
            dr.rectangle([cx, cy, cx + cw, cy + ch], outline=INK, width=3)
            if day:
                dr.text((cx + 14, cy + 10), str(day), font=df, fill=INK)
    img.save(out, dpi=(DPI, DPI))


def template_list(year, month, out):
    img = Image.new("RGB", (W, H), (255, 255, 255)); dr = ImageDraw.Draw(img)
    tf, lf, rf = font(60), font(30), font(34)
    dr.text((150, 110), "Availability Request — one line per day", font=tf, fill=INK)
    dr.text((150, 195), "Name: ______________________   Month: ____________   Codes:  ✓ any   AM   PM   NOC   X = unavailable",
            font=lf, fill=INK)
    dr.text((150, 245), "Notes / restrictions: __________________________________________________________________", font=lf, fill=INK)
    ndays = calendar.monthrange(year, month)[1]
    x0, y0 = 150, 320
    rh = (H - y0 - 150) // (ndays + 1)          # fits 31 rows + header
    c1, c2, c3 = 300, 260, W - 300 - x0 - 300 - 260
    hdr = [("Date", c1), ("Status", c2), ("Note", c3)]
    x = x0
    for name, wdt in hdr:
        dr.rectangle([x, y0, x + wdt, y0 + rh], outline=INK, width=3)
        dr.text((x + 16, y0 + 10), name, font=rf, fill=INK); x += wdt
    for i in range(ndays):
        y = y0 + rh * (i + 1); x = x0
        dt = datetime.date(year, month, i + 1)
        for j, (_, wdt) in enumerate(hdr):
            dr.rectangle([x, y, x + wdt, y + rh], outline=INK, width=2)
            if j == 0:
                dr.text((x + 16, y + 10), dt.strftime("%a %d"), font=rf, fill=INK)
            x += wdt
    img.save(out, dpi=(DPI, DPI))


# ------------------------------------------------------------------ specs and intent sheets
def spec_sheet(truth, title, out_png):
    """A printable sheet the writer COPIES from in the copyist condition."""
    img = Image.new("RGB", (W, H), (255, 255, 255)); dr = ImageDraw.Draw(img)
    tf, bf, sf = font(56), font(34), font(28)
    dr.text((150, 110), title, font=tf, fill=INK)
    dr.text((150, 190), "COPYIST CONDITION — copy each day's code (and note, if any) carefully onto the form. Take your time.",
            font=sf, fill=INK)
    dr.text((150, 235), "Global note for the top of the form: " + ("; ".join(truth["global_notes"]) or "(none)"), font=sf, fill=INK)
    y = 310
    items = list(truth["days"].items())
    col_w = (W - 300) // 2
    for k, (d, c) in enumerate(items):
        col = k // 16; row = k % 16
        x = 150 + col * col_w; yy = y + row * 150
        dt = datetime.date.fromisoformat(d)
        line = f"{dt.strftime('%a %d')}:   {CODE[c['status']]}"
        dr.text((x, yy), line, font=bf, fill=INK)
        if c["note"]:
            dr.text((x + 40, yy + 52), f"note: {c['note']}", font=sf, fill=(80, 80, 80))
    img.save(out_png, dpi=(DPI, DPI))


def intent_csv(year, month, out_csv):
    """Blank sheet the writer fills AFTER writing an authored document: what did you MEAN per day."""
    ndays = calendar.monthrange(year, month)[1]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "status  (AVAILABLE|AM|PM|NIGHT|UNAVAILABLE)", "note (exactly what you meant, or blank)"])
        for i in range(ndays):
            w.writerow([f"{year:04d}-{month:02d}-{i + 1:02d}", "", ""])
        w.writerow(["GLOBAL_NOTES", "", "(any notes/restrictions you wrote at the top, or blank)"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit"))
    ap.add_argument("--month", default="2026-10")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    year, month = map(int, a.month.split("-"))
    template_grid(year, month, os.path.join(a.out, "template_A_grid.png"))
    template_list(year, month, os.path.join(a.out, "template_B_list.png"))
    manifest = []
    seed = 101
    for geom, cond, n in PLAN:
        doc_id = f"{geom}-{cond}-{n}"
        entry = {"doc_id": doc_id, "geometry": geom, "condition": cond,
                 "template": f"template_{'A_grid' if geom == 'A' else 'B_list'}.png",
                 "photo_expected": f"{doc_id}.jpg"}
        if cond == "copy":
            truth = gen_truth(year, month, seed); seed += 1
            truth["doc_id"] = doc_id; truth["condition"] = "copyist"; truth["geometry"] = geom
            json.dump(truth, open(os.path.join(a.out, f"spec_{doc_id}.gold.json"), "w"), indent=2, ensure_ascii=False)
            spec_sheet(truth, f"Spec to copy — document {doc_id}", os.path.join(a.out, f"spec_{doc_id}.png"))
            entry["gold"] = f"spec_{doc_id}.gold.json"; entry["copy_from"] = f"spec_{doc_id}.png"
        else:
            intent_csv(year, month, os.path.join(a.out, f"intent_{doc_id}.csv"))
            entry["intent_csv"] = f"intent_{doc_id}.csv"; entry["gold"] = f"intent_{doc_id}.gold.json (made by intent_to_gold.py)"
        manifest.append(entry)
    # behaviour-coding sheet — one row per document, filled by eye from the photos
    with open(os.path.join(a.out, "coding_behaviour.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(CODING_FIELDS)
        for e in manifest:
            w.writerow([e["doc_id"]] + [""] * (len(CODING_FIELDS) - 1))

    json.dump({"month": a.month, "documents": manifest,
               "pre_registered": "2026-09-03",
               "amended": "2026-09-03, after PhD proposal committee review, BEFORE any document was written or photographed",
               "decision_rule": {
                   "unit": "DOCUMENT: an error document has at least one status error (PROBE-AMENDMENT-01 §2)",
                   "PROCEED": "two-sided Fisher exact p < 0.05 on error documents per arm, authored > copyist, AND the two Wilson 95% "
                              "intervals do not overlap (PROBE-AMENDMENT-01 §4)",
                   "CLOSE": "RETIRED: unreachable at any feasible n for one writer (PROBE-AMENDMENT-01 §3)",
                   "CONTINUE": "anything else, including every Stage 1 outcome; Stage 1 (3 documents per arm) is a pilot with no verdict. "
                               "Stage 2: 7 documents per arm; minimum 5 of 7 authored vs 0 of 7 copyist",
                   "route": "local vision model only (D-1; PROBE-AMENDMENT-01 §4b; PROBE-AMENDMENT-02)",
                   "families": "a single-family run is stated as such; it gates no branch"},
               "decision_rule_as_preregistered_2026-09-03": {
                   "CLOSE_THE_TRACK": "copyist Wilson-95 UPPER bound < 2% AND authored Wilson-95 UPPER bound < 5% "
                                      "-> frontier reads this class at ceiling under both conditions; publish the saturation negative",
                   "PROCEED": "authored > copyist AND Fisher two-sided p < 0.05 AND authored Wilson-95 LOWER bound > copyist UPPER bound "
                              "(non-overlapping intervals) -> an authoring effect exists at this scale. AMENDED 2026-09-04 before any data: "
                              "the earlier 'authored lower bound > 5%' clause was a LEVEL test that fired on equal error in both arms; "
                              "PROCEED is the expensive branch and is now the guarded one",
                   "CONTINUE": "anything else -> Stage 2: FOUR more documents PER ARM (eight total), same protocol, re-run. "
                               "CLOSE needs 189 cells per arm at zero errors (computed by probe_score.py); Stage 1 has 93, "
                               "so Stage 1 can only PROCEED or CONTINUE. With 3 documents per arm the effective n is the "
                               "DOCUMENT, not the cell; both decisive branches are guarded by confidence bounds, not point estimates",
                   "CLOSE_requires_a_non_Claude_frontier_model": "2604.16504 §4.2: 'The Claude family was an exception ... substantially "
                               "weaker than their Gemini and GPT counterparts (~10%+)'. A Claude-only run is the weaker family; "
                               "probe_score.py DISABLES the CLOSE branch unless an OpenAI-family model is included. PROCEED is valid on any family",
                   "model_string_of_record": "v1 ran claude-sonnet-5 (results/metrics.json); the probe defaults to the same string"},
               "prediction": "copyist error rate below the authored rate; authored 2-10%, concentrated in shift codes, "
                             "self-corrections, and cells written outside their boundary. "
                             "NOTE: this prediction overlaps the CLOSE region by design - the CI-guarded decision rule, not the "
                             "point prediction, decides. The critical-flip prediction was REMOVED 2026-09-03: with ~25 gold-UNAVAILABLE "
                             "cells per condition its CI is roughly [0.1%, 20%] and the probe cannot decide it",
                   "mediator": "coding_behaviour.csv - authoring behaviour is the middle link of C-IV and is measured, not assumed",
                   "durability": "run at least two model generations where available; a design lever that evaporates on the next "
                                 "model release is worth nothing to a practitioner (external examiner)"},
              open(os.path.join(a.out, "MANIFEST.json"), "w"), indent=2)
    print(f"kit written to {a.out}:")
    for f in sorted(os.listdir(a.out)):
        print("  ", f)


if __name__ == "__main__":
    main()
