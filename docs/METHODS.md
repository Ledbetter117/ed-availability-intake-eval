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
| `handwritten` | a hand-filled form | Patrick Hand typeface, each glyph tile independently rotated **±7°** |

**Reproduce:** `python3 generate_dataset.py --n 40 --seed 7 --out ./data`

> ⚠️ Case *i* uses `seed = 7 + i` and `style = STYLES[i % 4]`. Content and render style therefore advance together and are **perfectly correlated by construction.** Slice comparisons confound the two and are descriptive only. See [`LIMITATIONS.md`](LIMITATIONS.md) §2.

---

## 3 · The run

Each image is sent to the model with a fixed prompt asking for the same JSON schema as gold. Raw responses are written verbatim to `results*/raw/` at run time. **That folder is gitignored and is not in this repository** — a reader cannot open the original model text here. What *is* shipped, and what every number is re-derivable from: `results*/per_case.csv` (row per case), `typed_errors.json` (every counted error, typed), and `calendar_level.csv` (per-calendar rates). To regenerate the raw text, re-run the harness (§6).

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
| **`CRITICAL_FLIP`** | gold was `UNAVAILABLE`, prediction was anything else — **the asymmetric-cost error**: it schedules a nurse who said she could not work |
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

**Denominator: 146 gold note items per model** — 124 day-notes + 22 global notes — **292 across both models.**

### The DISPLACED chance floor

`DISPLACED` is assigned by comparing against neighbouring days, and with five status codes and up to four neighbours a **wrong label lands on a neighbour by chance about half the time. The chance floor is 0.50.** Of Haiku's 26 status errors, 19 carry the `DISPLACED` label; roughly 13 would carry it by chance, so the excess over chance is about **6**. Reported as the weak signal it is, rather than as 19.

Computing a chance floor for a label before interpreting its count is the same correction this project applied to its own headline metric — applied here to its own classifier.

---

## 5 · Statistics

### Reading the two shipped ledgers — they use the same word for different things

`typed_errors.json` counts **notes**. `calendar_level.csv` counts **cells**. Both contain something called *displaced*, and **they are not the same quantity and will not agree.**

- `calendar_level.csv` → column `displaced` = cell-level status. `claude-haiku-4-5` = **19 of 1,240 cells**; `claude-sonnet-5` = **0**.
- `typed_errors.json` → `NOTE_DISPLACED` = a gold note whose text is correct but attached to the wrong day. `claude-haiku-4-5` = **9 of 146 notes (6.2%)**; `claude-sonnet-5` = **1 of 146 (0.7%)**. **This is the README's "Note displacement rate."**

Neither is derivable from the other. Summing the CSV column and comparing it to the README's percentage will produce a disagreement that is an artefact of the unit, not an error.

**The note categories are also not all mutually exclusive**, which matters if you check the arithmetic:

- `NOTE_OK + NOTE_OMISSION = 146` — these two, and only these two, partition the gold notes.
- **`NOTE_DISPLACED` is a subset of `NOTE_OK`**, not a sibling. A displaced note has correct text, so it is already counted in `NOTE_OK`. Summing all three double-counts and gives 147 (sonnet) or 155 (haiku) against a denominator of 146.

The same explanation ships inside `typed_errors.json` under `_schema`, so the file is readable without this page.

**The calendar should be the unit of analysis, not the cell** — cells within one calendar share a writer, a render style and a layout, so treating 1,240 cells as independent makes intervals **anticonservative (too narrow)**.

**What is actually shipped, stated plainly:** the per-slice and overall intervals in `analysis-v2.md` §A4 are **cell-level**. They are labelled as such there. The calendar-level figure — *the fraction of documents with at least one error* — is reported beside them, and for `claude-haiku-4-5` it is **9/40 = 22.5%, Wilson 95% [12.3%, 37.5%]**, which is the honest answer to *"how often does a document come back wrong?"*

Wilson score intervals are used throughout because they behave correctly at or near zero, where most of this data sits.

A Wilson interval is why *"0 errors"* is reported as **0.0% [0.0%, 0.3%]** rather than as certainty. Forty perfect calendars bound the error rate; they do not prove it is zero.

---

## 6 · Reproducing every number

```bash
pip install -r requirements.txt          # Pillow>=10; matplotlib for charts only
python3 generate_dataset.py --n 40 --seed 7 --out ./data
python3 run_eval.py --model <model> --data ./data --out ./results
python3 make_charts.py                   # optional
```

`results*/raw/` holds the unmodified model output for every case **locally; it is gitignored and not shipped.** Every figure in `analysis-v2.md` is derived from those files by a typed scorer that **reproduces `results/metrics.json` exactly** — and the scorer's per-case output is shipped as `calendar_level.csv`, so the arithmetic is checkable here even though the raw text is not — that exact-reproduction check is what licenses the re-score to disagree with v1's *interpretation* while agreeing with its *arithmetic*.

---

## 7 · What the harness will not do

- It does not average away a parse failure. A malformed response is a `format_validity` failure, reported, not silently dropped.
- It does not report a rate without its denominator.
- It does not report a label without its chance floor where one exists.
- It does not claim a metric measures something the code does not test — the defect that produced [`CORRECTIONS.md`](CORRECTIONS.md) §1.

See also: [`CORRECTIONS.md`](CORRECTIONS.md) · [`LIMITATIONS.md`](LIMITATIONS.md) · [`PROBE.md`](PROBE.md)
