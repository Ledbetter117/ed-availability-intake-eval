# Methods

How this evaluation is built, what it measures, and how to reproduce it.

---

## 1 · The task

A nurse fills in a monthly availability calendar. A manager must turn 40 of those into a staffing plan. The question this repository asks is narrow and answerable:

> **Given a photograph or scan of one filled-in availability calendar, how reliably does a vision-language model recover the correct status for every day?**

Not "can AI do scheduling." One step of one workflow, measured.

---

## 2 · The data

**40 synthetic calendars, July 2026, 31 days each = 1,240 day-cells per model.**

Synthetic by design: the gold standard is the generator's own state, so there is no annotation error and no ambiguity about what the page "really" says. That is the trade this repository makes, and its cost is stated in [`LIMITATIONS.md`](LIMITATIONS.md).

**Per-day fields:** a `status` drawn from a fixed vocabulary (`AVAILABLE`, `UNAVAILABLE`, `AM`, `PM`, …) and a free-text `note` (e.g. `"charge only"`). Gold is emitted as JSON alongside each image:

```json
{ "month": "2026-07",
  "days": { "2026-07-02": { "status": "PM", "note": "charge only" }, … } }
```

**Four render styles**, 10 calendars each, produced by `generate_dataset.py`:

| style | what it simulates | how (`generate_dataset.py`) |
|---|---|---|
| `clean` | a flatbed scan | greyscale 246 background, 20 foreground |
| `rotated` | photographed at an angle | whole image rotated **−4°**, background fill |
| `lowcontrast` | a faint scan or poor lighting | foreground 110 on background 224 — a contrast ratio of about **3.9 : 1**, below the WCAG AA threshold for body text |
| `handwritten` | a hand-filled form | Patrick Hand typeface; each written string (a status code or a note) drawn as one tile and rotated up to **±7°** |

**Reproduce:** `python3 generate_dataset.py --n 40 --seed 7 --out ./data`

> ⚠️ Case *i* uses `seed = 7 + i` and `style = STYLES[i % 4]`. Content and render style therefore advance together and are **perfectly correlated by construction.** Slice comparisons confound the two and are descriptive only. See [`LIMITATIONS.md`](LIMITATIONS.md) §2.

---

## 3 · The run

Each image is sent to the model with a fixed prompt asking for the same JSON schema as gold. Raw responses are written verbatim to `results*/raw/` at run time. **That folder is gitignored and is not in this repository** — a reader cannot open the original model text here. What *is* shipped, and what every number is re-derivable from: `results*/per_case.csv` (row per case), `typed_errors.json` (per-model totals for every error type), and `calendar_level.csv` (per-calendar rates). To regenerate the raw text, re-run the harness (§6).

**The prompt, verbatim** (`run_eval.py`, `TASK_PROMPT`) — the largest single source of variance in vision-model extraction, and therefore not something a methods document may omit:

```text
This image is a filled-in monthly staff availability calendar. Legend: ✓=available any shift, AM, PM, NOC=night shift, X=unavailable. Extract it to JSON with exactly this schema: {"month": "YYYY-MM", "days": {"YYYY-MM-DD": {"status": "AVAILABLE|AM|PM|NIGHT|UNAVAILABLE", "note": ""}}, "global_notes": []}. Every day of the month must appear. NOC maps to NIGHT; ✓ maps to AVAILABLE; X maps to UNAVAILABLE. Transcribe notes exactly as written; do not invent notes. Output ONLY the JSON.
```

A retry suffix is appended only when a response fails to parse; both published runs parsed on the first attempt (`retried = False` on all 80 rows of `per_case.csv`). **Prompt sensitivity is unmeasured** — one formulation cannot separate model capability from prompt fit, so the Haiku↔Sonnet gap may be partly a prompt artefact. See [`LIMITATIONS.md`](LIMITATIONS.md) §10.

**Models of record:** `claude-sonnet-5` (`results/metrics.json`) and `claude-haiku-4-5` (`results_haiku/metrics.json`) — the exact strings in those files.

**Measured cost:** ≈ $0.0125 per Sonnet call, ≈ $0.0042 per Haiku call. A full 40-case pass is ≈ $0.50 and ≈ $0.17 respectively.

---

## 4 · The metrics

Each predicted day is compared to gold and assigned exactly one label.

### Status labels

| label | meaning |
|---|---|
| `OK` | status matches gold |
| **`CRITICAL_FLIP`** | gold was `UNAVAILABLE` and the prediction was an available status (`AVAILABLE`, `AM`, `PM` or `NIGHT`) — **the asymmetric-cost error**: it schedules a nurse who said she could not work |
| `DISPLACED` | the predicted status belongs to an adjacent day |
| `MISREAD` | a wrong status that is not displacement |
| `MISSING` | no prediction for a day that exists in gold |

