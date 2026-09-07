# The probe, Arm A — manufactured documents · pre-registration

> [!note] Added 2026-09-06 — this is now **Arm A** of a two-arm probe.
> After this file was written, the author located his own real availability documents from May 2023 → Nov 2025. Those form **Arm B**, pre-registered separately in [`PROBE-B.md`](PROBE-B.md) *before* any of them was scored. Nothing below is changed; Arm A still runs exactly as written, because it isolates the authoring condition within one writer — which Arm B, being across-corpora, cannot. The two arms triangulate. See `PROBE-B.md` §1 for the comparison.

**Published before the data exists. That is the entire point of this file.**

If you are reading this after results have been posted, check the repository history: this document was committed **before** `PROBE-RESULTS.md`. A pre-registration written after the data is worthless, and a reader should verify rather than take the claim on trust.

---

## 1 · Why

[`LIMITATIONS.md`](LIMITATIONS.md) §1 and §3 say two things that together make this repository unable to answer its own question:

1. The benchmark is **saturated** — a frontier model makes 0 status errors in 1,240 cells.
2. The `handwritten` slice is **a typeface, not a hand** — uniform strokes, perfect baselines, no corrections, no cramming, no ink outside the cell.

So the honest reading of a 100% score is not *"models read availability calendars perfectly."* It is *"models read this rendering perfectly, and this rendering may not be the hard case."*

**The question this probe asks:**

> Does a real human hand, writing under real authoring conditions, produce extraction errors that a rendered font does not?

---

## 2 · The distinction being tested — and its confound, stated up front

Two arms, six documents, one hand (the author's):

| arm | n | task |
|---|---|---|
| **COPYIST** | 3 | Transcribe a supplied specification onto a blank calendar. Accuracy-oriented, no time pressure. Gold is the specification |
| **AUTHORED** | 3 | Write your own real availability for a month, **under a timer**, as you would before a deadline. Gold is a separate intent sheet completed *after* writing |

The hypothesis is that the **authoring condition** — deciding while writing, under time pressure — produces page features (self-corrections, cramming, out-of-cell ink, invented abbreviations) that transcription does not, and that those features, not letterform legibility, drive extraction error.

> ### ⚠️ The confound, disclosed before the data
> **A hand rushed under a timer is also a less legible hand.** This design cannot separate "authoring behaviour" from "degraded legibility," because the manipulation produces both. `coding_behaviour.csv` measures the behavioural mediator per document (out-of-cell ink, self-corrections, crammed cells, off-legend abbreviations) so the mediator is *observed* rather than assumed — but observation is not separation. **Any result is correlational with respect to mechanism.** Claiming otherwise would be the same over-reach this repository already corrected once.

**Balance:** two grid geometries (A and B) appear in **both** arms, so geometry is not confounded with condition. Presentation order is randomised. One lighting condition, one camera.

---

## 3 · The decision rule — three branches, fixed before any data

| branch | fires when | consequence |
|---|---|---|
| **PROCEED** | authored error rate > copyist error rate **and** Fisher exact *p* < 0.05 **and** the intervals do not overlap | Authoring conditions matter. A scoped follow-on is warranted |
| **CLOSE** | copyist Wilson **upper** bound < 2% **and** authored Wilson **upper** < 5% | Frontier models read real handwritten staffing grids at ceiling. **Publish the negative and close the question** |
| **CONTINUE** | anything else | Stage 2: four more documents per arm, same protocol, re-run |

**PROCEED is a difference test, not a level test.** An earlier version of the scorer read `(authored_lower > 0.05) OR (difference significant)`, which fired PROCEED on **equal 9.7% error in both arms with Fisher p = 1.0** — a branch that could not fail, in the falsifier of the claim it was meant to test. It was caught by an independent review and replaced. Integration test **T11** now asserts that equal error in both arms refuses PROCEED.

---

## 4 · Reachability — computed before collection, not discovered after

**Rule: state the disqualifying value and prove it is reachable on the data you will actually have.**

CLOSE requires a copyist Wilson upper bound below 2%. At zero observed errors, reaching a 2% upper bound requires:

> **189 cells per arm.** Stage 1 collects **93** (3 documents × 31 days).

At 93 cells, a **perfect score** yields a Wilson upper bound of **3.97%** — above the 2% threshold.

> ### Stage 1 therefore CANNOT fire CLOSE. It decides PROCEED or CONTINUE only.
> Stage 2 (7 documents per arm ≈ 217 cells) makes CLOSE reachable. **This is stated here rather than discovered after a disappointing run** — the failure mode being that a study reports "we could not close the question" when the arithmetic never permitted it to.

---

## 5 · Model coverage — a Claude-only run cannot validly CLOSE

A CLOSE verdict from a single-family run would be a statement about one family presented as a statement about the frontier. **No source is cited here for a cross-family difference on handwriting, and none is claimed** — the lockout is a deliberate conservative hedge against an untested assumption, not an evidenced correction.

**The scorer disables the CLOSE branch unless an OpenAI-family model is included in the run, and says so in its output.** Integration test **T8** asserts this.

---

## 6 · What would make this probe worthless

Listed so a reader can check whether it happened:

- **Changing the decision rule after seeing the data.** The rule is in `kit/MANIFEST.json`, committed with this file.
- **Dropping a document.** All six are scored, including any that is badly photographed. A landscape-orientation photo raises a warning, not a silent exclusion.
- **Reporting a rate without its denominator, or a difference without its interval.**
- **Reading CONTINUE as PROCEED.** CONTINUE means the data did not decide.
- **Treating *n* = 1 writer as a sample.** It is one hand. The result bounds nothing about between-writer variation, and any write-up must say so in the sentence that reports it.

---

## 7 · Controls that must pass before the run counts

| control | asserts |
|---|---|
| `probe_score.py --selftest` | the scorer detects an injected error — a scorer that cannot fail is not a scorer |
| `probe_integration_test.py` | 9 checks: geometry balance · blank-intent refusal · end-to-end · PROCEED reachable · CONTINUE on unreachable · CLOSE at stage 2 · **T8** Claude-only CLOSE disabled · month-mismatch excluded · **T10** empty photo set → RUN INVALID, exit 1 · **T11** equal error refuses PROCEED |

**A run with no verdict exits non-zero and prints RUN INVALID.** It does not exit 0 with a blank result — six code paths previously did, which is how that requirement got written.

---

## 8 · Scope of whatever this returns

*One writer, one hand, six documents, two grid geometries, one lighting condition, one camera, one month of dates, scored by the models listed in the results file on the date listed there.* Every sentence reporting the outcome carries that scope inline. A negative here bounds this design and nothing wider.

---

**Status at time of writing: not yet run.** No probe data exists. When it does, it lands in `PROBE-RESULTS.md` beside this file, and this file is not edited.

See also: [`METHODS.md`](METHODS.md) · [`LIMITATIONS.md`](LIMITATIONS.md) · [`CORRECTIONS.md`](CORRECTIONS.md)
