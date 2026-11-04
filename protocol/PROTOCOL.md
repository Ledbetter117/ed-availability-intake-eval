# ED-MM-PROTOCOL-0.1 · Cross-model comparison under one frozen task (frozen-ready draft, 2026-10-26)

**Status: FROZEN-READY DRAFT, NOT FROZEN.** It freezes when the founder records ruling `M2-PROTOCOL` with this file's sha256. The model identities are filled in at execution, so the run manifest hash changes then and is re-recorded.

- Nothing in this protocol has run against a model.
- Dispatch is disabled.
- Orca and the local models are occupied as of 2026-10-26, and none was called.

## 0 · Four jobs, kept apart

| Job | Question | Where |
|---|---|---|
| 1 · Repair the instrument | Does the harness parse, validate, score and account for every case correctly? | r6 candidate (offline-verified); v1.1 payload (release) |
| 2 · **Compare individual models** (this protocol) | Under one frozen task, how do one Claude, one GPT and one open-weight vision configuration differ on the same 40 documents? | M2 |
| 3 · System vs single model (later) | Does an OCR or collaborative system beat the strongest single model, at its stated cost? | M3; separate frozen arm |
| 4 · Explain the contribution | What did the work establish, and what can it not establish? | `report/` |

More models do not fix wrong labels, flawed scoring or weak design. Model consensus is never reference truth. Jobs 1 and 4 do not depend on running jobs 2 or 3.

## 1 · Arms and admission

| Arm | Provider / route | Endpoint | Model | Admission |
|---|---|---|---|---|
| `claude` | anthropic / cloud | `https://api.anthropic.com/v1/messages` | TBD at execution | capability check passes; identity recorded |
| `gpt` | openai / cloud | `https://api.openai.com/v1/chat/completions` | TBD at execution | same; `detail` and output budget fixed before freezing |
| `openweight` | ollama_local (or openai_compatible_local) / local | loopback (`127.0.0.1`), or a listed private IP | TBD; must show image input in the capability check | same; weights hash, quantization and runtime recorded |

- The historical Sonnet and Haiku runs (2026-09) are history. They are not fresh arms, and they are reported in their own section, not inside the M2 comparison.
- Qwen-, Jev- and DeepSeek-family candidates are not presumed to accept images. A local text model combined with a separate OCR step is a *system* arm (job 3), not `openweight`.
- **Capability check** (`configs/arms.capability-check.json`): 4 of the 40 cases (one per slice), 1 trial per arm, at most 4 calls per arm plus repairs.
  - It establishes that the image request is accepted, that the answer parses, and which identity is served.
  - It is not scored for the comparison. Its exposures are recorded, and those 4 cases stay in the comparison set.
  - An arm that fails it is not admitted. No substitute model is swapped in silently; a replacement needs a dated amendment.
- **Identity record** (the runner saves it per attempt; fill the template `IDENTITY-RECORD-TEMPLATE.json` per arm before freezing):
  - requested and served model
  - provider, endpoint and route
  - revision or date where available
  - for local arms: weights sha256, quantization, runtime and version, chat template, `num_ctx`, GPU
  - preprocessing (none), sampling (provider default unless stated), thinking/reasoning policy, output limit
  - observed latency, retries and usage
  - Unknowns are written as unknown.

## 2 · Task (frozen)

- **Prompt:** `run_eval.TASK_PROMPT`, unchanged from v1. The scorer, parser and prompt are pinned by the sha256 of `run_eval.py` (`2549b13f0a30be7f60f891d136b0f6484ebd9e7ceae4866852fd1f2c143661e8`).
- **Task reading:** transcription (`D-6_task-definition.md`). The 59 global-note conflict days are reported as their own slice.
- **Schema:** exactly `month`, `days` (every day, each with `status` from {AVAILABLE, AM, PM, NIGHT, UNAVAILABLE} and a `note` string) and `global_notes` (a list of strings). Strict parsing rejects conflicting duplicate keys and NaN/Infinity. An answer is validated before it is scored.
- **Image policy:** the stored PNG bytes are sent as `image/png`. The harness does not resize or re-encode. Provider-side resizing is recorded where the provider reports it.
- **Context policy:** one fresh single-turn request per attempt, with no system prompt and no earlier turns. The model never sees reference labels or another arm's output.
- **Tools:** none (no web, search, OCR helper or code execution).
- **Repair allowance:** 1 extra attempt for an unparseable answer, using the v1 repair suffix. A schema-invalid answer is not repaired.
- **Transport retries:** a transient failure (HTTP 408/409/429/5xx/529 or a network error) is retried with backoff of 2, 8 and 30 s, up to the arm's `max_attempts_per_trial`. A permanent failure ends the unit as `unavailable`.

## 3 · Cases

- **Set:** the 40 published synthetic cases. Set hash `1d62aa17ecdcf5f41b03a181bcf47aa33a8713fbb80a96992cd602631b58edc2` (case id + image sha256 + reference hash).
- **Integrity, checked 2026-10-26:**
  - every reference regenerates from its seed (40/40);
  - every image re-renders pixel-exactly from its reference with the bundled hand font (40/40);
  - no duplicate images or references;
  - a planted one-day change is detected.