`CRITICAL_FLIP` is reported separately because the costs are not symmetric. Marking an available nurse unavailable produces a thinner roster; marking an unavailable nurse available produces a shift nobody covers. **Denominator: 316 gold-`UNAVAILABLE` days across the 40 calendars.**

> [!warning] The floor this metric has, and why it must never be read alone — added 2026-09-07
> **A model that answered `UNAVAILABLE` for all 1,240 cells would score a critical-error rate of 0.0%** — identical to the best result here. The metric is one-directional by construction, so it is only meaningful beside day-level accuracy, which such a model would fail catastrophically.
> The reverse error (gold available → predicted `UNAVAILABLE`) is **not** broken out as its own label in this version; it is absorbed into `MISREAD`/`DISPLACED`. That is a gap, it is named here rather than left to be discovered, and a `REVERSE_FLIP` label is the obvious v1.2 fix.

### Note labels

`OK` · `OMISSION` (gold note not produced) · **`DISPLACED`** (note is on the page, attached to the wrong day) · **`FABRICATED`** (note text appears nowhere on the page).

> The `DISPLACED` / `FABRICATED` split is the whole substance of Correction 1. v1 collapsed them into a single "hallucination rate" that never tested page presence. See [`CORRECTIONS.md`](CORRECTIONS.md).

**Denominators.** `OK` and `OMISSION` are counted over the **146 gold note items per model** (124 day-notes + 22 global notes; 292 across both models). `DISPLACED` and `FABRICATED` are counted over **predicted note instances**: 147 for Sonnet, 145 for Haiku (292 across both). See §5.

### The DISPLACED chance floor

