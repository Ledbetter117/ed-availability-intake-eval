#!/usr/bin/env python3
"""Render results charts from results/metrics.json + results/per_case.csv.

Run AFTER run_eval.py. No API calls; local files only.
Requires matplotlib (the only non-stdlib dependency in this repo, and only
for charts): pip install matplotlib

Usage:
    python3 make_charts.py [--results ./results]
"""
import os, json, csv, argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
            flips = json.loads(r["critical_flips"]) if r["critical_flips"].startswith("[") else []
            crit += len(flips)
            days_wrong = round((1 - float(r["day_accuracy"])) * 31)
            benign += max(days_wrong - len(flips), 0)
            halluc += int(r["hallucinated_notes"])
    fig, ax = plt.subplots(figsize=(7, 4.2))
    cats = ["critical flips\n(UNAVAIL→avail)", "benign status\nmisses", "hallucinated\nnotes"]
    vals = [crit, benign, halluc]
    bars = ax.bar(cats, vals, color=[DARK["crit"], DARK["warn"], DARK["bar"]])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.3, str(v), ha="center",
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
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.3, f"{v:+.1f} pp", ha="center",
                    color=DARK["fg"], fontsize=10)
        ax.set_ylabel("accuracy drop vs clean (pp)", color=DARK["fg"])
        style(ax, "Robustness: accuracy penalty of degraded inputs")
        save(fig, os.path.join(out, "robustness_delta.png"))


if __name__ == "__main__":
    main()
