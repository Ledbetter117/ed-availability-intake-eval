# Probe amendment 01 — the unit of inference

**Drafted 2026-09-12 and revised 2026-09-25. The earlier draft heading incorrectly described 2026-09-25 as its first publication date. Publication is established by repository history, not that heading.** The preserved project record reports that these revisions preceded probe scoring. The 2026-09-25 revision does three things: it corrects the Arm B document count (§3); it states how the original secondary conditions carry over (§4); and it records a ruling on image transmission (§4b). No photograph has been taken for Arm A, no intent sheet has been filled for Arm B, and no scorer has been run against any probe document. Check the repository history: this file precedes `PROBE-RESULTS.md`.

**`PROBE.md` and `PROBE-B.md` are not edited.** Their entire value is that they were committed before data existed, so they stay exactly as published and this document records what changed and why. A pre-registration that is quietly rewritten is not a pre-registration.

---

## 1 · What was wrong

Both pre-registrations decide using **Fisher exact tests and Wilson intervals computed over day-cells**. Both designs vary their condition at the level of the **document**.

- **Arm A** assigns COPYIST or AUTHORED to a whole sheet. Stage 1 has **three documents per arm**, counted as 93 cells per arm.
- **Arm B** compares 7 real grid documents against the published synthetic run, counted as 215 cells.

Cells inside one calendar share a writer, a sheet, a layout, a lighting condition and a single capture. They are not independent trials, and the errors this probe exists to detect are exactly the kind that **cascade**: a one-day grid shift misreads nine cells at once. That is not nine pieces of evidence. It is one.

**This repository already said so, in the same commit.** `METHODS.md` §5:

> *"**The calendar should be the unit of analysis, not the cell** — cells within one calendar share a writer, a render style and a layout, so treating 1,240 cells as independent makes intervals **anticonservative (too narrow)**."*

The probe's decision rules contradict the methods document they ship beside. That is the defect.

### The counterexample that makes it concrete

Suppose COPYIST records 0 errors in 93 cells and AUTHORED records 10, **all ten inside a single document**.

| Unit | Test | Result |
|---|---|---|
| Cells | Fisher on 0/93 vs 10/93 | *p* = **0.0015**; Wilson [0%, 3.97%] vs [5.95%, 18.67%], non-overlapping → **fires PROCEED** |
| Documents | Fisher on 0/3 vs 1/3 | *p* = **1.0** → decides nothing |

One badly photographed sheet would have produced a "significant authoring effect."

### A second, narrower defect

**Arm B handles its duplicate month inconsistently.** `PROBE-B.md` §6 excludes `G3` — the second document from `G2`'s month — from the CLOSE denominator (184 cells) on cell-independence grounds, then admits all 215 cells including `G3` into PROCEED. The same objection applies to both branches or to neither.

---

## 2 · What is amended

**The unit of inference for every decision branch in both arms is the DOCUMENT.** A document counts as an error document if it contains at least one status error.

Cell-level rates remain in the results as **descriptive** statistics, labelled as such, because they describe how bad a bad document is. They no longer decide anything.

**Duplicate-month handling is now uniform:** `G3` is excluded from every Arm B decision denominator, not only CLOSE. It is still scored and reported in full.

---

## 3 · Reachability under the amended unit — computed here, before collection

`PROBE.md` §4 requires the disqualifying value be proven reachable on the data that will actually exist. Re-run at the document level, the answers changed, and two of them changed the design's conclusions.

### Arm A · Stage 1 — 3 documents per arm

The most extreme table obtainable is 0/3 copyist error-documents against 3/3 authored:

> P(table) = C(3,0)·C(3,3) / C(6,3) = 1/20 = 0.05 → **two-sided *p* = 0.10**

> ### ⛔ Arm A Stage 1 cannot fire PROCEED. Not with a perfect result.
> `PROBE.md` §4 already established Stage 1 cannot fire CLOSE. **Under the corrected unit it cannot fire PROCEED either, so Stage 1 returns CONTINUE by construction.**
>
> **Stage 1 is a pilot, not a decision point.** What it buys is real and worth the two hours — the mediator measurements in `coding_behaviour.csv`, a point estimate to size Stage 2, descriptive error rates, and a first contact with the instrument. It does not buy a verdict, and no write-up may report one.

