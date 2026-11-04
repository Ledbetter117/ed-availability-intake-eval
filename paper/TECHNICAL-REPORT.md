# Separating extraction errors from evaluation errors in synthetic availability calendars

Galen Coulter-Ledbetter, RN, Paramedic

Technical report and preprint candidate · 3 November 2026

## Abstract

An extraction benchmark can mislead even when its arithmetic is correct. This report describes an audit and software repair of an evaluation that converts synthetic staff-availability calendars into structured data. The historical dataset contains 40 calendars and 1,240 day cells per evaluated model. The saved results label the models `claude-sonnet-5` and `claude-haiku-4-5`; these identifiers are reported as recorded, without inferring model lineage or current availability. Their status-error counts were 0 and 26, respectively. A metric originally called a hallucination rate counted notes attached to the wrong location. The typed correction found 1 displaced predicted note among 147 predictions for the first model and 9 among 145 for the second, with no note fabrication recorded. At document level, any status or note error affected 1/40 and 12/40 calendars. The audit also identified content–rendering confounding, inappropriate independence assumptions, and incomplete software controls. The repaired tooling separates unavailable responses from scored errors, bounds local authenticated requests, preserves attempt evidence, and refuses mismatched installation files. Historical-response re-scoring and synthetic engineering tests support these software and accounting claims. They do not establish performance on real handwriting, a local model, or clinical use. Both planned photograph probe arms remain without completed empirical endpoints.

## 1. Purpose and scope

Availability intake is a document-extraction task: a calendar image must become a structured month, daily availability statuses, and notes. The evaluation examines the correctness of that transcription. It does not assign staff, estimate staffing adequacy, or test patient outcomes.

The contribution is a traceable correction of measurement and execution errors in a small evaluation artifact. The original release remains recoverable in repository history. This report separates the historical synthetic observations, the later repairs to the instrument, and the unfinished photo probes. It makes no claim that this evaluation design is novel or that it ranks current frontier models.

The numerical source map accompanying this report links its results to machine-readable artifacts. Private historical response text was used for an offline re-score but is excluded from the public package. Public readers can recompute the published aggregate counts from the per-case and typed-error records; they cannot independently establish the original service identity from those aggregate records alone.

## 2. Data and task

The dataset contains 40 generated monthly calendars, with 10 each in clean, rotated, low-contrast, and handwriting-font render conditions. The handwriting-font condition is synthetic; it does not represent a human writer. A generator first creates a structured reference and then renders an image. The reference includes daily statuses and notes. The required model output is structured JSON containing the month, every day, and global notes.

The historical record reports one extraction run per model across the same calendars. Each run covers 1,240 day cells, including 316 reference days marked UNAVAILABLE. The model labels in the saved records are `claude-sonnet-5` and `claude-haiku-4-5`. No new model inference was performed for this repair or this report.

Content and style vary together in the original generator. Consequently, differences between rendering slices cannot isolate a causal effect of rotation, contrast, or font. Reproduction of the semantic reference data also differs from pixel-exact rendering: the latter depends on the original fonts and rendering environment.

## 3. Measurement corrections

### Status errors and denominators

Day accuracy counts exact agreement with the reference status. The asymmetric error measure counts a reference UNAVAILABLE day returned as an available status. Its denominator is reference UNAVAILABLE days, not all days. This is a transcription error with a potential scheduling consequence; the evaluation does not demonstrate a safety event.

Document-level error counts answer a different question from cell-level accuracy: whether a returned calendar contains at least one error. Cells within one calendar share content, layout, and capture conditions. They therefore cannot be treated as independent replications of the document-level experiment. The report emphasizes counts and document denominators; previously calculated cell-level intervals are descriptive and may be too narrow.

### Displacement is different from fabrication

The original note metric compared a predicted note with the reference note at the same location. A mismatch does not establish that the text was invented. The typed audit separates an on-page note placed at a wrong location from text absent from the page.

The denominator also depends on the question. Recovery of reference notes uses reference items. Fabrication and displacement rates use predicted note instances. The first model emitted 147 note instances and the second 145, while each reference set contained 146 note items. These counts cannot be exchanged merely because some rounded percentages appear similar.

## 4. Historical synthetic results

| Measure | `claude-sonnet-5` (recorded label) | `claude-haiku-4-5` (recorded label) |
|---|---:|---:|
| Correct daily statuses | 1,240/1,240 | 1,214/1,240 |
| Status errors | 0/1,240 | 26/1,240 |
| UNAVAILABLE-to-available errors | 0/316 | 6/316 |
| Calendars with a status error | 0/40 | 9/40 |
| Calendars with any status or note error | 1/40 | 12/40 |
| Displaced predicted notes | 1/147 | 9/145 |
| Fabricated predicted notes | 0/147 | 0/145 |
| Reference notes recovered at their correct location | 146/146 | 136/146 |

Sources: `results/per_case.csv`, `results_haiku/per_case.csv`, `calendar_level.csv`, and `typed_errors.json`; see `NUMERICAL-SOURCE-MAP.json` for field mappings and recomputation checks.

