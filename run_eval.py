#!/usr/bin/env python3
"""ED availability-intake eval harness.

Sends each synthetic calendar PNG to a vision-capable LLM, parses the returned
JSON, and scores it against the gold label. Extraction NEVER sees gold labels;
scoring NEVER calls the API.

Usage:
    python3 run_eval.py --model claude-sonnet-4-5 [--data ./data] [--out ./results] [--judge] [--limit N]

Provider is inferred from the model string:
    claude*  -> Anthropic  (ANTHROPIC_API_KEY)
    gpt*/o*  -> OpenAI     (OPENAI_API_KEY)

The API key is read from the environment ONLY. It is never printed or logged.
100% synthetic data — no PHI.
"""
import os, sys, json, csv, glob, base64, argparse, re, time, urllib.request, urllib.error

LEGAL = {"AVAILABLE", "AM", "PM", "NIGHT", "UNAVAILABLE"}
AVAILABLE_KINDS = {"AVAILABLE", "AM", "PM", "NIGHT"}

TASK_PROMPT = (
    'This image is a filled-in monthly staff availability calendar. '
    'Legend: ✓=available any shift, AM, PM, NOC=night shift, X=unavailable. '
    'Extract it to JSON with exactly this schema: '
    '{"month": "YYYY-MM", "days": {"YYYY-MM-DD": {"status": "AVAILABLE|AM|PM|NIGHT|UNAVAILABLE", "note": ""}}, '
    '"global_notes": []}. Every day of the month must appear. NOC maps to NIGHT; ✓ maps to AVAILABLE; '
    'X maps to UNAVAILABLE. Transcribe notes exactly as written; do not invent notes. Output ONLY the JSON.'
)

RETRY_SUFFIX = " Your previous output was not valid JSON. Output ONLY a single valid JSON object, no prose, no code fences."


# ---------------------------------------------------------------- providers
def provider_for(model):
    if model.lower().startswith("claude"):
        return "anthropic"
    return "openai"


def get_key(provider):
    var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    key = os.environ.get(var)
    if not key:
        sys.exit(f"ERROR: environment variable {var} is not set. Set it and re-run. "
                 "The key is read from the environment only and is never printed.")
    return key


def _post(url, headers, payload, tries=3):
    body = json.dumps(payload).encode()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 529) and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"API HTTP {e.code}: {detail}") from None
        except OSError as e:
            if attempt < tries - 1:
                time.sleep(5)
                continue
            raise RuntimeError(f"network error: {e}") from None


