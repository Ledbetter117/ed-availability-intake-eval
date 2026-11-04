# Multi-model runner (r7.4 software candidate)

Status: software candidate. No new model inference was performed for this edition. The current release and test limits are in RELEASE-STATUS.md and VALIDATION.md. The inherited r6/r7.1/r7.2 behavior below remains unless a later section says otherwise. Synthetic loopback tests supplement response doubles.

## What it adds

`run_eval.py` remains the single-model harness that produced the published v1 results. It is unchanged in r6. `mm_run.py` and the `mmeval/` package add a layer for comparing several model configurations under one frozen task:

| Part | Job |
|---|---|
| `mmeval/config.py` | Explicit arm configuration: provider, route (cloud or local), endpoint, modalities, allowed data classes, limits. Nothing is inferred from a model name. |
| `mmeval/transport.py` | Deny-by-default transport; an offline recorded double; the HTTP transport, which re-checks the destination on every request. |
| `mmeval/adapters.py` | Request and response shapes for Anthropic Messages, OpenAI Chat Completions and the Ollama chat API. |
| `mmeval/casesets.py` | Case identity (image hash and reference hash), duplicate and split checks, and a check that each image re-renders from its reference. |
| `mmeval/runner.py` | Run manifest, unit plan, append-only attempt ledger, bounded retries, resume and the dispatch gate. |
| `mmeval/replay.py` | Offline replay of stored responses; import of the historical v1 raw folders. |
| `mmeval/report.py` | Accounting, the unchanged v1 metrics, new metrics, and paired document-level comparisons. |
| `configs/arms.queued.json` | Three queued arms (Claude, GPT, one local open-weight vision model). Dispatch is disabled; model names are placeholders. |

## Routing rules

- An unknown provider is refused.
- A cloud arm may send only to its provider's documented HTTPS host.
- A local arm may send only to a loopback address, or to a private IP address listed in `trusted_local_hosts`. Names and public addresses are refused there, because a name can resolve anywhere. There is no fallback field. An unknown configuration field is an error.
- A task that sends an image is refused on an arm that does not declare image input.
- Data marked `private_local_only` can never be allowed on a cloud arm.
- The transport repeats the destination check on every request.

## Outcomes and denominators

Each unit is one arm, one document and one trial. A unit ends as `scored`, `invalid`, `truncated`, `refused`, `unavailable` or `route_denied`. A planned unit with no outcome is `unrun`. Each report shows three blocks:

1. **Accounting.** All planned units. `unusable_rate = (planned − scored) / planned`.
2. **Historic.** `run_eval.aggregate()` unchanged, over the units that produced an answer. These rates are conditional on an answer.
3. **Extended (new in r6).** False-unavailable rate, status error rate, note omissions, constant-output count, document success (all planned units in the denominator), repeated-run variability.

r7.2: each arm summary carries a `denominators` map. Its keys are the dotted paths of the summary's rates (for example `historic_conditional.day_accuracy` or `extended.per_slice.<slice>.status_error_rate`), and each value states, in words, what that rate divides by. The r7.1 `extended.rate_denominators` block is unchanged. The accounting block also counts `replay_identity_units`: units that ended unavailable because a replay could not serve their own stored attempt (below). They are counted as unavailable, and the report lists them so they are not read as model failures.

An arm that has a critical-error rate of 0, but marks most available days UNAVAILABLE or gives a whole month one status, is flagged **DEGENERATE**. Marking every day unavailable can never flip an unavailable day, so in this case a zero critical-error rate is not evidence of safety.

## Retries, resume and replay

- A transient transport failure is retried, with backoff, up to `max_attempts_per_trial` attempts.
- An answer that does not parse gets one repair attempt, with the same suffix the v1 harness used.
- An answer that fails the schema check is not repaired.
- Every attempt is kept.
- To resume, the manifest must be identical. A unit whose answer was stored before its outcome was written is finished from the stored answer.
- r7.2: a run is resumed only under the runner policy that started it. The policy (`runner_policy`: an ambiguous send is resent only under `protocol.ambiguous_resend`) is part of the hashed manifest, so the binding holds both ways: r7.2 refuses a directory started by r7.1 or earlier, naming the policy, and r7.1 refuses a directory started by r7.2 (its manifest hash differs). `run_status.json` also names the runner edition. Replay always writes a new run directory and compares manifests without `runner_policy`, so a source started by an earlier runner with an otherwise identical manifest still replays.
- Replay feeds stored responses back through the same state machine without network access.

### Replay identity (r7.2)

A stored attempt is served only to the same unit and the same attempt number, and only when its recorded request hash equals the new request's hash. The runner names each send with `bind_identity(unit_id, attempt)`; a binding is used once. A send with no binding, a missing record, a hash mismatch, or a stored raw file that is not this unit's and this attempt's (by its canonical name `raw/<unit>.a<attempt>.json` and, where recorded, by the ids inside it; r7.2-p3) is a non-transient failure with reason `replay_identity`: nothing is served, the unit ends unavailable, and its outcome row carries `unavailable_reason: replay_identity`. r7.1 served a queue keyed by request hash, so a unit could receive another unit's answer.

A replay source is refused when the replay is built if it holds a duplicate (unit, attempt) record, or an intent or raw file with no attempt record (an unreconciled run). Owner-settled attempts replay their settlement. `replay --allow-changed-scorer` is refused if the two manifests differ in anything except the scorer hash and the bookkeeping fields `manifest_hash` and `replayed_from`.

