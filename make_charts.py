#!/usr/bin/env python3
"""Render results charts from results/metrics.json + results/per_case.csv.

Run AFTER run_eval.py. No API calls; local files only.
Requires matplotlib (charts only; the dataset generator also needs Pillow).
Install both with: pip install -r requirements.txt

Usage:
    python3 make_charts.py [--results ./results]
"""
import os, json, csv, argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

DARK = {"bg": "#111318", "panel": "#1a1d24", "fg": "#e8e8e8", "grid": "#333845",
        "bar": "#4f9cf7", "crit": "#e05252", "warn": "#e0a852", "ok": "#52b788"}


def style(ax, title):
    ax.set_facecolor(DARK["panel"])
    ax.figure.set_facecolor(DARK["bg"])
    ax.set_title(title, color=DARK["fg"], fontsize=13, pad=12)
    ax.tick_params(colors=DARK["fg"])
    for s in ax.spines.values():
        s.set_color(DARK["grid"])
    ax.grid(axis="y", color=DARK["grid"], linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)


def save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=DARK["bg"])
    plt.close(fig)
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="./results")
    a = ap.parse_args()
    m = json.load(open(os.path.join(a.results, "metrics.json")))
    slices = sorted(m["per_slice"])
    out = os.path.join(a.results, "charts")
    os.makedirs(out, exist_ok=True)

    # 1. day accuracy by slice
    fig, ax = plt.subplots(figsize=(7, 4.2))
    vals = [100 * m["per_slice"][s]["day_accuracy"] for s in slices]
    bars = ax.bar(slices, vals, color=DARK["bar"])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.1f}%", ha="center",
                color=DARK["fg"], fontsize=10)
    ax.set_ylim(0, 105)
    ax.set_ylabel("day-level accuracy (%)", color=DARK["fg"])
    style(ax, f"Day-level accuracy by difficulty slice — {m['model']}")
    save(fig, os.path.join(out, "day_accuracy_by_slice.png"))

    # 2. error-type breakdown (from per_case.csv)
    crit = benign = halluc = 0
    with open(os.path.join(a.results, "per_case.csv")) as f:
        for r in csv.DictReader(f):
            # An invalid response is reported in per_case.csv but never scored (run_eval candidate
            # 2026-10-16); its model-side fields are empty, so it adds nothing to this breakdown.
            if str(r.get("format_validity", "True")).strip().lower() not in ("true", "1", "1.0"):
                continue
            flips = json.loads(r["critical_flips"]) if r["critical_flips"].startswith("[") else []
            crit += len(flips)
            # Count days when the run recorded them. Historical v1 CSVs predate those columns
            # and are all July (31 days), so the old reconstruction is kept only as a fallback.
            # Multiplying by a fixed 31 mis-plots any month of another length (QA finding F18).
            if r.get("gold_days") and r.get("correct_days"):
                days_wrong = int(r["gold_days"]) - int(r["correct_days"])
            else:
                days_wrong = round((1 - float(r["day_accuracy"])) * 31)
            benign += max(days_wrong - len(flips), 0)
            # Retired-name fallback for the v1 CSVs (QA finding F03).
            halluc += int(r.get("mismatched_notes") or r["hallucinated_notes"])
    fig, ax = plt.subplots(figsize=(7, 4.2))
    cats = ["critical flips\n(UNAVAIL→avail)", "benign status\nmisses", "mismatched\nnotes"]
    vals = [crit, benign, halluc]
    bars = ax.bar(cats, vals, color=[DARK["crit"], DARK["warn"], DARK["bar"]])
    # Label offset scales with the axis. A fixed +0.3 drew labels above the title
    # whenever the largest count was 1 (the Sonnet chart).
    top = max(max(vals), 1)
    ax.set_ylim(0, top * 1.15)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))   # counts, not fractions
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + top * 0.02, str(v), ha="center",
                color=DARK["fg"], fontsize=11)
    ax.set_ylabel("count (all cases)", color=DARK["fg"])
    style(ax, "Error-type breakdown — not all errors are equal")
    save(fig, os.path.join(out, "error_breakdown.png"))

    # 3. robustness delta vs clean
    rob = m.get("robustness_delta_vs_clean", {})
    if rob:
        fig, ax = plt.subplots(figsize=(7, 4.2))
        ks = sorted(rob)
        vals = [100 * rob[k] for k in ks]
        bars = ax.bar(ks, vals, color=[DARK["ok"] if v <= 2 else DARK["warn"] if v <= 10 else DARK["crit"] for v in vals])
        span = max(max(vals) - min(vals), max(abs(v) for v in vals), 1)
        ax.set_ylim(min(0, min(vals)) - span * .05, max(0, max(vals)) + span * .2)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + span * .03, f"{v:+.1f} pp", ha="center",
                    color=DARK["fg"], fontsize=10)
        ax.set_ylabel("accuracy drop vs clean (pp)", color=DARK["fg"])
        style(ax, "Observed accuracy difference from clean slice")
        save(fig, os.path.join(out, "robustness_delta.png"))


if __name__ == "__main__":
    main()