### Arm A · Stage 2 — 7 documents per arm

| Authored error-documents (copyist at 0/7) | Two-sided *p* | Fires PROCEED |
|---|---|---|
| 7 / 7 | 0.00058 | yes |
| 6 / 7 | 0.0047 | yes |
| **5 / 7** | **0.021** | **yes — the minimum** |
| 4 / 7 | 0.070 | no |

**Minimum detectable effect: at least 5 of 7 authored documents must carry an error while 0 of 7 copyist documents do.** Anything weaker returns CONTINUE.

### Arm B — 6 grid documents (`G3` excluded) against the 40-document synthetic run

These figures assume a synthetic run with 0 of 40 error-documents, which is what `claude-sonnet-5` recorded. A model whose own synthetic run already carries errors needs more. Against `claude-haiku-4-5`'s 9 of 40, the minimum is 4 of 6 (*p* = 0.045).

| Real grid documents with ≥1 status error | Two-sided *p* | Fires B-PROCEED |
|---|---|---|
| 1 / 6 | 0.130 | no |
| **2 / 6** | **0.014** | **yes — the minimum** |

**Minimum detectable effect, against a 0-of-40 synthetic run: at least 2 of the 6 grid documents must carry at least one status error.**

*Corrected 2026-09-25, before publication. The first version of this section counted 7 grid documents, which included `G3` after §2 had excluded it from every decision. With 7 documents the figures were 0.149 and 0.019. The minimum, 2 documents, is unchanged.*

### CLOSE, in both arms

A Wilson 95% upper bound below 2% at zero observed errors requires **n = 189**. That arithmetic was correct in the original documents. **The unit was wrong: it is 189 documents, not 189 cells.**

- Arm A Stage 1, 0/3 documents → Wilson upper **56.2%**
- Arm B, 0/6 documents → Wilson upper **39.0%**

> ### ⛔ CLOSE is unreachable in this design at any stage, and cannot be made reachable by one writer.
> The original documents said Stage 1 could not close. The corrected unit says **no stage of either arm can close.** The probe can return PROCEED, CONTINUE, or a descriptive report. **It cannot publish the saturation negative.**
>
> This is a reduction in what the probe was advertised to deliver, it is stated before any data exists rather than discovered after a disappointing run, and it is exactly the failure `PROBE.md` §4 was written to prevent — caught this time against the probe's own rules.

---

## 4 · The amended decision rules

### Arm A

| Branch | Fires when |
|---|---|
| **PROCEED** | Fisher exact two-sided *p* < 0.05 on **error-documents per arm**, in the direction authored > copyist, **and** the two arms' Wilson 95% intervals do not overlap (carried over from `PROBE.md` §3, now at the document level) |
| ~~CLOSE~~ | **RETIRED.** Unreachable at any feasible n for one writer (§3) |
| **CONTINUE** | anything else — including every possible Stage 1 outcome |

### Arm B

| Branch | Fires when |
|---|---|
| **B-PROCEED** | Fisher exact two-sided *p* < 0.05 on **error-documents**, using LEGEND-BLIND output from the best model: 6 real grid documents (`G3` excluded) against that model's own synthetic run, **and** a Wilson 95% lower bound above 1% on the real documents' error-document rate (carried over from `PROBE-B.md` §6, now at the document level) |
| ~~B-CLOSE~~ | **RETIRED**, same reason |
| **B-CONTINUE** | anything else |

**What the carried-over conditions do at the document level.** Neither changes a minimum in §3. In Arm A, at 5 of 7 against 0 of 7 the intervals are [35.9%, 91.8%] and [0.0%, 35.4%], and they do not overlap. The condition can still bind: 6 of 7 against 1 of 7 gives *p* = 0.029, but [48.7%, 97.4%] overlaps [2.6%, 51.3%], so that result returns CONTINUE. In Arm B, at 2 of 6 the Wilson lower bound is 9.7%, above the 1% floor. *(The first version of this section listed only the Fisher condition and dropped both of these without saying so. Corrected 2026-09-25, before publication.)*

**Carried over unchanged:** in Arm B, decisions on LEGEND-BLIND output, grid arm, best model; scoring every document including badly photographed ones; no rate without its denominator and no difference without its interval; CONTINUE means the data did not decide; *n* = 1 writer bounds everything.