`DISPLACED` is assigned by comparing against neighbouring days, and with five status codes and up to four neighbours a **wrong label lands on a neighbour by chance about half the time. The chance floor is 0.50.** Haiku made 26 status errors: 6 critical flips, 19 `DISPLACED`, 1 misread. The labels are mutually exclusive and a critical flip takes precedence, so only 20 errors could carry `DISPLACED`. About 10 of them would by chance (9.9 using each document's own floor); 19 do, an excess of about **9**. Those 19 come from 8 documents, and 6 of them come from one run of days read one cell off in `sample_11_lowcontrast` (July 3–11). Cells in one document are not independent, so this is reported as consistent with whole-row shifts rather than as a rate. *(Corrected 2026-09-25: the first version counted all 26 errors as eligible and reported an excess of about 6.)*

Computing a chance floor for a label before interpreting its count is the same correction this project applied to its own headline metric — applied here to its own classifier.

---

## 5 · Statistics

### Reading the two shipped ledgers — they use the same word for different things

`typed_errors.json` counts **notes**. `calendar_level.csv` counts **cells**. Both contain something called *displaced*, and **they are not the same quantity and will not agree.**

- `calendar_level.csv` → column `displaced` = cell-level status. `claude-haiku-4-5` = **19 of 1,240 cells**; `claude-sonnet-5` = **0**.
- `typed_errors.json` → `NOTE_DISPLACED` = a predicted note whose text matches a gold note but is attached to the wrong day. `claude-haiku-4-5` = **9 of 145 predicted note instances (6.2%)**; `claude-sonnet-5` = **1 of 147 (0.7%)**. **This is the README's "Note displacement rate."**

Neither is derivable from the other. Summing the CSV column and comparing it to the README's percentage will produce a disagreement that is an artefact of the unit, not an error.

**The note categories are indexed on two different things**, which matters if you check the arithmetic:

- **`NOTE_OK` and `NOTE_OMISSION` are outcomes of a GOLD note.** Was the gold item captured at its correct location, or not? These two, and only these two, partition the 146 gold items.
- **`NOTE_DISPLACED` is an outcome of a PREDICTED note** — a note the model emitted at a location that is not its gold location. It is counted over predictions, not over gold items, so it is not a member of the gold partition and **bears no fixed relationship to `NOTE_OK`.** Summing all three mixes the two index sets and gives 147 (sonnet) or 155 (haiku) against a gold denominator of 146.

Two shipped rows show why one blanket relationship cannot describe it:

| Row | gold | `NOTE_OK` | `NOTE_OMISSION` | `NOTE_DISPLACED` | What happened |
|---|---:|---:|---:|---:|---|
| `claude-sonnet-5` · `sample_01_clean` | 5 | 5 | 0 | 1 | Every gold note captured correctly, **plus an extra copy** asserted on a wrong day |
| `claude-haiku-4-5` · `sample_02_rotated` | 2 | 0 | 2 | 2 | Both gold notes **missing from their correct days**, both appearing one week-row down |

In the first, the displaced note is a duplicate of a correctly captured one. In the second, exact-location fidelity is **zero** and the displaced notes are the moved originals. Same column, two different events.

> **Correction, 2026-09-12.** An earlier version of this section and of `typed_errors.json`'s `_schema` block stated that *"`NOTE_DISPLACED` is a subset of `NOTE_OK`."* **That is false**, and the haiku row above refutes it directly: two displaced notes cannot be a subset of zero OK notes. The column totals always reconciled; the stated relationship between the columns did not. Found by external QA review (F06). This is the same failure the whole repository exists to correct — a name asserting a relationship the data does not have — caught one layer down from the original.

The same explanation ships inside `typed_errors.json` under `_schema`, so the file is readable without this page.

**The calendar should be the unit of analysis, not the cell** — cells within one calendar share a writer, a render style and a layout, so treating 1,240 cells as independent makes intervals **anticonservative (too narrow)**.

**What is actually shipped, stated plainly:** the per-slice and overall intervals in `analysis-v2.md` §A4 are **cell-level**. They are labelled as such there. Two calendar-level figures are reported beside them, and **they are not the same number**:

| Model | Documents with a **status** error | Documents with **any** recorded status *or* note error |
|---|---|---|
| `claude-sonnet-5` | **0 / 40 = 0.0%**, Wilson 95% upper **8.76%** | **1 / 40 = 2.5%** — the duplicated note on `sample_01_clean` |
| `claude-haiku-4-5` | **9 / 40 = 22.5%**, Wilson 95% [12.3%, 37.5%] | **12 / 40 = 30.0%**, Wilson 95% [18.1%, 45.4%] |

The three extra haiku documents are `sample_10_rotated`, `sample_13_clean` and `sample_38_rotated` — note-only failures, no status error.

**The honest answer to *"how often does a document come back wrong?"* is the right-hand column**: 30.0% for haiku, 2.5% for sonnet.

Note also that sonnet's zero-status-error result bounds at **8.76%** on 40 documents — not the 0.31% obtained by treating 1,240 cells as independent trials. Forty clean documents are much weaker evidence than 1,240 clean cells appear to be, and the document figure is the defensible one.

> **Correction, 2026-09-12.** An earlier version of this section described the 22.5% figure as *"the fraction of documents with at least one error."* **It counts status errors only.** Found by external QA review (F07). The status figure is retained because it is useful; it is no longer described as full-document correctness.

Wilson score intervals are used throughout because they behave correctly at or near zero, where most of this data sits.

A Wilson interval is why *"0 errors"* is reported with a bound rather than as certainty. **0 of 1,240 cells** gives [0.0%, 0.3%]; **0 of 40 documents** bounds the document error rate at 8.8%. Forty perfect calendars bound the error rate; they do not prove it is zero.

---

## 6 · Reproducing every number

```bash
pip install -r requirements.txt          # Pillow==10.4.0 (pinned); matplotlib for charts only
python3 generate_dataset.py --n 40 --seed 7 --out ./data
python3 run_eval.py --model <model> --data ./data --out ./results
python3 make_charts.py                   # optional
```

`results*/raw/` holds the unmodified model output for every case **locally; it is gitignored and not shipped.** Every figure in `analysis-v2.md` is derived from those files by a typed scorer that **reproduces `results/metrics.json` exactly** — and the scorer's per-case output is shipped as `calendar_level.csv`, so the arithmetic is checkable here even though the raw text is not — that exact-reproduction check is what licenses the re-score to disagree with v1's *interpretation* while agreeing with its *arithmetic*.

---

## 7 · What the harness will not do

- It does not drop a parse failure silently. A malformed response is a `format_validity` failure, and it is reported. **Gap closed in v1.2:** before v1.2 such a case, and likewise a valid response that simply omits a day, scored zero critical flips while its gold-`UNAVAILABLE` days stayed in the denominator, which pulled the critical-error rate down. Since v1.2 a response is validated before it is scored: an invalid response is reported with its reason and is not scored, and every rate uses scored cases only. A provider error is reported as such and is never counted as a model answer. Every v1 response parsed and returned every day (format validity 100% for both models), so no published figure is affected; re-scoring all 80 stored responses with the v1.2 harness reproduces every published per-case and aggregate value (`CORRECTIONS.md` §7).
- The documentation does not report a rate without its denominator. The harness's own `summary.md` prints its rates without denominators, apart from the critical-flip count; the counts behind every rate are in `per_case.csv`.
- It does not report a label without its chance floor where one exists.
- It does not claim a metric measures something the code does not test — the defect that produced [`CORRECTIONS.md`](CORRECTIONS.md) §1.

See also: [`CORRECTIONS.md`](CORRECTIONS.md) · [`LIMITATIONS.md`](LIMITATIONS.md) · [`PROBE.md`](PROBE.md)