- **Role:** a diagnostic and compatibility set. It has been public since 2026-09, so results show compatibility on these examples, not generalization. Every report says so.
- **Confirmation set** (only if a generalization claim is wanted):
  - built from new seeds and new latent calendars;
  - `check_splits` must report no shared seed, image or reference;
  - fonts pinned;
  - no prompt or setting tuned on it;
  - it gets its own amendment before scoring.
- **Historical assets are never re-rendered in place.**

## 4 · Execution

- **Planned shape** (ceiling, not spending authority): 3 arms × 40 cases × 3 trials = **360 primary units**, plus the 12-unit capability check. One sweep (120 units) is a single-trial comparison until all three trials finish.
- **Order:** trial-major, then a seeded shuffle of cases (`order_seed` `ed-mm-2026-10-26`), then every arm. Each document is read by every arm close together in time.
- **Ledger:** manifest (`manifest.json`), append-only `attempts.jsonl`, terminal `results.jsonl`, raw answers in `raw/` (gitignored, never overwritten) and `run_status.json`.
- **Resume:** only with an identical manifest hash. A changed configuration needs a new run directory and a dated amendment.
- **Stop rules:**
  - Stop an arm on a served-identity mismatch, an exposure or input-integrity problem, or persistent transport failure. Its planned-but-unrun units stay counted.
  - Never stop because one arm is winning.
  - No silent rerun, substitution or fallback.
- **Dispatch gate** (all are required): CLI `--dispatch`; `dispatch.enabled`; every arm `ready` and `dispatch_enabled`; a real model name; image capability verified (except in the capability check itself); positive limits; `run_caps.max_calls_total`; credential variables set; `MMEVAL_DISPATCH_ACK` set to the first 12 characters of the final manifest hash.

## 5 · Measures

| Block | Measures | Denominator |
|---|---|---|
| Accounting | scored, invalid, truncated, refused (abstention), unavailable, route-denied, unrun; **unusable rate** | every planned unit |
| Historic (v1 definitions, unchanged) | day accuracy, critical-error rate (UNAVAILABLE → available), note mismatch, note fidelity, format validity | units that produced an answer (conditional) |
| Extended (new, labelled) | status error rate, **false-unavailable rate**, dangerous flips, constant-output count, note omissions, displaced, fabricated; global-note conflict slice; per slice | scored units |
| Document level | **document success**: all statuses correct and no flip; an unusable trial counts as failure (ITT) | planned trials per document |
| Variability | fraction of days where trials disagree; within-document SD of day accuracy | documents with 2 or more scored trials |
| Resources | attempts, reported tokens, latency, served identity | per arm; tokens are never converted to subscription percentages |

**Degenerate-output guard.** A critical-error rate of 0 together with a false-unavailable rate above 50% or a constant output is flagged DEGENERATE and is never reported as safe.

**Primary outcome (fixed before scoring):** document success (ITT), averaged over trials within each document.

**Secondary outcomes:** dangerous flips, false-unavailable rate, unusable rate, status error rate, note measures.

## 6 · Analysis (fixed before scoring)

- The unit is the **document**. Trials are averaged within a document first.
- **Planned contrasts (3):** claude − gpt, claude − openweight, gpt − openweight.
- For each contrast:
  - mean difference in document success, with a seeded paired bootstrap 95% CI over documents (10,000 resamples, seed 20261026);
  - an exact two-sided sign test over documents;
  - Holm's adjustment across the 3 contrasts;
  - a conditional day-accuracy difference on documents usable in both arms, labelled conditional.
- Per-slice and conflict-day tables are descriptive only, with no tests.
- **No universal pass threshold and no best-model headline when intervals overlap.** With n = 40 public documents, small differences are not resolvable. Say so.
- Optional model adjudication of notes (`--judge` in v1) is excluded from M2.

## 7 · Resources and caps

See `RESOURCE-ESTIMATE.md`. Every cap starts as an unresolved field. The gate refuses until the founder records `M2-BUDGET`: availability, `max_calls_total`, per-arm `max_calls`, elapsed-time ceiling, and either a money ceiling with prices or an explicit statement that money is not capped by the harness. A Claude subscription is not API spending authority.

## 8 · Data boundary

- Only public synthetic cases may go to cloud arms.
- The founder's photographed probe documents (both arms) stay local under D-1 and Amendment 01 §4b, so they are not part of this protocol. The probe follows Amendment 02.
- `private_local_only` data can never be configured for a cloud arm. The config refuses it.

## 9 · What this cannot show

- Real-world staffing performance.
- Performance on genuine handwriting.
- Generalization beyond these 40 exposed synthetic documents.
- Clinical safety.
- That any model "understands" schedules.
- A passing mock or replay is not a provider run.

## 10 · Freeze and amendments

The founder records `M2-PROTOCOL` = FROZEN with this file's sha256 and the arm identities. Any later change — a model swap, a prompt variant or a confirmation set — is a dated amendment with its own manifest. Results under the earlier manifest are kept and labelled.
