"""Offline, strict calendar scoring. No inference or network access."""
import argparse
import calendar
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics

STATUSES = {"AVAILABLE", "AM", "PM", "NIGHT", "UNAVAILABLE", "NOT_SPECIFIED"}
AVAILABLE = {"AVAILABLE", "AM", "PM", "NIGHT"}
CONDITIONS = ("typed", "handwriting", "degraded")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def strict_json(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("response must be text of at most 1 MiB")
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def valid_prediction(value):
    if not isinstance(value, dict) or set(value) != {"month", "days", "global_notes"}:
        raise ValueError("top-level fields")
    month = value["month"]
    if not isinstance(month, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        raise ValueError("month format")
    year, mon = map(int, month.split("-"))
    if year < 1 or not 1 <= mon <= 12:
        raise ValueError("month range")
    dates = {f"{month}-{day:02d}" for day in range(1, calendar.monthrange(year, mon)[1] + 1)}
    days = value["days"]
    if not isinstance(days, dict) or set(days) != dates:
        raise ValueError("date set does not equal actual month")
    for item in days.values():
        if not isinstance(item, dict) or set(item) != {"status", "note"}:
            raise ValueError("day fields")
        if not isinstance(item["status"], str) or item["status"] not in STATUSES:
            raise ValueError("status")
        if not isinstance(item["note"], str):
            raise ValueError("note type")
    if not isinstance(value["global_notes"], list) or any(not isinstance(x, str) for x in value["global_notes"]):
        raise ValueError("global notes type")
    return value


def score_one(gold, observation):
    valid_prediction(gold)
    days = gold["days"]
    notes = [d for d in days if days[d]["note"]]
    off = [d for d in days if days[d]["status"] == "UNAVAILABLE"]
    out = {"observed": observation is not None, "schema_valid": False, "month_correct": False,
           "calendar_exact": False, "status_correct": 0, "status_total": len(days),
           "note_correct": 0, "note_total": len(days), "nonempty_note_correct": 0,
           "nonempty_note_total": len(notes), "global_notes_exact": False,
           "critical_flips": None, "unavailable_total": len(off), "failure": "not_observed"}
    if observation is None:
        return out
    if observation["outcome"] != "response":
        out["failure"] = observation["outcome"]
        return out
    if observation.get("finish_reason") not in {"stop", "end_turn", "eos", "eos_token", "completed"}:
        out["failure"] = "noncomplete_finish"
        return out
    try:
        pred = valid_prediction(strict_json(observation["text"]))
    except (ValueError, TypeError, RecursionError) as error:
        out["failure"] = "invalid_json_or_schema: " + str(error)[:160]
        return out
    out["schema_valid"] = True
    out["month_correct"] = pred["month"] == gold["month"]
    if not out["month_correct"]:
        out["failure"] = "wrong_month"
        return out
    out["failure"] = None
    out["status_correct"] = sum(pred["days"][d]["status"] == cell["status"] for d, cell in days.items())
    out["note_correct"] = sum(pred["days"][d]["note"] == cell["note"] for d, cell in days.items())
    out["nonempty_note_correct"] = sum(pred["days"][d]["note"] == days[d]["note"] for d in notes)
    out["global_notes_exact"] = pred["global_notes"] == gold["global_notes"]
    out["critical_flips"] = sum(pred["days"][d]["status"] in AVAILABLE for d in off)
    out["calendar_exact"] = pred == gold
    return out


def wilson(successes, total):
    z = 1.959963984540054
    p = successes / total
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return [max(0.0, center - radius), min(1.0, center + radius)]


def paired_summary(differences):
    rng = random.Random(2026110302)
    draws = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(10000))
    return {"n_calendars": len(differences), "mean_difference": statistics.mean(differences),
            "bootstrap_95_percentile": [draws[249], draws[9749]],
            "bootstrap_draws": 10000, "seed": 2026110302,
            "degenerate": draws[0] == draws[-1], "paired_differences": differences}


def verify_freeze(root):
    freeze = json.loads((root / "FREEZE.json").read_text(encoding="utf-8"))
    for row in freeze["files"]:
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError("frozen input changed: " + row["path"])
    return freeze


def load_observations(path, known):
    paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    values = []
    for filename in paths:
        item = strict_json(filename.read_text(encoding="utf-8"))
        values.extend(item if isinstance(item, list) else [item])
    indexed = {}
    for item in values:
        if not isinstance(item, dict) or item.get("request_id") not in known:
            raise ValueError("unknown or missing request ID")
        rid = item["request_id"]
        if rid in indexed:
            raise ValueError("duplicate observation: " + rid)
        if item.get("outcome") not in {"response", "transport_error", "timeout", "refused"}:
            raise ValueError("unknown outcome")
        if not isinstance(item.get("text", ""), str):
            raise ValueError("observation text must be a string")
        if item["outcome"] == "response" and not isinstance(item.get("finish_reason"), str):
            raise ValueError("response requires actual finish reason")
        indexed[rid] = item
    return indexed


def evaluate(root, observation_path):
    verify_freeze(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    known = {r["request_id"] for r in manifest["images"]}
    observations = load_observations(observation_path, known)
    rows = []
    for row in manifest["images"]:
        gold_path = (root / row["gold"]).resolve()
        if not gold_path.is_relative_to(root.resolve()):
            raise ValueError("gold path escapes corpus")
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        result = score_one(gold, observations.get(row["request_id"]))
        rows.append({"request_id": row["request_id"], "calendar_id": row["calendar_id"],
                     "condition": row["condition"], "month": gold["month"], **result})
    conditions = {}
    for condition in CONDITIONS:
        group = [r for r in rows if r["condition"] == condition]
        success = sum(r["calendar_exact"] for r in group)
        conditions[condition] = {"scheduled": len(group), "observed": sum(r["observed"] for r in group),
            "calendar_exact": success, "calendar_exact_fraction": success / len(group),
            "calendar_exact_wilson_95": wilson(success, len(group)),
            "schema_valid": sum(r["schema_valid"] for r in group),
            "mean_status_accuracy": statistics.mean(r["status_correct"] / r["status_total"] for r in group),
            "status_correct": sum(r["status_correct"] for r in group),
            "status_total": sum(r["status_total"] for r in group),
            "note_correct": sum(r["note_correct"] for r in group),
            "note_total": sum(r["note_total"] for r in group),
            "nonempty_note_correct": sum(r["nonempty_note_correct"] for r in group),
            "nonempty_note_total": sum(r["nonempty_note_total"] for r in group),
            "critical_flips_in_scored_responses": sum(r["critical_flips"] or 0 for r in group),
            "unscorable_calendars": sum(r["failure"] is not None for r in group)}
    paired = {}
    ids = sorted({r["calendar_id"] for r in rows})
    indexed = {(r["calendar_id"], r["condition"]): r for r in rows}
    for a, b in (("handwriting", "typed"), ("degraded", "handwriting"), ("degraded", "typed")):
        name = a + "_minus_" + b
        paired[name] = {}
        for metric in ("calendar_exact", "status_accuracy"):
            def value(row):
                return int(row["calendar_exact"]) if metric == "calendar_exact" else row["status_correct"] / row["status_total"]
            paired[name][metric] = paired_summary([value(indexed[c, a]) - value(indexed[c, b]) for c in ids])
    return {"edition": "SIMULATION", "freeze_sha256": sha(root / "FREEZE.json"),
            "scheduled": len(known), "observed": len(observations),
            "observation_coverage_complete": len(known) == len(observations),
            "conditions": conditions, "paired": paired, "rows": rows,
            "limits": "Twelve synthetic calendar clusters; font renders are not human handwriting. Descriptive intervals do not establish population or clinical reliability. Failures remain in all scheduled denominators."}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit("REFUSED: output directory exists; preserve prior results")
    result = evaluate(args.root.resolve(), args.observations)
    args.out.mkdir(parents=True)
    (args.out / "SCORES.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scheduled": result["scheduled"], "observed": result["observed"], "output": str(args.out / "SCORES.json")}))


if __name__ == "__main__":
    main()