The first model reached the ceiling for status extraction on this dataset, but its note duplication means that perfect status accuracy was not perfect document extraction. The second model's 26 status errors were concentrated in 9 calendars; adding note-only errors raises the count of affected calendars to 12. The observations therefore support a narrow statement about these stored outputs on this corpus. They do not establish general model safety or real-handwriting accuracy.

The zero-fabrication observations concern 147 and 145 predicted instances in this corpus. They are not a proof that the models cannot fabricate. Pooling the predictions would also combine two systems and correlated observations from the same documents.

## 5. Software validation and repairs

The repaired multi-model layer records explicit provider, route, model configuration, input identity, and trial outcomes. A local authenticated OpenAI-compatible endpoint must be on loopback. A configured credential must exist before dispatch; it is passed through the existing request builder. Redirects and environment proxies remain disabled. An endpoint that reflects a credential in an otherwise successful response is treated as unavailable: the value is removed from retained evidence and the response is excluded from accuracy scoring. This prevents a redacted answer from silently becoming an ordinary scored observation.

The installed-package wrapper now refuses execution when a manifest entry is missing or changed, and forces a failed result if files change during execution. This protects against accidental drift. The manifest is not a digital signature or proof against an attacker who can replace the program and manifest together.

The photo-probe tooling uses the same local route checks. It forwards the selected local credential, enforces the configured call bound, refuses reuse of a nonempty real-run output directory, and preserves response attempts. A real Arm B baseline must identify the same configured arm and contain the complete selected synthetic trial. It cannot silently combine different arms or accept duplicated or missing case outcomes.

Validation uses a mix of stored-answer re-scoring, synthetic response doubles, deliberate fault controls, and temporary loopback HTTP servers. The test record reports failures and unverified checks separately. The private historical re-score reproduced the saved scoring contracts without new inference. Missing reference rendering dependencies and host-specific partial-response behavior remain explicit limitations. Passing these tests is evidence about the software paths exercised, not completion of the empirical study.

## 6. Photograph probes: preserved scope and unfinished endpoints

Both original probe arms remain in scope. Arm A compares copied and authored documents. Its initial collection is a pilot, because the document-level design cannot produce the advertised decisive contrast at that stage. Arm B uses the author's existing real documents, with intended meanings supplied independently of model output. The duplicate-month document is reported but excluded from decision denominators.

Amendment 01 changes the inferential unit to the document and retires CLOSE. Its owner ruling selects a local vision route for photographed documents. Amendment 02 remains an unfrozen draft: model identity and settings, a same-model synthetic baseline, and unresolved feasibility and failure-handling choices must be recorded before photo scoring. This report does not treat the older cloud-model or CLOSE language as an active requirement.

The checked source materials do not contain completed Arm A photos, completed behavior coding, or completed authored intent sheets. The Arm B workbook and intent files contain no completed intended-status answers or grid defaults. Existing inferred legends are candidate interpretations, not the author's confirmed intended meanings. Copyist references and public synthetic labels can be recovered mechanically. Private author intent cannot be manufactured from a model's reading without changing the question being tested.

No Arm A or Arm B empirical result is reported here. A future edition must distinguish locally qualified model performance, descriptive photo results, and any outcome of a frozen decision rule. These endpoints are separate from the present software release.

## 7. Limitations and reproducibility

This is a small, retrospective synthetic evaluation with two recorded model configurations and one stored run per configuration. The document content and rendering conditions are confounded. Handwriting is represented by a font. The historical raw response re-score validates scoring consistency but does not independently authenticate the original provider execution or resolve model-label provenance. Real authored intent, real-world reliability, current model rankings, staffing quality, and clinical outcomes remain outside the evidence.

The public artifact contains source code, generated inputs and references, aggregate historical results, correction records, synthetic tests, and this report. It excludes private photographs, actual availability labels, private document mappings, raw response archives, credential values, and internal review folders. The software uses the repository's MIT license; the bundled Patrick Hand font retains its separate SIL Open Font License notice.

The intended reproducibility claim is precise: public aggregate results can be recomputed, the engineering checks can be rerun, and the unfinished experiments can be identified. It is not a claim that rerunning a remote model today would reproduce historical responses.

## Artifact references

1. Repository and preserved release history: https://github.com/Ledbetter117/ed-availability-intake-eval
2. Historical source records: `results/metrics.json`, `results_haiku/metrics.json`, both `per_case.csv` files, `calendar_level.csv`, and `typed_errors.json`.
3. Measurement correction: `analysis-v2.md`, `docs/CORRECTIONS.md`, and `docs/METHODS.md`.
4. Probe scope: `docs/PROBE.md`, `docs/PROBE-B.md`, `docs/PROBE-AMENDMENT-01.md`, and the explicitly draft `docs/PROBE-AMENDMENT-02.draft.md`.
5. Current software evidence: `docs/VALIDATION.md`, `docs/RELEASE-STATUS.md`, and `docs/NUMERICAL-SOURCE-MAP.json`.

## Disclosure

AI assistants supported implementation, artifact auditing, and drafting. The report is a technical preprint candidate, not a peer-reviewed paper or a completed clinical study. Publication status and the final commit identifier belong in the release record; no submission or acceptance is claimed here.
