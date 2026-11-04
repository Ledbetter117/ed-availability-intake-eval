# Limitations — what this benchmark cannot tell you

Read this before citing any number from this repository.

---

## 1 · It is saturated. It cannot rank frontier models.

`claude-sonnet-5` makes **0 status errors in 1,240 cells** — every slice, 100%.

| model | cells | status errors | rate | Wilson 95% CI |
|---|---|---|---|---|
| `claude-sonnet-5` | 1,240 | **0** | 0.0% | [0.0%, 0.3%] |
| `claude-haiku-4-5` | 1,240 | 26 | 2.1% | [1.4%, 3.1%] |

A benchmark a frontier model completes perfectly has reached its ceiling. It **can** still separate a frontier model from a small one, which is a real and useful result for someone choosing a model for this task. It **cannot** tell you which of two frontier models is better, and it cannot detect improvement in either.

**Consequence for anyone reusing this:** do not treat a 100% score here as evidence of fitness for real intake. It is evidence that *rendered* calendars are easy.

---

## 2 · Slice comparisons confound rendering with content

Case *i* uses `seed = 7 + i` and `style = STYLES[i % 4]`. Content and render style advance together and are **perfectly correlated by construction**.

Every apparent difference between `clean`, `rotated`, `lowcontrast` and `handwritten` is a difference in *both* the calendar's content and its rendering, and no analysis can separate them after the fact. Haiku's `lowcontrast` slice shows 5.8% and its `handwritten` slice 0.0% — **that is not evidence that low contrast is harder than handwriting.** It is one confounded comparison across ten calendars each.

Slice figures are **descriptive only**. `analysis-v2.md` §A4 reports cell-level intervals (labelled as such, and anticonservative) beside the calendar-level figures, which are the honest unit. **Two calendar-level figures are reported and they differ:** documents with a **status** error (haiku 9/40 = 22.5%), and documents with **any** status *or* note error (haiku 12/40 = 30.0%; sonnet 1/40 = 2.5%). *Corrected 2026-09-12 — QA finding F07; this section previously named only the first and described it as "at least one error."*

*Fixing this requires crossing content with style — the same content rendered four ways — which the generator does not currently do.*

---

## 3 · The handwriting is not handwriting

The `handwritten` slice is a **typeface** (Patrick Hand), with each written string drawn as one tile and rotated up to ±7°. If the bundled font fails to load, `generate_dataset.py` falls back to the typed font without warning, so a regenerated handwritten slice could silently be typed. This is tracked with the deferred font findings. It has uniform stroke weight, perfect baseline spacing, no pressure variation, no self-corrections, no ink outside the cell, no crossings-out, no personal abbreviations, no cramming.

Real availability sheets have all of those, because they are filled in by a tired person against a deadline. **This slice tests a font, not a hand.** How much harder genuine handwriting is for these models is **not measured here and no source is cited for it** — it is the open question, not a known quantity.

That gap is precisely why [`PROBE.md`](PROBE.md) exists.

---

## 4 · Synthetic data buys a clean gold standard and pays for it

Because the generator's own state is the gold standard, there is no annotation error and no ambiguity about what the page says. That is a genuine strength: every disagreement is the model's.

The cost: the corpus contains no ambiguity a *human* would have to adjudicate — no illegible cell, no note that could attach to two days, no writer inventing a legend. Those are the cases that break real intake, and this corpus **cannot contain them by construction.**

---

## 5 · Single vendor, one point in time

Two models, one vendor (Anthropic), one run. No OpenAI, Google, or open-weight model. No re-run across model generations, so nothing here speaks to **durability** — whether a result survives the next model release.

**Do not read this as a cross-vendor comparison.** It is not one.

---

## 6 · No deployment, therefore no safety claim

Nothing here demonstrates a system in which a machine reads these documents unsupervised and acts on the result. Without that step, a status flip caught at schedule review is a **rework cost**, not a patient-safety event.

v1 framed the critical-flip metric as *"the patient-safety-analog failure mode."* That claimed more than the work established, and it is retired. The honest framing is **asymmetric cost**: expensive to discover late, cheap to prevent at authoring.

---

## 7 · One month, one layout, one schema

July 2026, 31 days, a single grid geometry and a single status vocabulary. Nothing here speaks to alternative layouts, partial shifts, split shifts, multi-month periods, or the free-form annotations real sheets accumulate.

---

## 8 · Why the controls exist

Every number here is gated by a check that must be able to fail — a scorer self-test that must detect a deliberately injected error, an integration test that refuses a run producing no verdict, and a pre-push sweep whose negative checks each carry a positive control. Author review is not treated as a control.

**[`CORRECTIONS.md`](CORRECTIONS.md) states how each correction was found.** Corrections 1–5 came from auditing the artifact against itself with a separate typed scorer. Correction 6 came from an adversarial review pass before publication. The follow-ups came from an external QA review after publication. Each review pass ran as a separate model session with no sight of earlier review output, and each finding was verified by hand against the shipped data. That method is disclosed because a repository about model reliability should say how its own reliability was checked.

---

## 9 · No baseline

No trivial baseline (majority class), no deterministic baseline (template matching against a grid whose geometry is known to the generator), and no human baseline is reported. **The accuracy figures therefore have no floor to be read against**, and whether a vision-language model outperforms classical extraction on this fixed-geometry task is unmeasured here.

## 10 · One prompt, one run, temperature unpinned

A single prompt formulation, one run per model, model-default temperature. **Prompt sensitivity is unmeasured**, so the Haiku↔Sonnet gap cannot be separated into model capability versus prompt fit; and single-run results at model defaults cannot support a claim about run-to-run stability. The headline zeros should be read with that in mind.

## In one sentence

**The saved synthetic runs contain zero and 26 status errors under their recorded model labels; the first run still has a duplicated note. One headline metric was named for a failure it did not measure. These records do not establish current model rankings or performance on a real handwritten sheet.**

See also: [`CORRECTIONS.md`](CORRECTIONS.md) · [`METHODS.md`](METHODS.md) · [`PROBE.md`](PROBE.md)
