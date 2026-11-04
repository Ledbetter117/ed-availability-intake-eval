#!/usr/bin/env python3
"""ED availability-intake eval harness.

Sends each synthetic calendar PNG to a vision-capable LLM, parses the returned
JSON, and scores it against the gold label. Extraction NEVER sees gold labels;
scoring NEVER calls the API.

Usage:
    python3 run_eval.py --model claude-sonnet-4-5 [--data ./data] [--out ./results] [--judge] [--limit N]

Provider is inferred from the model string:
    claude*                 -> Anthropic  (ANTHROPIC_API_KEY)
    gpt*, chatgpt*, o<N>*   -> OpenAI     (OPENAI_API_KEY)
    any other name          -> rejected before any call (no silent default provider)

Exit status (v1.2):
    0  complete, and at least one case was scored
    1  no case got a model answer (run FAILED; metrics.json is not written)
    2  usage or configuration error; refused before any call
    3  incomplete: provider errors, truncated answers or cases not run (partial outputs are labelled)
    4  every model answer was invalid, so no case was scored

The API key is read from the environment ONLY. It is never printed or logged.
100% synthetic data — no PHI.
"""
import os, sys, json, csv, glob, base64, argparse, re, time, urllib.request, urllib.error
from mmeval import transport as transport

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
    """Infer the provider from the model name, or return None when it cannot be inferred.

    An unrecognised name must not silently route to a paid provider (QA: unknown_provider_rejected)."""
    m = str(model).lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "chatgpt")) or is_o_series(m):
        return "openai"
    return None


def is_o_series(model):
    """OpenAI o-series reasoning models (o1, o3, o4-mini, ...)."""
    return re.match(r"o\d", str(model).lower()) is not None


# OpenAI's reasoning guide recommends reserving at least 25,000 tokens for reasoning and output when
# starting with these models; a smaller budget can end before any visible text (review P06-ED F09).
O_SERIES_MIN_COMPLETION_TOKENS = 25_000


class TruncatedResponse(Exception):
    """The provider stopped at the token limit. This is a harness outcome, not the model's answer."""

    def __init__(self, text, reason):
        super().__init__(reason)
        self.text, self.reason = text, reason


def openai_token_limit(model, n):
    """o-series models reject `max_tokens`; they take `max_completion_tokens` (QA: o_series_...)."""
    if is_o_series(model):
        return {"max_completion_tokens": max(n, O_SERIES_MIN_COMPLETION_TOKENS)}
    return {"max_tokens": n}


def get_key(provider):
    var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    key = os.environ.get(var)
    if not key:
        print(f"ERROR: environment variable {var} is not set. Set it and re-run. "
              "The key is read from the environment only and is never printed.", file=sys.stderr)
        sys.exit(2)   # configuration error: nothing was called
    return key


def _post(url, headers, payload, tries=3):
    """Use the same bounded, credential-scrubbing transport as the multi-model runner.

    Only explicit provider endpoints are accepted. An ambiguous send or malformed
    success is terminal: an unrecorded retry could duplicate a paid request.
    """
    providers = {"https://api.anthropic.com/v1/messages": "anthropic",
                 "https://api.openai.com/v1/chat/completions": "openai"}
    if url not in providers:
        raise RuntimeError("legacy provider destination is not allowed; nothing was sent")
    arm = {"arm_id": "legacy", "provider": providers[url], "route": "cloud"}
    for attempt in range(tries):
        try:
            return transport.HttpTransport().send(arm, url, headers, payload, 180)["json"]
        except transport.TransportError as e:
            if e.transient and not e.ambiguous and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(str(e)) from None


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
        text = "".join(b.get("text", "") for b in out.get("content", []))
        if out.get("stop_reason") == "max_tokens":
            raise TruncatedResponse(text, "stop_reason=max_tokens")
        return text
    payload = {
        "model": model, **openai_token_limit(model, 4096),
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
    }
    out = _post("https://api.openai.com/v1/chat/completions",
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload)
    choice = out["choices"][0]
    text = choice["message"]["content"] or ""
    if choice.get("finish_reason") == "length":
        raise TruncatedResponse(text, "finish_reason=length")
    return text


