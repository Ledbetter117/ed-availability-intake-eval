# ED(i) paired simulation pilot — prospective plan

This edition is a synthetic software evaluation, authorized on 2026-11-03. It does not complete or replace the preserved human handwriting/photograph study. No real employee, patient, writer, signature, or staffing decision is represented.

The source software is commit `e7d4f28c00b258ff0d9c421e9e696a11840652f8`. The new generator/scorer are separate simulation additions. No original source data or study decisions are changed.

## Frozen design

- Seed: 2026110301. Twelve distinct latent calendars: three each with 28, 29, 30 and 31 days, selected from fictitious dates in 2024–2032. Calendar layout follows the actual Gregorian month. Random selection is stratified by month length, not a representative sample of workers or handwriting.
- Each calendar has three matched images: typed control, handwriting-font rendering, and degradation of that exact handwriting image. There are 36 scheduled requests, one per image. Conditions share identical latent truth. Fonts are font simulations, not observations from human writers.
- Each calendar includes every status, explicit unavailable marks, legitimate blank availability cells, five day notes, and two global notes. A visible legend defines blank as NOT_SPECIFIED, not available. Notes are invented text. There are no signatures.
- Fonts, their licenses/hashes, all truths, the full plan, prompt/schema, rendering parameters, image bytes, pairing map, and randomized request order are frozen in FREEZE.json before the first model request. Rendering or truth cannot change in response to model outcomes. A discovered defect remains an exclusion/deviation record; it does not authorize silent replacement.
- Fixed handwriting perturbations: independent per-mark offsets at most 3 px and rotation at most 3 degrees. A font is assigned by calendar in a balanced cycle. The degraded condition is the same handwritten image resized to 72%, restored, contrast multiplied by 0.70, Gaussian blur radius 0.55, then rotated 1.25 degrees on white without cropping. The typed condition keeps the same calendar geometry.

## Inference contract

Root controls model selection and dispatch. The producer does not launch inference. Each call receives only PROMPT.txt and the image bytes. Random opaque filenames/request IDs convey no truth, month, calendar ID, font or condition. The private scoring manifest and gold are never included in the request. One call per image, no outcome-driven retries or prompt tuning. Requested temperature 0, maximum output 4096 tokens; root records effective settings, exact model identity, timeout, finish reason and any unsupported settings before dispatch. Missing, failed, truncated, refused or invalid outputs remain results. They are not replaced. Any transport retry must be a separately logged protocol deviation and cannot replace the first observation in primary scoring.

Root writes one observation JSON per request, or a JSON array, using the documented envelope. A response may be absent; the scorer records NOT_OBSERVED until closeout, then reports coverage explicitly. No simulated outcome is invented by the scorer. Its perfect/incorrect examples are test controls only.

## Prospective scoring

Response JSON must contain exactly month, days, global_notes. Each actual date in its stated Gregorian month must appear once. Each day contains exactly status and note. Allowed statuses: AVAILABLE, AM, PM, NIGHT, UNAVAILABLE, NOT_SPECIFIED. All notes must be strings; global_notes must be a list of strings. Duplicate keys, NaN/Infinity, extra fields, out-of-month dates and impossible dates fail strict schema. A single JSON object, with no Markdown/prose, is required. No repair, fuzzy matching, note trimming, case folding or inferred date filling is applied.

Primary endpoint: calendar exact match, requiring successful nontruncated delivery, valid schema, correct month, every date/status/note, and exact global note list/order. Primary denominator is all 12 calendars per condition, including failures. Secondary descriptive endpoints: schema validity; exact status fraction per calendar; exact note fraction across all dates and separately the five note-bearing dates; exact global-note list; and critical flips (gold UNAVAILABLE, prediction AVAILABLE/AM/PM/NIGHT). Wrong-month and invalid/failed responses receive zero status/note credit. Failed extraction is reported separately and is never counted as a safe absence of critical flips. Strict semantic mismatches on otherwise valid responses retain correct-cell credit.

The independent comparison unit is a latent calendar (n=12), not 1,000+ repeated cells. Report the three condition proportions with Wilson 95% descriptive intervals for calendar exactness. Compare handwriting minus typed, degraded minus handwriting, and degraded minus typed using within-calendar differences in exactness and status accuracy. Report mean paired differences and deterministic 95% percentile bootstrap intervals resampling the 12 calendar clusters (10,000 draws; seed 2026110302). These small convenience-sample intervals are descriptive, not population-valid coverage claims; degeneracy at all-zero/all-one differences is stated. No significance threshold, clinical safety claim, causal writer-intent inference or performance-dependent completion gate is used.

## Completion and limits

The simulation edition is complete when the frozen 36-image design, actual observation ledger (including failures), tested scoring, provenance, report, and limitations are delivered. High accuracy is not required. Model behavior on font-generated images cannot establish reliability on human handwriting, phone photographs, private intent, staff availability or real scheduling. The preserved human-study endpoints remain outside this edition.
