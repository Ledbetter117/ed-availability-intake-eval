# The probe, Arm B — real documents · pre-registration

**Written 2026-09-06, before any image in this arm has been scored. Committed alongside [`PROBE.md`](PROBE.md), which is now Arm A.** If you are reading this after results exist, check the repository history: this file precedes `PROBE-RESULTS.md`.

---

## 1 · Why a second arm

[`PROBE.md`](PROBE.md) pre-registers a **within-writer** test: six documents, three transcribed from a specification and three authored under a timer, to isolate *authoring conditions* from *legibility*. It was designed on the assumption that no real documents existed.

Then the author located his own past availability documents — written over a year for actual scheduling deadlines, photographed the way they were actually submitted. **Arm A simulates authoring conditions. Arm B has them.** The two arms answer related questions and are run together:

| | Arm A (`PROBE.md`) | **Arm B (this file)** |
|---|---|---|
| Documents | 6 manufactured for the experiment | **11 real** — 7 grid-months + 4 free-form lists |
| Comparison | copyist vs authored, **within one writer** | authentic handwriting vs **the published synthetic benchmark** |
| Isolates | the authoring condition | whether the benchmark's ceiling survives contact with real documents |
| Cells (Stage 1) | 93 per arm — **cannot fire CLOSE** | 215 scored, **184 in the CLOSE denominator — also cannot fire CLOSE** (§6) |
| Weakness | simulated conditions | across-corpora, so confounded with everything else that differs |

**Neither arm alone answers the question. Together they triangulate it.**

---

## 2 · The document set — FROZEN at pre-registration. No additions after this date.

| ID | Document | Days | Encoding |
|---|---|---|---|
| `G1` | printed grid, handwritten | 31 | **L1** |
| `G2` | printed grid, handwritten | 31 | **L1** |
| `G3` | printed grid, handwritten — a second, richer document from the **same month as `G2`** (extra annotation vocabulary) | 31 | **L1** + free text |
| `G4` | printed grid, handwritten | 30 | **L2** + span marks |
| `G5` | printed grid, handwritten | 31 | **L2** + span marks |
| `G6` | printed grid, handwritten | 31 | **L3** |
| `G7` | printed grid, handwritten | 30 | **L3** |
| `F1` | free-form date list, notepaper | — | dates + shift |
| `F2` | free-form date list, lined notebook, **written at 90°** | — | dates + shift |
| `F3` | free-form date list, plain paper | — | dates only |
| `F4` | free-form date list, lined notebook | — | dates + shift |

**Three distinct encodings (`L1`, `L2`, `L3`) appear across the seven grid documents, spanning roughly twelve months.** The encodings themselves are the writer's private shorthand and are **not reproduced here** — nothing in this pre-registration's validity depends on publishing them, and doing so would narrow the setting. Document identifiers and calendar months are likewise abstracted; the mapping is held privately alongside the intent sheets.

**Grid arm: 215 day-cells across 7 documents covering 6 unique months, one writer.** The CLOSE denominator is the 184 unique-month cells — see §6. Lists are scored separately as a different task.

**Re-shoot pairs (a control needing no gold):** two of the grid documents each exist in **two separate photographs**. **Two pairs** — a third was listed in error and struck 2026-09-07 (§3).

> **Legend drift is pre-registered as a descriptive observation, not a claim.** One writer's encoding moved through three distinct schemes (`L1` → `L2` → `L3`) across roughly twelve months. It will be reported. It will not be interpreted as a finding about writers in general.

---

## 3 · Ground truth — and a correction made before scoring

| Source | Status |
|---|---|
| **G1 · Author intent sheets** | Primary. The writer states, per document, what every marked cell meant **and what an unmarked cell meant** (§4). Typed independently of any model output |
| **G3 · Re-shoot pairs** | **Two** pairs. Same document, two captures — any disagreement is capture-induced error. **Zero annotation required** |
| ~~**G4**~~ | **WITHDRAWN 2026-09-07, before scoring.** It overlapped no handwritten document, so it was gold for nothing here — and describing its source disclosed more than the cross-check was worth |
| ~~**G2 · A manager's confirmation email**~~ | **STRUCK before scoring.** The design draft of 2026-09-06 listed this as "external gold he did not author." Checking file dates: the email confirms **July 2023**. No handwritten July 2023 document exists. It is gold for nothing in this set. Recorded here because it would otherwise have been discovered *after* a scorer was built around it |

---

## 4 · The sparse-document problem — stated before scoring, because the synthetic benchmark hides it

Every cell in the synthetic benchmark carries an explicit status. **Real availability sheets are sparse.** The writer marks the days he is working or requesting; **a blank cell means something implicit** — and what it means may differ by document.

