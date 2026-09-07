# ED Availability Intake — an LLM Extraction Eval
**Building LLM Evals for Emergency Care.** A documented, synthetic-data evaluation of how reliably — and how *safely* — a vision LLM turns a filled-in staff availability calendar into structured scheduling data.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![Data](https://img.shields.io/badge/benchmark%20data-100%25%20synthetic-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey) ![Providers](https://img.shields.io/badge/runs%20on-Anthropic%20%7C%20OpenAI-orange)

**Author:** Galen Coulter-Ledbetter, RN, Paramedic · working ED nurse · Paramedic licensure held in Florida · military medical education and readiness leadership · daily multi-EHR and clinical-AI user.

| The input | The question |
|---|---|
| ![sample handwritten calendar](data/sample_04_handwritten.png) | A nurse prints a blank month, hand-marks availability, snaps a photo, and emails it. Before any scheduler can use that, something has to **read it correctly**. When an LLM does the reading and gets it wrong — **how wrong, and is the error dangerous?** |

---

## Results

**Scored 2026-08-13 · Anthropic API · single run per model · all 40 cases · zero format retries on either model.**

**Headline first — the dangerous flip.** `claude-sonnet-5`: **0 critical flips across 316 gold-UNAVAILABLE days (0.0%)**. `claude-haiku-4-5`: **6 flips across the same 316 days (1.9%)** — all six on degraded slices (5 lowcontrast, 1 rotated), peaking at **5.7%** on lowcontrast.

| Metric (overall, 40 cases) | claude-sonnet-5 | claude-haiku-4-5 |
|---|---|---|
| **Critical-error rate** (UNAVAILABLE→available) | **0.0%** (0 / 316) | **1.9%** (6 / 316) |
| Day-level accuracy | 100.0% (1240 / 1240) | 97.9% (1214 / 1240) |
| Note **displacement** rate (v1 called this "hallucination rate" — see [`analysis-v2.md`](analysis-v2.md) §A3) | 0.7% (1 / 146) | 6.2% (9 / 146) |
| Note **fabrication** rate (text absent from the page) | 0.0% (0 / 146; Wilson 95% upper 2.6%) | 0.0% (0 / 146; upper 2.6%) |
| Note fidelity (normalized match) | 100.0% (146 / 146) | 93.2% (136 / 146) |
| Format validity | 100.0% | 100.0% |

> ### 📄 Read [`docs/CORRECTIONS.md`](docs/CORRECTIONS.md) first.
> One of the metrics in the table above was named for a failure it did not measure. The correction is public and `v1.0.0` is preserved as a tag so the two can be read side by side.

Per-slice breakdowns: [`results/summary.md`](results/summary.md) (Sonnet) · [`results_haiku/summary.md`](results_haiku/summary.md) (Haiku). Row-level data in each folder's `per_case.csv`.

**The honest finding: Sonnet 5 saturates this benchmark.** 100% day-level accuracy on every slice, including handwritten, with zero robustness delta. Its only error in 40 cases: one duplicated note — the real "charge only" annotation from July 2 also asserted on the empty July 1 cell (`sample_01_clean`). Saturation is a result, not a disappointment: it locates this difficulty tier relative to **one frontier model on one date** and motivates the v2 tier on the roadmap.

**Haiku's failures are geometric, not glyphic.** Its handwritten slice is perfect; the errors cluster in spatial indexing. Worst case: a one-day grid shift on a faint calendar (`sample_11_lowcontrast`) misread 9 days and produced 3 phantom-available days in a single document. Under rotation, notes landed exactly one week-row down (`sample_02_rotated`: "no call" 18th→25th, "early out" 24th→31st). Every failure is traced with raw output in [`analysis.md`](analysis.md).

<p><img src="results_haiku/charts/day_accuracy_by_slice.png" width="520" alt="Haiku day accuracy by slice"> <img src="results_haiku/charts/error_breakdown.png" width="520" alt="Haiku error breakdown"></p>

---

## The headline metric: the dangerous flip
Not all misreads are equal. A model that reads `AM` as `PM` dirties the data. A model that reads **UNAVAILABLE as available** puts a body on the schedule that isn't there — a phantom nurse, an unstaffed ED shift discovered at shift change instead of at planning time. That `UNAVAILABLE → available` flip is this eval's **critical-error rate**, weighted and reported separately from ordinary accuracy, because it is the **asymmetric-cost** failure mode: expensive to discover late, cheap to prevent at authoring. (v1 called this "the patient-safety-analog failure mode"; no deployment in which a machine reads these unsupervised has been demonstrated, so that framing claimed more than the work established. See [`docs/CORRECTIONS.md`](docs/CORRECTIONS.md) §5.)

## The task under test
**Input:** an image of a filled-in monthly availability calendar.
**Output:** structured JSON.

```json
{
  "month": "2026-07",
  "days": {
    "2026-07-01": { "status": "PM", "note": "" },
    "2026-07-02": { "status": "UNAVAILABLE", "note": "no call" }
  },
  "global_notes": ["No weekends"]
}
```
`status ∈ {AVAILABLE, AM, PM, NIGHT, UNAVAILABLE}` (AVAILABLE = any shift). Calendar legend: `✓=any  AM  PM  NOC=night  X=off`.

*Schema note:* the rendered calendars carry a synthetic employee ID as visual decoration, but it is not part of the labeled ground truth, so it is deliberately **not** in the required output schema. Stated here because silently dropping it would be the kind of drift an eval exists to catch.

## Synthetic data with free ground truth (the design move)
`generate_dataset.py` *generates* each availability pattern first, then renders it to an image — so every calendar ships with its **exact** ground-truth JSON. No manual labeling and no real records — a staff availability calendar carries employment data, not patient data, and every calendar here is generated, and the whole 40-case dataset is **regenerable from a single seed** (`--seed 7`). *Byte-identical* output additionally requires the same Pillow/FreeType build — glyph rasterisation for the handwritten slice varies across versions and platforms — so `requirements.txt` pins Pillow and byte-identity is claimed only for a matching environment. Difficulty is varied in slices so failures can be attributed:

| Slice | What it simulates |
|---|---|
| `clean` | typed codes, straight scan |
| `rotated` | photographed at an angle |
| `lowcontrast` | faint scan / poor lighting |
| `handwritten` | pen-filled printed calendar — handwriting font, per-mark jitter, stroke-drawn check marks |

## Metrics & rubric
Per case, then aggregated per slice and overall:
1. **Day-level accuracy** — % of days with correct `status`.
2. **Critical-error rate** *(headline)* — `UNAVAILABLE → available-of-any-kind` flips, per gold-UNAVAILABLE day.
3. **Note displacement rate** — notes attached to the wrong day. *(v1 named this "hallucination rate" and defined it as text not on the page; the typed re-score in [`analysis-v2.md`](analysis-v2.md) found **every** counted note was on the page. Fabrication is reported separately: **0 / 146** gold note items per model (Wilson 95% upper **2.6%** each; 0 / 292 pooled across both models, upper 1.30%).)*
4. **Note fidelity** — gold notes captured (normalized match; optional `--judge` adds an LLM-as-judge pass, reported separately, bias acknowledged).
5. **Format validity** — parsed, schema-conforming, all days present, statuses in enum. A case that fails twice scores as format-invalid — it is not dropped.
6. **Robustness delta** — accuracy on `clean` minus each degraded slice.

## How to run
Python 3.10+ with **Pillow** (`pip install -r requirements.txt`); matplotlib only for charts. Extraction never sees gold labels; scoring never calls the API. The key is read from an environment variable only — never a file, never an argument, never logged.

```bash
python3 generate_dataset.py --n 40 --seed 7     # rebuild the dataset (or use data/ as shipped)

export ANTHROPIC_API_KEY=...                     # or OPENAI_API_KEY for gpt-* models
python3 run_eval.py --model claude-sonnet-5 --limit 4   # cheap sanity run first
python3 run_eval.py --model claude-sonnet-5             # full 40-case run
python3 run_eval.py --model claude-haiku-4-5 --out ./results_haiku   # second-model run, as published
python3 run_eval.py --model gpt-4o                       # provider inferred from model string

python3 make_charts.py                           # renders results/charts/*.png
python3 make_charts.py --results ./results_haiku # charts for the second-model run
```
Outputs: `results/metrics.json` (aggregates), `results/per_case.csv` (row-level), `results/summary.md` (README-ready table), `results/raw/` (raw model output per case, gitignored).

*Cross-provider note:* the Anthropic path is exercised in the published run. **The OpenAI path is implemented to spec and untested** — it has never been executed. `docs/PROBE.md` §5 makes a branch of the probe depend on it, so it will be exercised on a small case set before that branch is used.

## Failure modes watched for
AM/PM/NOC confusion · date–cell misalignment (off-by-one weeks) · ambiguous-mark misreads · skew/rotation drops · faint-mark omissions · handwriting misreads · note truncation · invented notes. Each observed failure gets a concrete case in [`analysis.md`](analysis.md) with the **operational consequence stated in staffing terms**.

## Proposed guardrails (the clinician's recommendations)
Per-day confidence scores routing low-confidence cells to human confirm · **employee e-confirmation** of the parsed result before it enters the scheduler (closes the loop on the dangerous flip) · schema + sanity validators (reject a parse that marks a whole month AVAILABLE) · re-prompt or second-model vote on low-confidence cells.

## Why an eval, not just a demo
A working tool proves *"I can build."* An eval proves *"I can validate a model and find where it's unsafe"* — the actual day job of clinical-AI reviewer / SME / validation roles. The transferable part is the measurement discipline — typed error classes, denominators, chance floors, pre-registered decision rules, and a published account of where the instrument was wrong. **The extraction task itself is far easier than clinical document intake:** a fixed 31-cell grid with a five-symbol closed vocabulary and machine-generated ground truth, against unbounded layouts, open vocabulary, real PHI and human-adjudicated labels.

## Product vision (what this is the front door of)
The full tool is an ED scheduling system: ingests availability in whatever form it arrives, maps the scheduling period, projects daily assignments, adapts to callouts / census swings / travel-contract turnover / orientation double-assignments, and surfaces holes before they happen. That's a constraint-optimization + integration build. **This eval is Phase 1: prove the data going in is read correctly and safely** — an optimizer fed bad intake produces confidently wrong schedules.

## Honest limitations
> **Fuller treatment: [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)** — including the two that matter most: this benchmark is **saturated** (a frontier model scores 100%, so it cannot rank frontier models), and slice comparisons **confound rendering with content** by construction (`seed = 7 + i`, `style = i % 4`).

Synthetic calendars — even the handwritten slice — are cleaner and more uniform than real-world artifacts; reported accuracy is an **upper bound**. Single-model, single-run results unless the variance check is reported. LLM-as-judge (optional) shares a family with the model under test. Single-author rubric. Stated, not hidden — naming the limits is part of the competency.

## Repo layout
```
ed-availability-intake-eval/
├── README.md
├── LICENSE                # MIT (bundled font: SIL OFL 1.1, see assets/fonts/OFL.txt)
├── generate_dataset.py    # synthetic calendars + ground-truth JSON (seeded, reproducible)
├── run_eval.py            # extraction harness + scoring (Anthropic | OpenAI)
├── make_charts.py         # results charts (matplotlib)
├── assets/fonts/          # Patrick Hand (OFL 1.1) for the handwritten slice
├── data/                  # 40 generated images + .gold.json (regenerable)
├── results/               # claude-sonnet-5 run: metrics.json, per_case.csv, summary.md, charts/
├── results_haiku/         # claude-haiku-4-5 run: same layout
├── V2_TIER_DESIGN.md      # next difficulty tier (v1 frozen; Sonnet saturated it)
├── analysis.md            # failure-mode writeup traced to per_case.csv rows
├── analysis-v2.md         # metric audit: typed error split, corrected Finding 2, calendar-level CIs
├── typed_errors.json      # every counted error, typed
├── calendar_level.csv     # per-calendar rates (the honest unit of analysis)
├── requirements.txt
└── docs/                  # METHODS · CORRECTIONS · LIMITATIONS · PROBE (pre-registration)
```

## Roadmap
- [x] Spec + synthetic generator
- [x] 40-case dataset across 4 difficulty slices (incl. handwritten)
- [x] Extraction + scoring harness, dual-provider
- [x] Scored run + charts (claude-sonnet-5 + claude-haiku-4-5, 2026-08-13)
- [x] Failure-mode analysis + guardrails (`analysis.md`)
- [x] **Metric audit and correction** — `analysis-v2.md` + `docs/CORRECTIONS.md` (2026-09)
- [x] **Methods, limitations and a pre-registered probe** — `docs/` (2026-09)
- [ ] Run-to-run variance check
- [ ] v2 difficulty tier — Sonnet saturated v1 (design: `V2_TIER_DESIGN.md`)
- [ ] Automated harness search over this eval — can an optimized harness close the Haiku→Sonnet gap? (candidate method: Meta-Harness; no affiliation with its authors)

**Independence:** developed on personal time and personal equipment. No employer data, systems, or resources were used, and no employer is identified. Views are the author's own.

---
*The benchmark dataset is 100% synthetic — no PHI, no employer data, no real schedules — **by construction.** Arm B of the probe ([`docs/PROBE-B.md`](docs/PROBE-B.md)) scores the author's **own** real availability documents; those images never enter this repository and only derived numbers do — **by policy, and stated as such.***