def call_text(model, key, prompt):
    """Text-only call (LLM-as-judge)."""
    if provider_for(model) == "anthropic":
        payload = {"model": model, "max_tokens": 16,
                   "messages": [{"role": "user", "content": prompt}]}
        out = _post("https://api.anthropic.com/v1/messages",
                    {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    payload)
        return "".join(b.get("text", "") for b in out.get("content", []))
    # Reasoning models spend completion tokens before answering; openai_token_limit raises their budget.
    payload = {"model": model, **openai_token_limit(model, 16),
               "messages": [{"role": "user", "content": prompt}]}
    out = _post("https://api.openai.com/v1/chat/completions",
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload)
    return out["choices"][0]["message"]["content"] or ""


# ---------------------------------------------------------------- parsing
class _Rejected(ValueError):
    """JSON text that Python's lenient json module accepts but the response contract does not."""


def _pairs_without_conflicts(pairs):
    out = {}
    for k, v in pairs:
        if k in out and out[k] != v:
            raise _Rejected(f"conflicting duplicate field {k!r}")
        out[k] = v
    return out


def _reject_constant(token):
    raise _Rejected(f"non-standard JSON constant {token}")


def _strict_loads(s):
    return json.loads(s, object_pairs_hook=_pairs_without_conflicts, parse_constant=_reject_constant)


def parse_json(text):
    """Best-effort: strip fences, find the outermost JSON object.

    Strict where leniency would change the meaning (candidate r4): a field given twice with different
    values, and NaN/Infinity, are rejected (Python's json accepts both, keeping the last value);
    pathological nesting returns None instead of raising RecursionError."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.MULTILINE).strip()
    try:
        return _strict_loads(t)
    except RecursionError:
        return None
    except ValueError:            # json.JSONDecodeError and _Rejected: try the outermost {...} once
        pass
    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if m:
        try:
            return _strict_loads(m.group(0))
        except (ValueError, RecursionError):
            return None
    return None


TOP_FIELDS = {"month", "days", "global_notes"}
CELL_FIELDS = {"status", "note"}


def schema_errors(pred, gold):
    """Every way a parsed response breaks the requested schema; [] when it conforms.

    The schema is the one TASK_PROMPT asks for: exactly month/days/global_notes; each day exactly
    status/note; status one of the legal strings; note a string; global_notes a list of strings."""
    if not isinstance(pred, dict):
        return ["top level is not a JSON object"]
    errs = []
    if set(pred) != TOP_FIELDS:
        errs.append("top-level fields differ: " + ", ".join(sorted(set(pred) ^ TOP_FIELDS)))
    if pred.get("month") != gold["month"]:
        errs.append("month does not match the calendar")
    days = pred.get("days")
    if not isinstance(days, dict):
        errs.append("days is not an object")
    else:
        if set(days) != set(gold["days"]):
            errs.append("day keys differ from the calendar month")
        for d in sorted(days):
            cell = days[d]
            if not isinstance(cell, dict) or set(cell) != CELL_FIELDS:
                errs.append(f"{d}: fields are not exactly status and note")
            elif not isinstance(cell["status"], str) or cell["status"] not in LEGAL:
                errs.append(f"{d}: status is not a legal value")
            elif not isinstance(cell["note"], str):
                errs.append(f"{d}: note is not a string")
    gn = pred.get("global_notes")
    if not isinstance(gn, list) or not all(isinstance(x, str) for x in gn):
        errs.append("global_notes is not a list of strings")
    return errs


def schema_valid(pred, gold):
    """Parsed + schema-conforming + all days present + statuses in enum (see schema_errors)."""
    return not schema_errors(pred, gold)


# ---------------------------------------------------------------- scoring
def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def score_case(pred, gold):
    """All metrics for one case. pred may be None (format failure)."""
    gdays = gold["days"]
    n = len(gdays)
    pdays = pred.get("days") if isinstance(pred, dict) else None
    if not isinstance(pdays, dict):   # parseable but malformed ("days": null / a list): never crash
        pdays = {}

    def status_of(cell):   # compared only as a string: a [] or {} status must not raise
        s = cell.get("status") if isinstance(cell, dict) else None
        return s if isinstance(s, str) else None

    correct = sum(1 for d, c in gdays.items() if status_of(pdays.get(d)) == c["status"])

    gold_unavail = [d for d, c in gdays.items() if c["status"] == "UNAVAILABLE"]
    flips = [d for d in gold_unavail if status_of(pdays.get(d)) in AVAILABLE_KINDS]

    # notes
    gold_day_notes = {d: c["note"] for d, c in gdays.items() if c["note"]}
    pred_day_notes = {d: c.get("note") for d, c in pdays.items()
                      if isinstance(c, dict) and norm(c.get("note"))}
    gold_gnotes = [norm(x) for x in gold.get("global_notes", [])]
    pred_gnotes_raw = pred.get("global_notes", []) if isinstance(pred, dict) else []
    if not isinstance(pred_gnotes_raw, list):   # a bare string would be split into one "note" per character
        pred_gnotes_raw = []
    # One instance per distinct normalized text: repeating a correct global note 10,000 times must not
    # dilute the mismatch rate (QA: duplicate_global_notes_cannot_dilute_error_rate).
    pred_gnotes = list(dict.fromkeys(norm(x) for x in pred_gnotes_raw if norm(x)))

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

    # Typed split of the mismatched predicted notes, with the docs/METHODS.md definitions (candidate r4):
    # DISPLACED = the text is a gold note of this calendar, at another location; FABRICATED = it is no
    # gold note of this calendar. displaced + fabricated == mismatched, by construction.
    gold_texts = {norm(x) for x in gold_day_notes.values()} | set(gold_gnotes)
    displaced = fabricated = 0
    for d, note in pred_day_notes.items():
        if norm(note) != norm(gold_day_notes.get(d, "")):
            if norm(note) in gold_texts:
                displaced += 1
            else:
                fabricated += 1
    for gnote in pred_gnotes:
        if gnote not in gold_gnotes:
            if gnote in gold_texts:
                displaced += 1
            else:
                fabricated += 1

    # NOTE-METRIC NAMING — corrected 2026-09-12 (external QA finding F03).
    #
    # `halluc` counts PREDICTED notes whose text does not match the gold note at the SAME
    # location. That is a note-LOCATION-MISMATCH count. It is reported as
    # `note_mismatch_rate` / `mismatched_notes`.
    #
    # It is NOT the typed metric: a DISPLACED note (real text, wrong place) and a FABRICATED one
    # (text that is no gold note) both land in it. Since candidate r4 the harness also reports the
    # split, as `displaced_notes` and `fabricated_notes`; the published typed totals came from a
    # separate scorer (typed_errors.json), which tests/test_harness.py compares against this one.
    #
    # `hallucination_rate` / `hallucinated_notes` are RETIRED NAMES for the same quantity,
    # emitted only so the shipped v1 results/ and results_haiku/ files stay readable by tools
    # written against them. New work should read the `*_mismatch*` keys.
    return {
        "day_accuracy": correct / n,
        "gold_days": n,            # persisted so charts count days instead of assuming 31 (F18)
        "correct_days": correct,
        "critical_error_rate": (len(flips) / len(gold_unavail)) if gold_unavail else None,
        "critical_flips": flips,
        "gold_unavailable_days": len(gold_unavail),
        "note_mismatch_rate": (halluc / total_pred_notes) if total_pred_notes else None,
        "mismatched_notes": halluc,
        "displaced_notes": displaced,
        "fabricated_notes": fabricated,
        "hallucination_rate": (halluc / total_pred_notes) if total_pred_notes else None,  # RETIRED alias
        "hallucinated_notes": halluc,                                                     # RETIRED alias
        "predicted_notes": total_pred_notes,
        "note_fidelity": (captured / gold_total_notes) if gold_total_notes else None,
        "gold_notes": gold_total_notes,
        "captured_notes": captured,
        "unmatched_gold_notes": unmatched_gold,
    }


# ------------------------------------------- validate first, then score (candidate 2026-10-16)
# A response that does not parse, or parses but fails schema_valid(), is REPORTED and never SCORED.
# Before this change score_case() ran first on whatever parsed, and every row entered the aggregates:
# a malformed response could crash the run, invent notes, or add its gold-UNAVAILABLE days to the
# critical-error denominator with zero flips (docs/METHODS.md, "One known gap").
def invalid_case(pred, gold):
    """Explicit invalid result: gold-side counts kept for transparency, every model-side metric None."""
    gdays = gold["days"]
    gold_notes = sum(1 for c in gdays.values() if c["note"]) + len(gold.get("global_notes", []))
    return {
        "format_validity": False, "scored": False,
        "invalid_reason": "unparseable" if pred is None else "schema: " + "; ".join(schema_errors(pred, gold)[:3]),
        "day_accuracy": None, "gold_days": len(gdays), "correct_days": None,
        "critical_error_rate": None, "critical_flips": None,
        "gold_unavailable_days": sum(1 for c in gdays.values() if c["status"] == "UNAVAILABLE"),
        "note_mismatch_rate": None, "mismatched_notes": None,
        "displaced_notes": None, "fabricated_notes": None,
        "hallucination_rate": None, "hallucinated_notes": None,   # RETIRED aliases
        "predicted_notes": None, "note_fidelity": None, "gold_notes": gold_notes,
        "captured_notes": None, "unmatched_gold_notes": [],
    }


def evaluate_response(pred, gold):
    """The only path main() uses: schema_valid() decides whether score_case() runs at all."""
    if pred is None or not schema_valid(pred, gold):
        return invalid_case(pred, gold)
    s = score_case(pred, gold)
    s.update({"format_validity": True, "scored": True, "invalid_reason": ""})
    return s


def provider_error_case(gold, error_type):
    """No model answer was obtained for this case (provider or network failure): reported, never scored,
    and never counted as a model formatting failure."""
    s = invalid_case(None, gold)
    s["invalid_reason"] = "provider_error"
    s["provider_error"] = error_type
    return s


def is_valid_row(r):
    """True for rows that were scored. Accepts CSV-loaded strings: "False" must not count as valid."""
    v = r.get("format_validity")
    return v is True or str(v).strip().lower() in ("true", "1", "1.0")


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
        if re.match(r"\W*YES\b", str(verdict).strip().upper()):   # "YESterday" is not a verdict
            ok += 1
    return ok


# ---------------------------------------------------------------- aggregate
def mean(vals):
    # r7.1 (A8, ORCA-ED-MAX-PROGRESS-20261030): an explicit left-to-right float sum. Python 3.12 changed the built-in sum() of floats
    # to compensated summation, so the published v1 results_haiku day_accuracy (0.979032258064516, computed with Python <= 3.11)
    # came out one unit in the last place higher (...162) on 3.12+. The left fold gives the published bits on every interpreter.
    vals = [v for v in vals if v is not None]
    total = 0.0
    for v in vals:
        total += v
    return total / len(vals) if vals else None


def aggregate(rows, slice_name=None):
    sel = [r for r in rows if slice_name is None or r["slice"] == slice_name]
    if not sel:
        return None
    every = sel                                   # format validity is over every case
    sel = [r for r in every if is_valid_row(r)]   # every other metric is over scored cases only
    tot_unavail = sum(r["gold_unavailable_days"] for r in sel)
    tot_flips = sum(len(r["critical_flips"]) for r in sel)
    tot_pred_notes = sum(r["predicted_notes"] for r in sel)
    # Rows loaded from the shipped v1 CSVs carry only the retired key (RES-02, 2026-09-25).
    tot_halluc = sum((r["mismatched_notes"] if "mismatched_notes" in r else r["hallucinated_notes"]) for r in sel)
    tot_gold_notes = sum(r["gold_notes"] for r in sel)
    tot_captured = sum(r["captured_notes"] for r in sel)
    # Day-weighted (pooled) accuracy when every row carries its day counts, so a 28-day month and a
    # 31-day month weigh by their days (QA: day_level_aggregate_weights_days). Rows read from the
    # shipped v1 CSVs predate those columns and keep their case mean, so published files re-aggregate.
    if sel and all(r.get("correct_days") not in (None, "") and r.get("gold_days") not in (None, "") for r in sel):
        tot_days = sum(int(r["gold_days"]) for r in sel)
        day_accuracy = sum(int(r["correct_days"]) for r in sel) / tot_days if tot_days else None
    else:
        day_accuracy = mean([r["day_accuracy"] for r in sel])
    return {
        "cases": len(every),
        "day_accuracy": day_accuracy,
        "critical_error_rate": (tot_flips / tot_unavail) if tot_unavail else None,
        "critical_flips": tot_flips,
        "gold_unavailable_days": tot_unavail,
        "note_mismatch_rate": (tot_halluc / tot_pred_notes) if tot_pred_notes else None,
        "hallucination_rate": (tot_halluc / tot_pred_notes) if tot_pred_notes else None,  # RETIRED alias
        "note_fidelity": (tot_captured / tot_gold_notes) if tot_gold_notes else None,
        "format_validity": mean([1.0 if is_valid_row(r) else 0.0 for r in every]),
    }


def pct(v):
    return "n/a" if v is None else f"{100 * v:.1f}%"


# ---------------------------------------------------------------- main
MAX_CONSECUTIVE_PROVIDER_ERRORS = 3
RUN_OUTPUTS = ("metrics.json", "per_case.csv", "summary.md", "run_status.json", "raw")
CSV_COLS = ["case", "slice", "format_validity", "retried", "day_accuracy", "critical_error_rate",
            "critical_flips", "gold_unavailable_days", "hallucination_rate", "hallucinated_notes",
            "predicted_notes", "note_fidelity", "gold_notes", "captured_notes",
            "note_mismatch_rate", "mismatched_notes", "gold_days", "correct_days",
            "scored", "invalid_reason", "displaced_notes", "fabricated_notes", "provider_error"]


def archive_previous_run(out_dir):
    """Move an earlier run's outputs to <out>/_previous/<UTC stamp>/ before anything new is written.

    A rerun that fails part-way must not leave the earlier run's success metrics beside its own new
    raw files (QA: failed_rerun_does_not_leave_success_metrics_beside_new_raw). Nothing is deleted."""
    present = [n for n in RUN_OUTPUTS if os.path.exists(os.path.join(out_dir, n))]
    if not present:
        return None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest, k = os.path.join(out_dir, "_previous", stamp), 1
    while os.path.exists(dest):
        k += 1
        dest = os.path.join(out_dir, "_previous", f"{stamp}-{k}")
    os.makedirs(dest)
    for n in present:
        os.replace(os.path.join(out_dir, n), os.path.join(dest, n))
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="./data")
    ap.add_argument("--out", default="./results")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)

    # Everything that can refuse the run does so before the key is read or any call is made.
    if a.limit is not None and a.limit < 0:
        ap.error("--limit must be 0 or a positive integer")
    if a.limit == 0:
        ap.error("--limit 0 selects no cases; nothing to evaluate and no call was made")
    provider = provider_for(a.model)
    if provider is None:
        ap.error(f"cannot infer the provider from model name {a.model!r}; use a claude*, gpt* "
                 "or o<N>* model name. No call was made")
    cases = sorted(glob.glob(os.path.join(a.data, "sample_*.png")))
    if a.limit is not None:
        cases = cases[: a.limit]
    if not cases:
        ap.error(f"no sample_*.png files in {a.data}")

    key = get_key(provider)
    os.makedirs(a.out, exist_ok=True)
    archived = archive_previous_run(a.out)
    if archived:
        print(f"Moved the previous run's outputs to {archived}")
    raw_dir = os.path.join(a.out, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    rows, consecutive = [], 0
    for i, png in enumerate(cases, 1):
        base = os.path.basename(png)[:-4]
        slice_name = base.split("_")[-1]
        gold = json.load(open(os.path.join(a.data, base + ".gold.json"), encoding="utf-8"))
        retried = False
        try:
            # --- extraction (image only; gold is never sent) ---
            text = call_vision(a.model, key, png, TASK_PROMPT)
            open(os.path.join(raw_dir, base + ".txt"), "w", encoding="utf-8").write(text)
            pred = parse_json(text)
            if pred is None:
                retried = True
                text = call_vision(a.model, key, png, TASK_PROMPT + RETRY_SUFFIX)
                open(os.path.join(raw_dir, base + ".retry.txt"), "w", encoding="utf-8").write(text)
                pred = parse_json(text)
        except Exception as ex:   # provider or network failure, or a truncated answer: no usable model answer
            if isinstance(ex, TruncatedResponse):   # keep the cut-off text for inspection; never scored
                suffix = ".retry.truncated.txt" if retried else ".truncated.txt"
                open(os.path.join(raw_dir, base + suffix), "w", encoding="utf-8").write(ex.text)
            consecutive += 1
            s = provider_error_case(gold, type(ex).__name__)   # the message is not printed: it may echo input
            print(f"[{i}/{len(cases)}] {base:28s} PROVIDER ERROR ({type(ex).__name__}); not scored")
        else:
            consecutive = 0
            # --- scoring (local only; no API) ---
            s = evaluate_response(pred, gold)   # validates first; an invalid response is reported, not scored
            s["provider_error"] = ""
            if a.judge and s["unmatched_gold_notes"]:
                try:
                    s["note_fidelity_judge_extra"] = judge_notes(a.model, key, s["unmatched_gold_notes"])
                except Exception as ex:
                    s["judge_error"] = type(ex).__name__
            print(f"[{i}/{len(cases)}] {base:28s} day_acc={pct(s['day_accuracy'])} "
                  f"flips={'n/a' if s['critical_flips'] is None else len(s['critical_flips'])}/{s['gold_unavailable_days']} "
                  f"valid={s['format_validity']}")
        s["case"], s["slice"], s["retried"] = base, slice_name, retried
        rows.append(s)
        if consecutive >= MAX_CONSECUTIVE_PROVIDER_ERRORS and i < len(cases):
            print(f"Stopping after {consecutive} consecutive provider errors; {len(cases) - i} case(s) not run.")
            break

    not_run = len(cases) - len(rows)
    rows.sort(key=lambda r: r["case"])
    responded = [r for r in rows if r.get("invalid_reason") != "provider_error"]
    provider_errors = len(rows) - len(responded)
    scored = [r for r in responded if is_valid_row(r)]
    run_status = ("COMPLETE" if provider_errors == 0 and not_run == 0
                  else "FAILED" if not responded else "INCOMPLETE")
    exit_code = (1 if not responded else 4 if not scored else 3 if run_status == "INCOMPLETE" else 0)

    # per_case.csv and run_status.json are always written: every attempted case is accounted for.
    # Column order keeps the shipped v1 CSVs readable; later columns are appended (F03, r3, r4).
    with open(os.path.join(a.out, "per_case.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for r in rows:
            w.writerow([json.dumps(r.get(c)) if isinstance(r.get(c), list) else r.get(c) for c in CSV_COLS])
    status = {"run_status": run_status, "model": a.model, "cases_selected": len(cases),
              "cases_attempted": len(rows), "responded_cases": len(responded), "scored_cases": len(scored),
              "invalid_cases": len(responded) - len(scored), "provider_error_cases": provider_errors,
              "not_run_cases": not_run, "exit_code": exit_code}
    json.dump(status, open(os.path.join(a.out, "run_status.json"), "w"), indent=2)
    if not responded:
        print(f"Run FAILED: no case produced a model answer ({provider_errors} provider error(s), {not_run} "
              "not run). metrics.json and summary.md were not written; see per_case.csv and run_status.json.")
        return exit_code

    # Metrics describe the cases that produced a model answer; provider errors are counted, not scored.
    slices = sorted({r["slice"] for r in responded})
    overall = aggregate(responded)
    per_slice = {s: aggregate(responded, s) for s in slices}
    clean_acc = per_slice.get("clean", {}).get("day_accuracy") if per_slice.get("clean") else None
    robustness = {s: (clean_acc - per_slice[s]["day_accuracy"])
                  for s in slices if s != "clean" and clean_acc is not None and per_slice[s]
                  and per_slice[s]["day_accuracy"] is not None}

    judge_errors = sum(1 for r in scored if r.get("judge_error"))
    if a.judge:
        extra = sum(r.get("note_fidelity_judge_extra", 0) for r in scored)
        tot_gold = sum(r["gold_notes"] for r in scored)
        tot_cap = sum(r["captured_notes"] for r in scored)
        overall["note_fidelity_judge"] = (((tot_cap + extra) / tot_gold) if tot_gold else None) if not judge_errors else None

    typed = {k: sum(r[k] for r in scored) for k in ("predicted_notes", "mismatched_notes",
                                                     "displaced_notes", "fabricated_notes")}
    metrics = {"model": a.model, "run_status": run_status, "exit_code": exit_code, "cases": len(rows),
               "scored_cases": len(scored), "invalid_cases": len(responded) - len(scored),
               "provider_error_cases": provider_errors, "not_run_cases": not_run,
               "overall": overall, "per_slice": per_slice, "robustness_delta_vs_clean": robustness,
               "typed_notes": typed}
    if a.judge:
        metrics["judge_errors"] = judge_errors
    json.dump(metrics, open(os.path.join(a.out, "metrics.json"), "w"), indent=2)

    # summary.md — README-ready table
    with open(os.path.join(a.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"## Results — model: `{a.model}` ({len(rows)} cases)\n\n")
        f.write("| Metric | Overall | " + " | ".join(slices) + " |\n")
        f.write("|---|---|" + "---|" * len(slices) + "\n")
        for label, kf in [("Day-level accuracy", "day_accuracy"),
                          ("**Critical-error rate** (UNAVAILABLE→available)", "critical_error_rate"),
                          ("Note mismatch rate — NOT the typed split, see docs/CORRECTIONS.md",
                           "note_mismatch_rate"),
                          ("Note fidelity (normalized match)", "note_fidelity"),
                          ("Format validity", "format_validity")]:
            f.write(f"| {label} | {pct(overall[kf])} | "
                    + " | ".join(pct(per_slice[s][kf]) for s in slices) + " |\n")
        f.write("\nRobustness delta vs clean: "
                + ", ".join(f"{s}: {pct(v)}" for s, v in robustness.items()) + "\n")
        f.write(f"\nCritical flips: {overall['critical_flips']} across "
                f"{overall['gold_unavailable_days']} gold-UNAVAILABLE days.\n")
        f.write(f"\nInvalid responses (reported, not scored): {metrics['invalid_cases']} of {metrics['cases']}.\n")
        f.write(f"\nNote mismatches by type (scored cases): {typed['displaced_notes']} displaced, "
                f"{typed['fabricated_notes']} fabricated, of {typed['predicted_notes']} predicted note instances.\n")
        if not scored:
            f.write("\n**No case was scored: every model answer was invalid.** Rates are n/a; see invalid_reason "
                    "in per_case.csv.\n")
        if run_status != "COMPLETE":
            f.write(f"\n**Run status: {run_status}.** {provider_errors} provider error(s) (no model answer; "
                    f"not counted as format failures) and {not_run} case(s) not run. Rates above cover the "
                    f"{len(responded)} case(s) that produced a model answer.\n")
        if a.judge:
            f.write(f"\nNote fidelity (LLM-as-judge, bias acknowledged): {pct(overall.get('note_fidelity_judge'))}\n")

    print("\n" + open(os.path.join(a.out, "summary.md"), encoding="utf-8").read())
    print(f"Wrote {a.out}/metrics.json, per_case.csv, summary.md, run_status.json (raw responses in {raw_dir}/)")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