**Pre-registered handling:**
1. Each intent sheet carries a **`DEFAULT_STATUS`** row — the writer's statement of what an unmarked cell meant *on that document*. Gold is generated only if it is present.
2. A document whose default the writer cannot state **is excluded and the exclusion reported.** If exclusions drop the grid arm below 189 cells, CLOSE becomes unreachable and the results must say so.
3. Errors on **blank** cells are typed and reported separately from errors on **marked** cells. An extractor that reads every mark correctly and then invents a status for every blank has a different failure from one that misreads marks.

---

## 5 · Conditions — two prompts, both pre-registered

| Condition | The model is told | Tests |
|---|---|---|
| **LEGEND-BLIND** *(primary)* | only the output schema | whether the model can infer this writer's encoding from the page alone — the realistic case for a system receiving sheets from many writers |
| **LEGEND-GIVEN** *(secondary)* | the document's own legend, supplied verbatim from the intent sheet (not reproduced here — §2) | pure reading, with encoding removed as a variable |

**Primary decisions are made on LEGEND-BLIND.** LEGEND-GIVEN is diagnostic: the gap between the two is the cost of legend inference, reported as such.

Cost: 11 documents × 2 conditions × 2 models ≈ 44 calls ≈ **$0.75**.

---

## 6 · The decision rule for Arm B — fixed before any data

Arm B has **no copyist arm**, so Arm A's difference test does not apply. Its comparison is against the **published synthetic run** for the same model (`claude-sonnet-5`: 0 status errors / 1,240 cells).

| Branch | Fires when (LEGEND-BLIND, grid arm, best model) | Meaning |
|---|---|---|
| **B-CLOSE** | status-error Wilson 95% **upper** < 2% on the **184-cell** unique-month denominator | ⛔ **Unreachable at this corpus size — see reachability below.** Retained so the rule is complete, not because it can fire |
| **B-PROCEED** | Fisher exact *p* < 0.05 versus the model's own synthetic run **and** Wilson 95% **lower** > 1% (**≥ 6 errors**) | Real handwriting breaks extraction where the font did not. **Five errors in 215 cannot fire this** — the floor exists so a handful of mistakes is not a finding |
| **B-CONTINUE** | anything else | The data did not decide |

**Reachability, computed — including the duplicate-month decision, made now rather than after scoring.**

CLOSE needs **189** cells at zero errors. The seven grid documents total **215** — but `G2` and `G3` are the **same writer, same month**, so 62 of those cells describe 31 days. Counting them as independent is the cell-independence error `METHODS.md` §5 forbids.

| Denominator | Cells | CLOSE reachable? |
|---|---|---|
| All seven documents | 215 | yes |
| **Six unique months (`G3` excluded)** | **184** | **NO** |

> ### Pre-registered decision: the CLOSE denominator is the six unique months — **184 cells** — so **Arm B, like Arm A Stage 1, cannot fire CLOSE.** It decides PROCEED or CONTINUE.
> `G3` is still scored and reported in full; it is excluded only from the CLOSE denominator. Stated before any image is scored, because assembling a denominator that clears a threshold you have already published is precisely the failure `PROBE.md` §4 exists to prevent.

**PROCEED** remains reachable: its 1% lower-bound floor needs **≥ 6 errors** at n = 215 (5 gives a lower bound of **0.9973%**, which does *not* clear — corrected 2026-09-07 before any data).

**Claude-only lockout carries over from Arm A:** a run without an OpenAI-family model cannot fire B-CLOSE.

**Lists** (`B-real-*`) carry no decision branch. They are reported descriptively: dates recovered / dates on page, with fabricated dates counted separately.

---

## 7 · What would make Arm B worthless

- Scoring any image before this file is committed.
- Adding a document after this date because it "looks interesting."
- Letting the model's own output seed the intent sheet. **Gold is typed from the writer's memory and the page, never from a model's reading.**
- Reporting the legend-drift observation as a claim about writers in general. *n* = 1.
- Publishing an image. **Handwriting is biometric. Only derived numbers leave the machine.**

---

## 8 · Scope of whatever this returns — carried in every reporting sentence

*One writer; eleven documents he kept and could locate, spanning May 2023 → Nov 2025; not a random sample of his authoring; photographed under whatever conditions they were originally captured in; scored by the models named in the results file on the date stated there.* A negative here bounds this writer and this set.

---

**Status at time of writing: not yet run.** Intent sheets not yet filled. No image scored.

See also: [`PROBE.md`](PROBE.md) (Arm A) · [`LIMITATIONS.md`](LIMITATIONS.md) · [`METHODS.md`](METHODS.md)
