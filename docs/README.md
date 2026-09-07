# docs/ — methods, corrections, limitations, pre-registration

Five documents. They exist so that a reader can answer five questions about this repository without asking anyone.

| # | The question | Answered in |
|---|---|---|
| 1 | What did you build? | [`METHODS.md`](METHODS.md) · the top-level `README.md` |
| 2 | What did it measure? | [`METHODS.md`](METHODS.md) §4–5 · `../analysis-v2.md` |
| 3 | **Where were you wrong?** | [`CORRECTIONS.md`](CORRECTIONS.md) — and the preserved `v1.0.0` tag |
| 4 | How do you know the instrument was good enough to trust? | [`LIMITATIONS.md`](LIMITATIONS.md) · [`PROBE.md`](PROBE.md) |
| 5 | **What would have changed your mind?** | [`PROBE.md`](PROBE.md) §3–4 and [`PROBE-B.md`](PROBE-B.md) §6 — two pre-registered decision rules, published before the data |

Rows 3 and 5 are the ones most evaluation repositories cannot answer. They are the reason this folder exists.

---

## Reading order

**If you have two minutes** — [`CORRECTIONS.md`](CORRECTIONS.md). It is the shortest route to knowing whether the rest is trustworthy, because it is where the project is wrong.

**If you are deciding whether to reuse this** — [`LIMITATIONS.md`](LIMITATIONS.md) first. It says what the benchmark cannot tell you, including that it is **saturated** and cannot rank frontier models.

**If you are reproducing it** — [`METHODS.md`](METHODS.md). Every number is re-derivable from `per_case.csv`, `typed_errors.json` and `calendar_level.csv`; the raw model text is regenerable by re-running the harness and is **not** shipped.

**If you want to know whether the author changes his mind when the data says so** — [`PROBE.md`](PROBE.md) and [`PROBE-B.md`](PROBE-B.md), then check the commit dates.

---

## The short version

A frontier model reads cleanly-rendered nurse availability calendars **essentially perfectly** — 0 status errors in 1,240 cells. A smaller model does not — 26 errors, 6 of them the asymmetric-cost kind.

One of this project's own headline metrics, a **"hallucination rate,"** was named for a failure it never tested. Every counted instance was text present on the page, attached to the wrong day. **Measured fabrication: 0 of 146 gold note items per model** (Wilson 95% upper bound **2.6%** each; 0 of 292 pooled across both models, upper bound 1.30% — the pooled figure merges two different systems and is quoted only where that is stated). The metric is retired and the correction is public, with `v1.0.0` preserved so the two can be read side by side.

Because the benchmark is saturated, it cannot answer the harder question — whether a **real hand under real authoring conditions** breaks extraction where a rendered font does not. [`PROBE.md`](PROBE.md) pre-registers that test, with the disqualifying result and the reachability arithmetic written down first.

---

*Author: Galen Coulter-Ledbetter, RN, Paramedic.*