### Malformed 2xx and ambiguous sends (r7.2)

The HTTP transport classifies a failure by how far the exchange got:

| What happened | Class | What the runner does |
|---|---|---|
| The request was not completely sent (connect or send error; the server may have the request line, never the whole body) | transient | retries within the attempt limit |
| It was sent, but no valid status line came back (timeout, reset, close) | transient and ambiguous: the provider may have it | does not resend by default; the unit ends unavailable |
| A 2xx status arrived, then the body could not be read or decoded | malformed | saves a raw record of kind `malformed_2xx` with the text that arrived (up to 65,536 characters; longer text is cut and marked `body_truncated`); the attempt is `bad_provider_shape`; never retried |

An ambiguous send is resent only when the owner sets `protocol.ambiguous_resend: true`. That setting is part of the manifest, so changing it changes the manifest hash. Each such resend is marked `ambiguous_resend` in its attempt row.

### Owner actions: settle and unlock (r7.1; r7.2 hardening)

- `mm_run.py settle` records the owner's decision for one UNRESOLVED send: an intent with no saved response, no attempt record and no outcome. `count_unavailable` ends the unit unavailable and sends nothing; `resend_authorized` lets the next run send one new attempt within the arm's attempt limit. Settlements are appended to `settlements.jsonl` with `--by` and `--reason`. Anything that is not unresolved is refused.
- `mm_run.py unlock` moves a `run.lock` aside (never deletes it) and logs the action in `owner-actions.jsonl`. r7.2: the lock records the host instance (Windows MachineGuid; on POSIX the machine id, boot id and pid namespace). The lock is released only when it parses, names an integer pid and this host instance, and the process is dead or has a different creation time. An unreadable, empty or torn lock, an r7.1 lock without a host, another host instance, or a live pid without a recorded creation time is refused, and the lock is kept as found. Unknown is not dead. If logging fails after the move, the refusal says the lock WAS moved and where. A moved lock is never overwritten: its name carries a unique suffix. If the lock changed between the identity check and the move (another run took it), it is put back when `run.lock` is free and the release is refused, naming both files.
- Both commands refuse malformed run state (for example a manifest of the wrong shape, or a row without its keys) with one `REFUSED` line and exit 2, never a traceback.

### Legacy import refusals (r7.2)

`import-legacy` validates the whole prior state of every case before it writes anything (r7.2-p3: a refusal for any case writes nothing for any case). Duplicate attempt or outcome rows are refused. The prior attempt records must be exactly attempts 1..k, each matching the source; a raw file without a record is allowed only for attempt k+1 (an interrupted import) and is reused. Anything else is refused. On a refusal, the previous `run_status.json` is kept as `run_status.before-refusal-<UTC>.json`, the status becomes `IMPORT_REFUSED` naming that file, and a row is appended to `import-refusals.jsonl`. Nothing is deleted. A torn ledger line still gives an `IMPORT_REFUSED` status (`results_rows_now: null`). A directory that belongs to another manifest is refused without any write to it.

## Dispatch

Dry-run is the default. `mm_run.py plan` writes a packet with one scrubbed example request per arm and the full unit count, and sends nothing. `mm_run.py run --dispatch` builds a network transport only when all of these are true:

- the config has `dispatch.enabled: true`;
- every arm is `ready`, has `dispatch_enabled: true`, a real model name, a verified image capability and positive limits;
- `run_caps.max_calls_total` is set;
- every selected credential variable is set, including an optional local credential;
- `MMEVAL_DISPATCH_ACK` holds the first 12 characters of this run's manifest hash.

Credentials are read only from the environment at send time and are never written anywhere. A passing mock or replay is not a provider run.

## Verified offline (2026-10-26)

Counts and outputs are recorded with the candidate package, not here, so this page cannot go stale when checks are added.

| Check | Result |
|---|---|
| Section G of `tests/test_harness.py` | Every check passes. The candidate's evidence folder records the counts for each checkout type. |
| Planted defects (candidate package, `tools/mutation_controls.py`) | Each planted defect is caught by the section G check named for it |
| Stored v1 answers imported through the new layer | Reproduce both published `metrics.json` files exactly (G38) |
| All 40 published images | Re-render pixel-exactly from their references, and each reference regenerates from its seed (G36, G37) |
| One-day change to a reference (planted) | Detected (G36) |

## Limits

- The 40 published documents are a diagnostic and compatibility set, already public. A confirmation claim needs a disjoint set, built from separate seeds and checked with `check_splits`.
- Statistics are small-sample. Trials are averaged within a document before any comparison.
- Request shapes follow the providers' documentation as read on 2026-10-26. They are untested against live endpoints.

## Local authentication and credential reflection (r7.4)

An `openai_compatible_local` arm may name `credential_env` only for a loopback endpoint. The credential is supplied as the existing Bearer header; it is never embedded in a URL or configuration. A missing selected credential refuses dispatch. Ollama credentials are refused because that adapter does not send them.

Explicit credential values of any nonzero length are redacted from errors. If a successful JSON response reflects a credential in a string key or value, the redacted response is retained as malformed/unavailable evidence and excluded from scoring. This preserves numeric fields while preventing an altered answer from being silently scored. See `tests/test_r74.py`.
