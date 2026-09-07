# Failure-Mode Analysis — Scored Runs of 2026-08-13

> Every number below is traceable to `results*/per_case.csv`; raw model output per case is archived locally (`results*/raw/`, gitignored). Nothing is smoothed or dropped.

## Run conditions

Both runs: the shipped seed-7 dataset, all 40 cases, single run per model, temperature/model defaults, Anthropic API, extraction prompt identical, gold labels never sent, scoring fully local. Zero format retries were triggered on either model — every response parsed on the first attempt.

| | `claude-sonnet-5` | `claude-haiku-4-5` |
|---|---|---|
| **Critical-error rate** | **0.0%** (0/316) | **1.9%** (6/316) |
| Day-level accuracy | 100.0% | 97.9% |
| Note displacement rate — v1 called this "hallucination rate"; see Finding 2 and `analysis-v2.md` §A3 | 0.7% | 6.2% |
| Note fidelity | 100.0% | 93.2% |
| Format validity | 100.0% | 100.0% |

Haiku per-slice: clean and handwritten **perfect** on every metric except one clean-slice note (below); lowcontrast 94.2% day accuracy with a **5.7% critical-error rate**; rotated 97.4% day accuracy with **22.6% note displacement** (every one of those notes is on the page, attached to the wrong day — v1 reported this as "hallucination"; see Finding 2) and 75.0% note fidelity.

## Finding 1 — Sonnet 5 saturates this tier

100% day-level accuracy on all four slices, zero critical flips, zero robustness delta. The v1 difficulty tier no longer discriminates at the frontier: as of 2026-08, a frontier vision model reads these calendars — including the pen-jitter handwritten slice — essentially perfectly. Consequence: v1 results should be read as a floor-check ("is this model class safe on clean-to-moderately-degraded intake?"), and discrimination work moves to the v2 tier (`V2_TIER_DESIGN.md`).

## Finding 2 (CORRECTED 2026-09) — the note-bleed is **displacement**, not fabrication

> **Superseded.** The original Finding 2 described these as "invented" notes. A typed re-score found every counted note was text already present on the page, attached to the wrong day. Full correction: [`docs/CORRECTIONS.md`](docs/CORRECTIONS.md) §1 · re-score: [`analysis-v2.md`](analysis-v2.md) §A3.

**Case S1 · `sample_01_clean` · claude-sonnet-5 (its only error in 40 cases).** Gold has "charge only" on July 2. The model emitted "charge only" on **both July 2 and July 1** — July 1's cell is empty. `claude-haiku-4-5` made a same-shaped error on `sample_13_clean`.

The v1 metric named `hallucination_rate` (`run_eval.py:175`) counts any predicted note differing from *that day's* gold note. It never tested whether the note appeared anywhere on the page. On this data **every such note — 1 for Sonnet, 9 for Haiku, 7 of those in Haiku's rotated slice — is text present elsewhere on the same page.** A note attached to the wrong day, not an invented one.

**Measured fabrication rate: 0.0% for both models** (0 / 292 gold note items across both models — 146 each; Wilson 95% upper bound 1.30%). The published "22.6% hallucination rate" for the rotated slice is a **displacement** rate. The metric's name did not match its behaviour; the name is retired and the typed split in `analysis-v2.md` replaces it.

*Staffing consequence (unchanged):* a phantom qualifier. The scheduler believes this nurse is charge-restricted on a day she never annotated. Milder than a flip, but it survives every "does it parse?" check because the JSON is perfectly valid.

*Root-cause read:* **adjacency bleed** — an annotation attributed to a neighbouring cell. That it appears on **both** models on the **clean** slice points at cell-attribution, not legibility. The corrected typing sharpens this: it is a spatial-binding failure, and remediation belongs at the layout, not at the model's grounding.

## Finding 3 — Haiku's failures are geometric, not glyphic

Handwritten slice: perfect. Symbol recognition is not the weakness. Every Haiku failure is a **spatial-indexing** failure — content read correctly but assigned to the wrong grid cell.

**Case H1 · `sample_11_lowcontrast` · the one-day shift cascade (worst case: 71% day accuracy, 3 critical flips).** The status sequence is correct but displaced one day forward: gold July 3 NIGHT appears on predicted July 4; gold July 7 PM on predicted July 8; gold July 9 AM on predicted July 10. One row-alignment error on a faint grid corrupted 9 days and produced **three phantom-available days** (July 4, 8, 11 — all gold-UNAVAILABLE).
*Staffing consequence:* three shifts this month could be scheduled against a nurse who marked X — each an unstaffed-ED discovery at shift change, from a single misread document.

**Case H2 · `sample_02_rotated` · the one-week note shift.** Both gold notes were read correctly but attached exactly +7 days down: "no call" July 18 → 25, "early out" July 24 → 31. The v1 metric layer scored this as 2 "hallucinations" (the retired name — these are displaced notes; see Finding 2) plus 0% note fidelity; the underlying cause is a single week-row misindex under a 4° rotation. Same case also flipped July 4 (UNAVAILABLE → AVAILABLE).
*Scoring note kept honest:* hallucination and fidelity are reported as measured. That two metrics light up from one geometric root is stated here rather than re-scored.

**Distribution.** All 6 critical flips on degraded slices: `sample_02_rotated` (1), `sample_11_lowcontrast` (3), `sample_27_lowcontrast` (1), `sample_31_lowcontrast` (1). Rotated-slice note damage: displacement/fidelity loss on samples 02, 06, 10, 18, 26, 38.

## Guardrail mapping (from README, now evidence-backed)

Employee e-confirmation of the parsed month: catches every failure class observed, including all 6 flips — strongest single control. Per-cell confidence routing to human review: targets exactly the faint-cell and rotated-cell reads where all flips occurred. Schema/sanity validators: caught nothing here and would not have — every failed case was schema-perfect. This is the eval's core lesson restated: **format validity is not safety.** Date-anchor verification (re-reading row/column headers against extracted dates) is the new guardrail this analysis motivates; it directly targets H1/H2-class shifts.

## What this sets up

The Haiku failure surface is systematic, recurring, and harness-addressable (deskew/anchor/verify logic, not model retraining) — the precondition for the roadmap's automated harness-search phase: can a searched harness close the Haiku→Sonnet gap at Haiku's price point? v1 stays frozen as the held-out benchmark; search runs against newly seeded generations.

## Limitations of these runs

Single run per model (variance check still open on the roadmap). Synthetic artifacts remain cleaner than field documents; all accuracies are upper bounds. Two models, one provider, one date. Slice-level Ns are small (10 cases/slice); per-slice rates carry wide intervals and are reported as observed counts, not stable estimates.
