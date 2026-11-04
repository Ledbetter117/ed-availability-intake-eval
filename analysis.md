# Failure-Mode Analysis — Scored Runs of 2026-08-13

> Every number below is traceable to `results*/per_case.csv`, or, for the typed counts, to `typed_errors.json`; raw model output per case is archived locally (`results*/raw/`, gitignored). Nothing is smoothed or dropped.

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

## Finding 1 — the recorded Sonnet run reaches the status ceiling on this corpus

The saved run records 100% day-level accuracy on all four slices, zero critical flips, and zero observed accuracy difference from the clean slice. It also contains a duplicated note, so this is not perfect document extraction. These observations describe one stored run on this synthetic corpus. They do not establish a model class's safety or rank current frontier models. A harder tier is proposed in `V2_TIER_DESIGN.md`.

## Finding 2 (CORRECTED 2026-09) — the note-bleed is **displacement**, not fabrication

> **Superseded.** The original Finding 2 described these as "invented" notes. A typed re-score found every counted note was text already present on the page, attached to the wrong day. Full correction: [`docs/CORRECTIONS.md`](docs/CORRECTIONS.md) §1 · re-score: [`analysis-v2.md`](analysis-v2.md) §A3.

**Case S1 · `sample_01_clean` · claude-sonnet-5 (its only error in 40 cases).** Gold has "charge only" on July 2. The model emitted "charge only" on **both July 2 and July 1** — July 1's cell carries a status but no note. `claude-haiku-4-5` made a same-shaped error on `sample_13_clean`.

The v1 metric named `hallucination_rate` (`run_eval.py:175`) counts any predicted note differing from *that day's* gold note. It never tested whether the note appeared anywhere on the page. On this data **every such note — 1 for Sonnet, 9 for Haiku, 7 of those in Haiku's rotated slice — is text present elsewhere on the same page.** A note attached to the wrong day, not an invented one.

**Measured fabrication rate: 0.0% for both models:** 0 / 147 for Sonnet and 0 / 145 for Haiku (Wilson 95% upper 2.5% and 2.6%; pooled across both models, 0 / 292, upper 1.30%). The published "22.6% hallucination rate" for the rotated slice is a **displacement** rate. The metric's name did not match its behaviour; the name is retired and the typed split in `analysis-v2.md` replaces it.

*Potential downstream consequence, not tested:* a scheduler could see a restriction attached to an unintended day if the transcription were accepted without correction. The output passes JSON parsing despite the misplaced note.

*Interpretation:* the duplicated on-page notes are consistent with a cell-attribution error. The experiment does not establish the model's internal cause or demonstrate which intervention would correct it.

## Finding 3 — many recorded errors are consistent with displaced content

The synthetic handwriting-font slice has no recorded errors in this run. That observation does not isolate symbol recognition as a cause: content and rendering differ together between slices. Many errors are consistent with **spatial indexing**: content assigned to the wrong grid cell. 19 of the 20 non-flip status errors carry the `DISPLACED` label, where about 10 would by chance, and the three flips in `sample_11_lowcontrast` are consistent with the same one-day shift. There are two exceptions: one misread status (`sample_27_lowcontrast`) and one note that was not produced anywhere (`sample_06_rotated`).

**Case H1 · `sample_11_lowcontrast` · the one-day shift cascade (worst case: 71% day accuracy, 3 critical flips).** The status sequence is correct but displaced one day forward: gold July 3 NIGHT appears on predicted July 4; gold July 7 PM on predicted July 8; gold July 9 AM on predicted July 10. One run of days read one cell off on a faint grid (July 3–11) corrupted 9 days and produced **three phantom-available days** (July 4, 8, 11 — all gold-UNAVAILABLE).
*Potential downstream consequence, not tested:* three days would incorrectly appear available if this output were used without review. The evaluation did not test scheduling decisions or staffing outcomes.

**Case H2 · `sample_02_rotated` · the one-week note shift.** Both gold notes were read correctly but attached exactly +7 days down: "no call" July 18 → 25, "early out" July 24 → 31. The v1 metric layer scored this as 2 "hallucinations" (the retired name — these are displaced notes; see Finding 2) plus 0% note fidelity. The pattern is consistent with a week-row attribution error; the experiment did not isolate its cause. The same case also flipped July 4 (UNAVAILABLE → AVAILABLE).
*Scoring note kept honest:* note mismatch (v1's retired "hallucination" metric) and fidelity are reported as measured. That two metrics light up from one geometric root is stated here rather than re-scored.

**Distribution.** All 6 critical flips on degraded slices: `sample_02_rotated` (1), `sample_11_lowcontrast` (3), `sample_27_lowcontrast` (1), `sample_31_lowcontrast` (1). Rotated-slice note damage: displacement/fidelity loss on samples 02, 06, 10, 18, 26, 38.

## Guardrail mapping (proposed, not implemented or tested)

Employee confirmation of the parsed month, confidence-based review, and date-anchor verification are proposed controls. Their detection rates and practical effectiveness were not measured. Every erroneous historical response parsed as JSON, so format validity alone did not detect these transcription errors.

## What this sets up

The observed patterns motivate testing deskewing, date anchors, and verification in a future study. The current results do not show that these changes close the performance gap. The proposed search would use newly seeded generations; the historical corpus remains available unchanged.

## Limitations of these runs

Single run per recorded model label (variance check still open on the roadmap). Synthetic artifacts differ from field documents; real-photograph performance is unknown, and these accuracies are not mathematical upper bounds. The source records name two models and one provider; provider identity was not independently authenticated by the later re-score. Slice-level Ns are small (10 cases/slice); per-slice rates are observed counts, not stable population estimates.

*Framing corrected 2026-11-03. Counts and original historical files are preserved; earlier interpretations remain in Git history.*
