"""Case sets: identities, split integrity and image/reference agreement (candidate r6).

A case is identified by its image bytes AND its reference content, not by its file name.
  truth_hash  sha256 of the canonical reference content (month, days, global_notes); the employee label
              and render style are presentation, not content
  png_sha256  sha256 of the image bytes
Split checks refuse duplicate case ids, duplicate images and duplicate references inside a set, and any
shared image, reference or generator seed between a development set and a confirmation set.
The render check re-renders a reference with the generator and compares pixels. It answers "does this
image show this reference?" only in an environment whose renderer reproduces the stored image; where it
cannot reproduce even an untouched case, the result is UNVERIFIED, never PASS.
"""
import glob, hashlib, json, os, random, re

CASE_RE = re.compile(r"^sample_(\d+)_([a-z]+)$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def truth_content(gold):
    return {"month": gold["month"], "days": gold["days"], "global_notes": list(gold.get("global_notes", []))}


def truth_hash(gold):
    return hashlib.sha256(json.dumps(truth_content(gold), sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def build_case_manifest(data_dir, split, seed_base=None):
    """One entry per sample_NN_style.png with its reference. seed is recorded when the generator's
    seed rule is known (published set: seed = 7 + NN - 1)."""
    cases = []
    for png in sorted(glob.glob(os.path.join(data_dir, "sample_*.png"))):
        base = os.path.basename(png)[:-4]
        m = CASE_RE.match(base)
        gpath = os.path.join(data_dir, base + ".gold.json")
        if not m or not os.path.isfile(gpath):
            continue
        gold = json.load(open(gpath, encoding="utf-8"))
        cases.append({"case_id": base, "split": split, "slice": m.group(2),
                      "index": int(m.group(1)),
                      "seed": (seed_base + int(m.group(1)) - 1) if seed_base is not None else None,
                      "png_sha256": sha256_file(png), "gold_sha256": sha256_file(gpath),
                      "truth_hash": truth_hash(gold), "days": len(gold["days"]),
                      "png_path": png, "gold_path": gpath})
    return cases


def set_hash(cases):
    ident = sorted((c["case_id"], c["png_sha256"], c["truth_hash"]) for c in cases)
    return hashlib.sha256(json.dumps(ident).encode()).hexdigest()


def check_set(cases):
    """Problems inside one set: duplicate ids, images or references."""
    errs = []
    for key in ("case_id", "png_sha256", "truth_hash"):
        seen = {}
        for c in cases:
            seen.setdefault(c[key], []).append(c["case_id"])
        errs += [f"duplicate {key}: {v}" for k, v in seen.items() if len(v) > 1]
    return errs


def check_splits(dev, conf):
    """Problems between a development set and a confirmation set: any shared image, reference or seed."""
    errs = check_set(dev) + check_set(conf)
    for key in ("png_sha256", "truth_hash", "seed"):
        a = {c[key] for c in dev if c.get(key) is not None}
        b = {c[key] for c in conf if c.get(key) is not None}
        shared = a & b
        if shared:
            errs.append(f"{len(shared)} shared {key} value(s) between development and confirmation")
    return errs


def render_check(case, generator_module, tmp_dir):
    """Re-render the case's reference with the generator and compare pixels with the stored image.
    Returns {"result": "MATCH"|"MISMATCH", "differing_pixels": n} for one case."""
    from PIL import Image, ImageChops
    gold = json.load(open(case["gold_path"], encoding="utf-8"))
    seed = case["seed"]
    rng = random.Random(seed * 7919)            # the generator's render-jitter stream
    out = os.path.join(tmp_dir, case["case_id"] + ".rerender.png")
    generator_module.render(gold, gold.get("employee_id", ""), gold.get("render_style", case["slice"]), out, rng)
    a, b = Image.open(case["png_path"]).convert("RGB"), Image.open(out).convert("RGB")
    if a.size != b.size:
        return {"result": "MISMATCH", "differing_pixels": None, "detail": f"size {a.size} vs {b.size}"}
    diff = ImageChops.difference(a, b)
    bbox = diff.getbbox()
    n = 0 if bbox is None else sum(1 for px in diff.getdata() if px != (0, 0, 0))
    return {"result": "MATCH" if n == 0 else "MISMATCH", "differing_pixels": n}


def regenerate_truth_check(case, generator_module, year=2026, month=7):
    """Does the generator, at this case's seed, produce exactly the stored reference content?"""
    gold = json.load(open(case["gold_path"], encoding="utf-8"))
    regen = generator_module.gen_truth(year, month, case["seed"])
    return truth_content(regen) == truth_content(gold)


# ---------------------------------------------------------------- task-definition audit (D-6)
WEEKDAY = {"No Mondays": {0}, "No weekends": {5, 6}}


def global_note_conflicts(gold):
    """Days whose marked status disagrees with a global note's literal meaning, under a reconciling
    reading. Under the transcription reading (the published prompt: "Transcribe notes exactly as
    written") these are NOT errors in the reference; they are listed so the task definition can be
    stated before scoring. "Max 3 shifts/wk" and "Prefer ICU" are not day-checkable and are skipped."""
    import datetime
    out = []
    for note in gold.get("global_notes", []):
        if note in WEEKDAY:
            for d, c in gold["days"].items():
                if datetime.date.fromisoformat(d).weekday() in WEEKDAY[note] and c["status"] != "UNAVAILABLE":
                    out.append((note, d, c["status"]))
        elif note == "Days only":
            out += [(note, d, c["status"]) for d, c in gold["days"].items() if c["status"] == "NIGHT"]
    return out
