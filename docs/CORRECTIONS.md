# Corrections

This file records where this project was wrong, how that was found, and what changed.

`v1.0.0` is preserved as a tag, unmodified. Nothing below rewrites it — you can read the original and the correction side by side, which is the point.

---

## Correction 1 · The headline metric was named for a failure it did not measure

**What v1.0.0 said.** `analysis.md`, Finding 2, and the README's summary table reported a **hallucination rate** — defined in the README as *"notes asserted that aren't on the page"* — and reported **22.6%** on the rotated slice.

**What was actually true.** The metric (`run_eval.py:175`) counts any predicted note that differs from *that day's* gold note. It never tested whether the note appeared anywhere on the page.

A typed re-score of every counted error found that **every single one was text already present on the page**, attached to the wrong day. Not invented — **displaced**.

| | Sonnet | Haiku |
|---|---|---|
| Notes counted as "hallucinations" by v1 | 1 | 9 |
| Of those, actually absent from the page | **0** | **0** |
| Measured fabrication rate | **0.0%** | **0.0%** |

**Fabrication across both models: 0 of 292 gold note items examined (146 per model — 124 day-notes + 22 global notes). Wilson 95% upper bound: 1.30%.**

**Why this matters more than a naming quibble.** Displacement and fabrication are different failures with different consequences. A displaced note is wrong data that a reviewer can trace to a real source on the page. A fabricated note is content with no origin — the failure people mean when they say a model "hallucinated." Reporting one as the other **overstates the danger of the model and understates the danger of the layout**, and it points remediation at the wrong place: you would go looking for a grounding problem when what you have is a spatial-binding problem.

**What changed.** The metric name is retired. `analysis-v2.md` replaces it with a typed split — `DISPLACED / MISREAD / MISSING / CRITICAL_FLIP` for statuses, and `OK / OMISSION / DISPLACED / FABRICATED` for notes — and reports fabrication separately, with its denominator and confidence interval.

---

## Correction 2 · The benchmark is saturated, and v1 did not say so

**What v1.0.0 implied.** By reporting per-slice accuracy across four rendering conditions, v1 presented itself as a benchmark that discriminates between models and conditions.

**What was actually true.** The stronger model makes **zero status errors in 1,240 cells** — every slice, 100%.

| model | cells | status errors | rate | Wilson 95% CI |
|---|---|---|---|---|
| `claude-sonnet-5` | 1,240 | **0** | 0.0% | [0.0%, 0.3%] |
| `claude-haiku-4-5` | 1,240 | 26 | 2.1% | [1.4%, 3.1%] |

A benchmark on which a frontier model scores perfectly **cannot rank frontier models**. It has a ceiling, and the ceiling has been reached. That is a limitation of the instrument, and it belongs in the README rather than being discoverable only by someone who reads the numbers carefully.

**What changed.** `docs/LIMITATIONS.md` states it plainly, and the README now carries a *"What it cannot tell you"* block above the fold.

---

## Correction 3 · Slice comparisons confound content with rendering

**What was actually true.** The generator sets `seed = 7 + i` and `style = i % 4` for case *i*. Content and render style therefore advance together and are **perfectly correlated by construction**. Any difference between the `clean`, `rotated`, `lowcontrast` and `handwritten` slices is a difference in *both* the calendar's content and its rendering, and the two cannot be separated after the fact.

**What changed.** Slice-level differences are now labelled **descriptive only**. The honest unit of analysis is the calendar. `analysis-v2.md` §A4 reports the calendar-level figure — documents with at least one error — beside cell-level intervals that are explicitly labelled anticonservative. **An earlier draft of that section claimed the intervals were calendar-level when the arithmetic was cell-level; that mislabelling was itself caught before publication and is corrected in place.**

---

## Correction 4 · The README's first command did not run

`README.md` described the project as *"Stdlib-only Python (matplotlib needed only for charts)."* `generate_dataset.py:20` imports PIL. A reader following the README's first instruction got `ModuleNotFoundError`.

**What changed.** A `requirements.txt` (`Pillow>=10`, `matplotlib`), and the README now states the real dependency.

---

## Correction 5 · A safety framing that the evidence did not support

v1 justified its focus on availability flips as *"the patient-safety-analog failure mode."*

No deployment in which a machine reads these documents unsupervised has been demonstrated, here or anywhere cited. Without that step, a flip caught at schedule review is a **rework cost**, not a safety event. The framing claimed more than the work established.

**What changed.** The framing is now *"the asymmetric-cost failure mode: expensive to discover late, cheap to prevent at authoring."* That is what the data supports.

---

## How these were found

**Corrections 1–5** were found by auditing the artifact against itself: every metric re-derived from the raw outputs by a separate typed scorer that reproduces `results/metrics.json` exactly, then re-read line by line against what the README and `analysis.md` claimed.

**Correction 6 was found by an adversarial review pass before publication, not by the author.** None of these came from a user or a bug report — but it would be false to call the whole set self-audit, and the distinction matters for exactly the reason this file exists.

---

## Correction 6 · The correction itself was wrong the first time

This is the entry that matters most, so it is not buried.

The first draft of Correction 1 quoted a denominator of **292 note items** while the scorer that produced the number examined only **248** — it silently skipped 44 global notes. The rate was right; the denominator described work the instrument had not done.

It was caught by an adversarial review pass *before* publication, not by the author. The response was to **fix the instrument, not the sentence**: the scorer now examines global notes exactly as v1's scorer did, so 292 is the number it actually examines. The corrected figure is unchanged at zero fabrications.

**Why it is in the public record.** A corrections file that lists only other people's category of error is marketing. This one is here because the correction *of* a correction is the case that tests whether the process works — and the process caught it, before publication, rather than the author noticing later.

---

## Provenance

Every figure above is reproducible from `results/metrics.json` and `results_haiku/metrics.json` via the typed scorer. Model strings of record are **`claude-sonnet-5`** and **`claude-haiku-4-5`** — the exact strings in those files. (An earlier draft wrote "claude-haiku", which appears in neither. Corrected.)

See also: [`METHODS.md`](METHODS.md) · [`LIMITATIONS.md`](LIMITATIONS.md) · [`PROBE.md`](PROBE.md) · `../analysis-v2.md`
