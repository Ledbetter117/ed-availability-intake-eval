# analysis-v2 — metric audit and correction

Computed 2026-09-03 with `ed-eval-probe/probe_score.py` (self-test PASS; integration test 9/9; reproduces v1's `results/summary.md` exactly). **Corrected the same day after an adversarial review pass:** the first draft quoted a denominator of 292 while the scorer examined only the 248 day-notes. Global notes are now scored as items exactly as v1's scorer did; the denominator below is the number of items the scorer actually examined.

## A2 · Typed split of every counted error, both models

| model | status errors | critical flips | DISPLACED | MISREAD | MISSING | DISPLACED chance floor | gold note items examined | note OK | note OMISSION | note DISPLACED (page-present) | note FABRICATED |
|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5 (v1 run, as recorded in results/metrics.json) | 0 | 0 | 0 | 0 | 0 | 0.50 | 146 | 146 | 0 | 1 | **0** |
| claude-haiku-4-5 (v1 run, as recorded in results_haiku/metrics.json) | 26 | 6 | 19 | 1 | 0 | 0.50 | 146 | 136 | 10 | 9 | **0** |

*`note OK` and `note OMISSION` partition the 146 gold note items. `note DISPLACED` and `note FABRICATED` are counted over predicted note instances — 147 for Sonnet, 145 for Haiku. See `typed_errors.json` → `_schema`.*

**Reading.** Across 80 outputs the scorer examined **292 gold note items** (124 day-notes + 22 global notes, per model) and **292 predicted note instances** (147 Sonnet, 145 Haiku); **0 of the predicted instances were fabricated** — every counted note "hallucination" (10) is text present elsewhere on the same page. **Fabrication rate 0.0%, pooled across both models (Wilson 95% upper bound 1.30%; per model 2.5% and 2.6%).** Haiku made 26 status errors: 6 critical flips, 19 labelled DISPLACED, 1 misread. **The DISPLACED label's chance floor on this data is 0.50** (five codes, up to four neighbours). The labels are mutually exclusive and a critical flip takes precedence, so only 20 errors could carry DISPLACED. About 10 of them would by chance (9.9 using each document's own floor); 19 do, an excess of about 9. Those 19 come from 8 of the 40 documents, and 6 of them come from one run of days read one cell off in `sample_11_lowcontrast` (July 3–11). Cells within a document are not independent, so read this as consistent with whole-row shifts, not as a measured rate. *(Corrected 2026-09-25: this paragraph first counted all 26 errors as eligible, which gave ~13 by chance and an excess of 6.)*

## A3 · Corrected Finding 2 (replaces `analysis.md` Finding 2 verbatim when moved in)

> **Finding 2 (corrected).** The v1 metric named `hallucination_rate` (`run_eval.py:175`) counts any predicted note that differs from *that day's* gold note. On this data every such note — 1 for Sonnet, 9 for Haiku, 7 of those in Haiku's rotated slice — is text present elsewhere on the same page: a note attached to the wrong day, not an invented one. **The measured fabrication rate is 0.0% for both models: 0 / 147 for Sonnet and 0 / 145 for Haiku (Wilson 95% upper 2.5% and 2.6%; pooled across both models, 0 / 292, upper 1.30%).** The published "22.6% hallucination rate" for the rotated slice is a *displacement* rate. The metric's name did not match its behaviour; the name is retired and the typed split above replaces it. Model of record: `claude-sonnet-5` (`results/metrics.json`) and `claude-haiku-4-5` (`results_haiku/metrics.json`) — the exact strings in those files; the first draft of this sentence said "claude-haiku", which is in neither. This correction was found by tearing down our own artifact — and its first draft repeated the defect it corrects, quoting a denominator the scorer had not examined; that was caught by an adversarial review pass before publication.

## A4 · Per-slice and overall rates, with **cell-level** Wilson 95% CIs — and a disclosure about the unit