def call_vision(model, key, png_path, prompt):
    """Send one image + prompt; return raw text response."""
    b64 = base64.b64encode(open(png_path, "rb").read()).decode()
    if provider_for(model) == "anthropic":
        payload = {
            "model": model, "max_tokens": 4096,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": prompt},
            ]}],
        }
        out = _post("https://api.anthropic.com/v1/messages",
                    {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    payload)
        return "".join(b.get("text", "") for b in out.get("content", []))
    payload = {
        "model": model, "max_tokens": 4096,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
    }
    out = _post("https://api.openai.com/v1/chat/completions",
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload)
    return out["choices"][0]["message"]["content"] or ""


def call_text(model, key, prompt):
    """Text-only call (LLM-as-judge)."""
    if provider_for(model) == "anthropic":
        payload = {"model": model, "max_tokens": 16,
                   "messages": [{"role": "user", "content": prompt}]}
        out = _post("https://api.anthropic.com/v1/messages",
                    {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    payload)
        return "".join(b.get("text", "") for b in out.get("content", []))
    payload = {"model": model, "max_tokens": 16,
               "messages": [{"role": "user", "content": prompt}]}
    out = _post("https://api.openai.com/v1/chat/completions",
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload)
    return out["choices"][0]["message"]["content"] or ""


# ---------------------------------------------------------------- parsing
def parse_json(text):
    """Best-effort: strip fences, find the outermost JSON object."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def schema_valid(pred, gold):
    """Parsed + schema-conforming + all days present + statuses in enum."""
    if not isinstance(pred, dict):
        return False
    if pred.get("month") != gold["month"]:
        return False
    days = pred.get("days")
    if not isinstance(days, dict) or set(days) != set(gold["days"]):
        return False
    for cell in days.values():
        if not isinstance(cell, dict) or cell.get("status") not in LEGAL:
            return False
    if not isinstance(pred.get("global_notes", []), list):
        return False
    return True


# ---------------------------------------------------------------- scoring
def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def score_case(pred, gold):
    """All metrics for one case. pred may be None (format failure)."""
    gdays = gold["days"]
    n = len(gdays)
    pdays = pred.get("days", {}) if isinstance(pred, dict) else {}

    correct = sum(1 for d, c in gdays.items()
                  if isinstance(pdays.get(d), dict) and pdays[d].get("status") == c["status"])

    gold_unavail = [d for d, c in gdays.items() if c["status"] == "UNAVAILABLE"]
    flips = [d for d in gold_unavail
             if isinstance(pdays.get(d), dict) and pdays[d].get("status") in AVAILABLE_KINDS]

    # notes
    gold_day_notes = {d: c["note"] for d, c in gdays.items() if c["note"]}
    pred_day_notes = {d: c.get("note") for d, c in pdays.items()
                      if isinstance(c, dict) and norm(c.get("note"))}
    gold_gnotes = [norm(x) for x in gold.get("global_notes", [])]
    pred_gnotes_raw = pred.get("global_notes", []) if isinstance(pred, dict) else []
    pred_gnotes = [norm(x) for x in pred_gnotes_raw if norm(x)]

    total_pred_notes = len(pred_day_notes) + len(pred_gnotes)
    halluc = sum(1 for d, note in pred_day_notes.items() if norm(note) != norm(gold_day_notes.get(d, "")))
    halluc += sum(1 for gnote in pred_gnotes if gnote not in gold_gnotes)

    gold_total_notes = len(gold_day_notes) + len(gold_gnotes)
    captured = sum(1 for d, note in gold_day_notes.items()
                   if norm(pred_day_notes.get(d, "")) == norm(note))
    captured += sum(1 for gnote in gold_gnotes if gnote in pred_gnotes)

    unmatched_gold = ([(d, note, pdays.get(d, {}).get("note", "") if isinstance(pdays.get(d), dict) else "")
                       for d, note in gold_day_notes.items()
                       if norm(pred_day_notes.get(d, "")) != norm(note)]
                      + [("global", g, "; ".join(map(str, pred_gnotes_raw)))
                         for g in gold.get("global_notes", []) if norm(g) not in pred_gnotes])

    return {
        "day_accuracy": correct / n,
        "critical_error_rate": (len(flips) / len(gold_unavail)) if gold_unavail else None,
        "critical_flips": flips,
        "gold_unavailable_days": len(gold_unavail),
        "hallucination_rate": (halluc / total_pred_notes) if total_pred_notes else None,
        "hallucinated_notes": halluc,
        "predicted_notes": total_pred_notes,
        "note_fidelity": (captured / gold_total_notes) if gold_total_notes else None,
        "gold_notes": gold_total_notes,
        "captured_notes": captured,
        "unmatched_gold_notes": unmatched_gold,
    }


def judge_notes(model, key, unmatched):
    """Optional LLM-as-judge pass over gold notes that failed normalized match.
    Returns count judged semantically-equivalent. Reported separately; judge bias acknowledged."""
    ok = 0
    for _, gold_note, pred_note in unmatched:
        if not norm(pred_note):
            continue
        verdict = call_text(model, key,
                            f'Gold note: "{gold_note}"\nPredicted note: "{pred_note}"\n'
                            'Do these mean the same thing in a staff-scheduling context? Answer YES or NO only.')
        if verdict.strip().upper().startswith("YES"):
            ok += 1
    return ok


# ---------------------------------------------------------------- aggregate
def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def aggregate(rows, slice_name=None):
    sel = [r for r in rows if slice_name is None or r["slice"] == slice_name]
    if not sel:
        return None
    tot_unavail = sum(r["gold_unavailable_days"] for r in sel)
    tot_flips = sum(len(r["critical_flips"]) for r in sel)
    tot_pred_notes = sum(r["predicted_notes"] for r in sel)
    tot_halluc = sum(r["hallucinated_notes"] for r in sel)
    tot_gold_notes = sum(r["gold_notes"] for r in sel)
    tot_captured = sum(r["captured_notes"] for r in sel)
    return {
        "cases": len(sel),
        "day_accuracy": mean([r["day_accuracy"] for r in sel]),
        "critical_error_rate": (tot_flips / tot_unavail) if tot_unavail else None,
        "critical_flips": tot_flips,
        "gold_unavailable_days": tot_unavail,
        "hallucination_rate": (tot_halluc / tot_pred_notes) if tot_pred_notes else None,
        "note_fidelity": (tot_captured / tot_gold_notes) if tot_gold_notes else None,
        "format_validity": mean([1.0 if r["format_validity"] else 0.0 for r in sel]),
    }


def pct(v):
    return "n/a" if v is None else f"{100 * v:.1f}%"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="./data")
    ap.add_argument("--out", default="./results")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    key = get_key(provider_for(a.model))
    os.makedirs(a.out, exist_ok=True)
    raw_dir = os.path.join(a.out, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    cases = sorted(glob.glob(os.path.join(a.data, "sample_*.png")))
    if a.limit:
        cases = cases[: a.limit]
    if not cases:
        sys.exit(f"ERROR: no sample_*.png files in {a.data}")

    rows = []
    for i, png in enumerate(cases, 1):
        base = os.path.basename(png)[:-4]
        slice_name = base.split("_")[-1]
        gold = json.load(open(os.path.join(a.data, base + ".gold.json")))

        # --- extraction (image only; gold is never sent) ---
        text = call_vision(a.model, key, png, TASK_PROMPT)
        open(os.path.join(raw_dir, base + ".txt"), "w", encoding="utf-8").write(text)
        pred = parse_json(text)
        retried = False
        if pred is None:
            retried = True
            text = call_vision(a.model, key, png, TASK_PROMPT + RETRY_SUFFIX)
            open(os.path.join(raw_dir, base + ".retry.txt"), "w", encoding="utf-8").write(text)
            pred = parse_json(text)

        # --- scoring (local only; no API) ---
        s = score_case(pred, gold)
        s["case"] = base
        s["slice"] = slice_name
        s["format_validity"] = bool(pred) and schema_valid(pred, gold)
        s["retried"] = retried
        if a.judge and s["unmatched_gold_notes"]:
            s["note_fidelity_judge_extra"] = judge_notes(a.model, key, s["unmatched_gold_notes"])
        rows.append(s)
        print(f"[{i}/{len(cases)}] {base:28s} day_acc={pct(s['day_accuracy'])} "
              f"flips={len(s['critical_flips'])}/{s['gold_unavailable_days']} "
              f"valid={s['format_validity']}")

    rows.sort(key=lambda r: r["case"])
    slices = sorted({r["slice"] for r in rows})
    overall = aggregate(rows)
    per_slice = {s: aggregate(rows, s) for s in slices}
    clean_acc = per_slice.get("clean", {}).get("day_accuracy") if per_slice.get("clean") else None
    robustness = {s: (clean_acc - per_slice[s]["day_accuracy"])
                  for s in slices if s != "clean" and clean_acc is not None and per_slice[s]}

    if a.judge:
        extra = sum(r.get("note_fidelity_judge_extra", 0) for r in rows)
        tot_gold = sum(r["gold_notes"] for r in rows)
        tot_cap = sum(r["captured_notes"] for r in rows)
        overall["note_fidelity_judge"] = ((tot_cap + extra) / tot_gold) if tot_gold else None

    metrics = {"model": a.model, "cases": len(rows), "overall": overall,
               "per_slice": per_slice, "robustness_delta_vs_clean": robustness}
    json.dump(metrics, open(os.path.join(a.out, "metrics.json"), "w"), indent=2)

    # per_case.csv
    cols = ["case", "slice", "format_validity", "retried", "day_accuracy", "critical_error_rate",
            "critical_flips", "gold_unavailable_days", "hallucination_rate", "hallucinated_notes",
            "predicted_notes", "note_fidelity", "gold_notes", "captured_notes"]
    with open(os.path.join(a.out, "per_case.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([json.dumps(r[c]) if isinstance(r[c], list) else r[c] for c in cols])

    # summary.md — README-ready table
    with open(os.path.join(a.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"## Results — model: `{a.model}` ({len(rows)} cases)\n\n")
        f.write("| Metric | Overall | " + " | ".join(slices) + " |\n")
        f.write("|---|---|" + "---|" * len(slices) + "\n")
        for label, kf in [("Day-level accuracy", "day_accuracy"),
                          ("**Critical-error rate** (UNAVAILABLE→available)", "critical_error_rate"),
                          ("Hallucination rate (notes)", "hallucination_rate"),
                          ("Note fidelity (normalized match)", "note_fidelity"),
                          ("Format validity", "format_validity")]:
            f.write(f"| {label} | {pct(overall[kf])} | "
                    + " | ".join(pct(per_slice[s][kf]) for s in slices) + " |\n")
        f.write("\nRobustness delta vs clean: "
                + ", ".join(f"{s}: {pct(v)}" for s, v in robustness.items()) + "\n")
        f.write(f"\nCritical flips: {overall['critical_flips']} across "
                f"{overall['gold_unavailable_days']} gold-UNAVAILABLE days.\n")
        if a.judge:
            f.write(f"\nNote fidelity (LLM-as-judge, bias acknowledged): {pct(overall.get('note_fidelity_judge'))}\n")

    print("\n" + open(os.path.join(a.out, "summary.md"), encoding="utf-8").read())
    print(f"Wrote {a.out}/metrics.json, per_case.csv, summary.md (raw responses in {raw_dir}/)")


if __name__ == "__main__":
    main()