**Sidedness.** Every Fisher test in this document is two-sided. The original documents did not state a sidedness. Two-sided is the conservative reading — a one-sided test would lower the Stage 2 minimum to 4 of 7 — and it is fixed here, before any data.

**Controls.** `PROBE.md` §7 lists two controls that test CLOSE: *CLOSE at stage 2* and *T8, Claude-only CLOSE disabled*. They retire with the branch. The rewritten scorer's self-tests will instead assert that CLOSE can never fire, and will test the document-level minimums in §3.

**Where the rule lives.** `PROBE.md` §6 says its decision rule is in `kit/MANIFEST.json`, committed with that file. That file was not committed. It ships with the probe code, and it will carry the amended rule.

**Retained, with a changed role: the Claude-only lockout.** The OpenAI-family requirement existed to make CLOSE valid. CLOSE is retired, so the lockout no longer gates a branch — **it is retained anyway**, as a single-family run remains a statement about one family, and the results must say which families ran.

---

---

## 4b · A second correction: what "never leaves the machine" actually meant

`PROBE-B.md` says, of the author's real availability documents:

> *"**Handwriting is biometric. Only derived numbers leave the machine.**"*

**As written, that is false, and it would have become false the moment the probe ran.** Arm B scores real photographs by sending them to a cloud vision model. The adapter base64-encodes the entire image into the request body. The image leaves the machine — to a third-party processor — every time a document is scored.

What the sentence was reaching for is a different and narrower guarantee, and that one does hold:

| Boundary | Status |
|---|---|
| **Not committed to git, not published** | **TRUE** and enforced — `.gitignore`, and the images live outside the repository tree |
| **Not in the public artifact** | **TRUE** — only derived numbers reach `PROBE-RESULTS.md` |
| **Never transmitted anywhere** | **FALSE** — scoring transmits the image to the model provider |

**Amended statement, replacing the sentence above:**

> Handwriting is biometric. **These images are transmitted to the model provider that scores them, and to nobody else.** They are never committed to this repository, never published, and never included in any released artifact; only derived numbers are. A reader who objects to the images reaching a commercial API should read Arm B's results as conditioned on that, because it is unavoidable for any cloud-model evaluation of real documents.

**Consequence, and it is the founder's to rule on:** if images reaching a third-party processor is not acceptable, **Arm B cannot run as designed** — not with these providers. The alternatives are a local vision model, or dropping Arm B. That decision belongs to whoever owns the documents, and it must be made before the first scored image, not after.

> **Ruling, 2026-09-25 — before any image was scored.** The documents' owner chose a local vision model, the first alternative named above, for every photographed document in both arms, subject to a feasibility check on the public synthetic calendars. What that changes for the design will be published as `PROBE-AMENDMENT-02.md` before any probe image is scored: which model is used and how it is run, the synthetic baseline it is compared against, and what the cross-family requirement means for a local model.

Identified by external QA review (F20). No private image has been transmitted; no probe document has been scored.

---

## 5 · What this does not change

- No image has been scored. No result exists. Nothing is being re-decided after seeing data.
- The v1 benchmark's published numbers are untouched — this concerns the probe only.
- `PROBE.md` and `PROBE-B.md` remain exactly as committed at `ac084ca`.
- The corpus is still frozen. No document is added or dropped.
- Arm A's disclosed confound stands: a hand rushed under a timer is also a less legible hand, and this design cannot separate them.

## 6 · Provenance

The unit error was identified by an external QA review on 2026-09-12 (finding F08), which supplied the clustered counterexample above. The duplicate-month defect (§1) was found twice, independently. An internal review of `probe_b.py` on 2026-09-08 found the code computing B-CLOSE over 215 cells where `PROBE-B.md` §6 had published 184, and the same external review found it again. Neither review had seen the other. A third independent review, on 2026-09-25, found that the first version of this document miscounted Arm B's decision documents and silently dropped the original secondary conditions. Both are corrected above, before publication.

**The code has not yet been amended to match this document.** Until it is, and until its self-tests are run, no probe image may be scored.

See also: [`PROBE.md`](PROBE.md) · [`PROBE-B.md`](PROBE-B.md) · [`METHODS.md`](METHODS.md) §5 · [`CORRECTIONS.md`](CORRECTIONS.md)