> [!warning] Read the interval column correctly — corrected 2026-09-07
> **The Wilson intervals below are computed over CELLS, not calendars.** An earlier version of this heading claimed the calendar was the unit, which the arithmetic does not support: `[1.4%, 3.1%]` is Wilson(26/1240), not a calendar-level bound. Cells within one calendar share a writer, a render style and a layout, so **treating them as independent makes these intervals anticonservative — too narrow.** They are reported because they are what was computed, and labelled for what they are.
>
> The genuinely calendar-level figure is the last column, and it is far less flattering: **`claude-haiku-4-5` had at least one STATUS error in 9 of 40 calendars — 22.5%, Wilson 95% [12.3%, 37.5%].**
>
> **Corrected 2026-09-12 (QA finding F07):** that figure counts status errors only. Counting **any** recorded status *or* note error, haiku is **12/40 = 30.0%, Wilson 95% [18.1%, 45.4%]** — the three extra documents are `sample_10_rotated`, `sample_13_clean` and `sample_38_rotated`, which fail on notes alone. `claude-sonnet-5` is **1/40 = 2.5%** on the same basis, from the duplicated note on `sample_01_clean`, despite 0/40 status-error documents. **30.0% and 2.5% are the numbers to quote when the question is *"how often does a document come back wrong?"***
>
> This was caught by an independent pre-publication review, in a correction document, committing the exact independence error [`docs/METHODS.md`](docs/METHODS.md) §5 forbids.

| model | slice | calendars | cells | status errors | rate | Wilson 95% CI | flips / gold-UNAVAIL | calendars with ≥1 status error |
|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5 (v1 run, as recorded in results/metrics.json) | clean | 10 | 310 | 0 | 0.0% | [0.0%, 1.2%] | 0 / 65 | 0/10 |
| claude-sonnet-5 (v1 run, as recorded in results/metrics.json) | rotated | 10 | 310 | 0 | 0.0% | [0.0%, 1.2%] | 0 / 75 | 0/10 |
| claude-sonnet-5 (v1 run, as recorded in results/metrics.json) | lowcontrast | 10 | 310 | 0 | 0.0% | [0.0%, 1.2%] | 0 / 87 | 0/10 |
| claude-sonnet-5 (v1 run, as recorded in results/metrics.json) | handwritten | 10 | 310 | 0 | 0.0% | [0.0%, 1.2%] | 0 / 89 | 0/10 |
| claude-sonnet-5 (v1 run, as recorded in results/metrics.json) | ALL | 40 | 1240 | 0 | 0.0% | [0.0%, 0.3%] | 0 / 316 | 0/40 |
| claude-haiku-4-5 (v1 run, as recorded in results_haiku/metrics.json) | clean | 10 | 310 | 0 | 0.0% | [0.0%, 1.2%] | 0 / 65 | 0/10 |
| claude-haiku-4-5 (v1 run, as recorded in results_haiku/metrics.json) | rotated | 10 | 310 | 8 | 2.6% | [1.3%, 5.0%] | 1 / 75 | 5/10 |
| claude-haiku-4-5 (v1 run, as recorded in results_haiku/metrics.json) | lowcontrast | 10 | 310 | 18 | 5.8% | [3.7%, 9.0%] | 5 / 87 | 4/10 |
| claude-haiku-4-5 (v1 run, as recorded in results_haiku/metrics.json) | handwritten | 10 | 310 | 0 | 0.0% | [0.0%, 1.2%] | 0 / 89 | 0/10 |
| claude-haiku-4-5 (v1 run, as recorded in results_haiku/metrics.json) | ALL | 40 | 1240 | 26 | 2.1% | [1.4%, 3.1%] | 6 / 316 | 9/40 |

**Caveat carried from the teardown:** content and render style are perfectly correlated by construction (`seed=7+i`, `style=i%4`), so slice differences confound style with content. Calendar-level CIs are the honest unit; the slice comparison is descriptive only.
