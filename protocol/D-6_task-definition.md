# D-6 · Transcribe or reconcile? Task definition for the comparison (2026-10-26)

**Status:** analysis complete; decision open. The founder confirms the default or chooses otherwise. Until then, the protocol uses the default.

**The question (SITREP 2026-09-25, D-6 · F17).** When a calendar carries a global note such as "No Mondays", and a Monday cell is marked as available, should the extraction report the mark (transcribe) or the note's meaning (reconcile)?

## What the data shows (OBSERVED, computed this session)

| Measure | Value | Source |
|---|---|---|
| Published cases with at least one global note | 22 of 40 | `mm_run.py check-cases`; `casesets.global_note_conflicts` |
| Cases where a day-checkable note contradicts a day's mark | **16 of 40** | same |
| Contradicting days | **59 of 1,240** (4.8%): "No Mondays" 27, "No weekends" 19, "Days only" 13 | `D-6_conflict-days_historic-runs.json` |
| Notes that cannot be checked per day | "Max 3 shifts/wk", "Prefer ICU" | skipped |
| Reference labels on the 59 days | The mark as drawn. The generator draws the statuses first and adds the note independently, so the reference is a transcription. | `generate_dataset.gen_truth` (render check: 40/40 pixel-exact) |
| Published task prompt | "Transcribe notes exactly as written; do not invent notes." It defines the status legend per cell and gives no instruction to apply global notes to cells. | `run_eval.TASK_PROMPT` (sha256 of `run_eval.py` `2549b13f…`) |
| Historic Sonnet answers on the 59 days | 59/59 report the mark (0 reconciled) | v1 raw answers via `import-legacy` |
| Historic Haiku answers on the 59 days | 59/59 report the mark (0 reconciled) | same |

## Consequences of each reading

| | Transcription (default) | Reconciliation |
|---|---|---|
| Reference | Unchanged; the 59 days stay as drawn | A versioned corrected reference set would be needed. It would change 59 labels and every historical metric computed on them. |
| Prompt | Unchanged | Must be rewritten, so it becomes a different task from v1 |
| A model that reconciles anyway | Errs on up to 59 days. "No Mondays/weekends" errors go to UNAVAILABLE, so they count as status errors and false unavailability, never as dangerous flips. | n/a |
| Comparability with v1 | Kept | Lost |

## Protocol default

Transcription, with the prompt unchanged. The 59 conflict days are reported as their own slice ("global-note conflict days"). A model that applies notes then shows up in its own row and is not hidden inside the overall error rate. The historical metrics are not revised.

A reconciliation task can be added later as a separately named task variant with its own reference version. It must not be mixed into the comparison.

## Founder input needed

- [ ] Confirm transcription as the comparison's task definition.
- [ ] Or choose reconciliation as an additional, separately labelled task variant (it needs a corrected reference version and a new prompt).
