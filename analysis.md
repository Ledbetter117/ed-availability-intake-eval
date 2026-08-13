# Failure-Mode Analysis — Scored Runs of 2026-08-13

> Every number below is traceable to `results*/per_case.csv`; raw model output per case is archived locally (`results*/raw/`, gitignored). Nothing is smoothed or dropped.

## Run conditions

Both runs: the shipped seed-7 dataset, all 40 cases, single run per model, temperature/model defaults, Anthropic API, extraction prompt identical, gold labels never sent, scoring fully local. Zero format retries were triggered on either model — every response parsed on the first attempt.

| | `claude-sonnet-5` | `claude-haiku-4-5` |
|---|---|---|
| **Critical-error rate** | **0.0%** (0/316) | **1.9%** (6/316) |
| Day-level accuracy | 100.0% | 97.9% |
| Hallucination rate (notes) | 0.7% | 6.2% |
| Note fidelity | 100.0% | 93.2% |
| Format validity | 100.0% | 100.0% |

Haiku per-slice: clean and handwritten **perfect** on every metric except one clean-slice note (below); lowcontrast 94.2% day accuracy with a **5.7% critical-error rate**; rotated 97.4% day accuracy with **22.6% note hallucination** and 75.0% note fidelity.

## Finding 1 — Sonnet 5 saturates this tier

100% day-level accuracy on all four slices, zero critical flips, zero robustness delta. The v1 difficulty tier no longer discriminates at the frontier: as of 2026-08, a frontier vision model reads these calendars — including the pen-jitter handwritten slice — essentially perfectly. Consequence: v1 results should be read as a floor-check ("is this model class safe on clean-to-moderately-degraded intake?"), and discrimination work moves to the v2 tier (`V2_TIER_DESIGN.md`).

## Finding 2 — the note-bleed (both models, clean slice)

**Case S1 · `sample_01_clean` · Sonnet 5 (its only error in 40 cases).** Gold has "charge only" on July 2. The model output "charge only" on **both July 2 and July 1** — July 1's cell is empty. **Haiku made a same-shaped error on `sample_13_clean`** (1 invented note on a clean calendar).

*Staffing consequence:* a phantom qualifier. The scheduler now believes this nurse is charge-restricted on a day she never annotated — wrongly narrowing (or mis-slotting) assignment options. Milder than a flip, but it survives every "does it parse?" check because the JSON is perfectly valid.

*Root-cause read:* adjacency bleed — an annotation attributed to a neighboring cell. That it appears on **both** models on the **clean** slice suggests a general weak point of cell-attribution rather than a legibility problem.

## Finding 3 — Haiku's failures are geometric, not glyphic

Handwritten slice: perfect. Symbol recognition is not the weakness. Every Haiku failure is a **spatial-indexing** failure — content read correctly but assigned to the wrong grid cell.

**Case H1 · `sample_11_lowcontrast` · the one-day shift cascade (worst case: 71% day accuracy, 3 critical flips).** The status sequence is correct but displaced one day forward: gold July 3 NIGHT appears on predicted July 4; gold July 7 PM on predicted July 8; gold July 9 AM on predicted July 10. One row-alignment error on a faint grid corrupted 9 days and produced **three phantom-available days** (July 4, 8, 11 — all gold-UNAVAILABLE).
*Staffing consequence:* three shifts this month could be scheduled against a nurse who marked X — each an unstaffed-ED discovery at shift change, from a single misread document.

**Case H2 · `sample_02_rotated` · the one-week note shift.** Both gold notes were read correctly but attached exactly +7 days down: "no call" July 18 → 25, "early out" July 24 → 31. The metric layer scores this as 2 hallucinations plus 0% note fidelity; the underlying cause is a single week-row misindex under a 4° rotation. Same case also flipped July 4 (UNAVAILABLE → AVAILABLE).
*Scoring note kept honest:* hallucination and fidelity are reported as measured. That two metrics light up from one geometric root is stated here rather than re-scored.

**Distribution.** All 6 critical flips on degraded slices: `sample_02_rotated` (1), `sample_11_lowcontrast` (3), `sample_27_lowcontrast` (1), `sample_31_lowcontrast` (1). Rotated-slice note damage: hallucinations/fidelity loss on samples 02, 06, 10, 18, 26, 38.

## Guardrail mapping (from README, now evidence-backed)

Employee e-confirmation of the parsed month: catches every failure class observed, including all 6 flips — strongest single control. Per-cell confidence routing to human review: targets exactly the faint-cell and rotated-cell reads where all flips occurred. Schema/sanity validators: caught nothing here and would not have — every failed case was schema-perfect. This is the eval's core lesson restated: **format validity is not safety.** Date-anchor verification (re-reading row/column headers against extracted dates) is the new guardrail this analysis motivates; it directly targets H1/H2-class shifts.

## What this sets up

The Haiku failure surface is systematic, recurring, and harness-addressable (deskew/anchor/verify logic, not model retraining) — the precondition for the roadmap's automated harness-search phase: can a searched harness close the Haiku→Sonnet gap at Haiku's price point? v1 stays frozen as the held-out benchmark; search runs against newly seeded generations.

## Limitations of these runs

Single run per model (variance check still open on the roadmap). Synthetic artifacts remain cleaner than field documents; all accuracies are upper bounds. Two models, one provider, one date. Slice-level Ns are small (10 cases/slice); per-slice rates carry wide intervals and are reported as observed counts, not stable estimates.
