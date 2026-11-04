# Probe amendment 02 — the local route, its synthetic baseline, and what "cross-family" means (DRAFT)

**Status: DRAFT, 2026-10-26.** It is not published and it is not the rule. It takes effect only after:

- the founder records ruling **A-02 = FROZEN** with this file's sha256;
- the file is published to the repository;
- both happen before any probe image is scored.

Facts so far:

- No photograph has been taken for Arm A.
- No intent sheet has been filled for Arm B.
- No scorer has been run on any probe document.
- No local model has been called. The local machine was occupied on the drafting date.

**Why this exists.** Amendment 01 §4b recorded a ruling (2026-09-25, D-1): the photographed documents in both arms are scored by a **local** vision model, subject to a feasibility check on the public synthetic calendars, and "*what that changes for the design will be published as PROBE-AMENDMENT-02.md before any probe image is scored: which model is used and how it is run, the synthetic baseline it is compared against, and what the cross-family requirement means for a local model.*" This draft answers those three items. Where the answer needs a fact that does not exist yet, it says **PENDING** and names who supplies it.

`PROBE.md`, `PROBE-B.md` and `PROBE-AMENDMENT-01.md` are not edited.

---

## 1 · Which model, and how it is run — PENDING (founder)

| Item | Value |
|---|---|
| Runtime and version (Ollama, or an OpenAI-compatible local server) | **PENDING** |
| Model name, and the digest or weights sha256 | **PENDING** |
| Quantization | **PENDING** |
| Hardware (GPU, memory) | **PENDING** |
| Context window (`num_ctx`) and output limit | **PENDING**; output limit at least 4,096 tokens |
| Sampling | Runtime default unless the founder sets a value; whatever is used is recorded |
| Endpoint | Loopback only (`127.0.0.1`). A LAN host only if its private IP address is listed in `trusted_local_hosts` and it is a machine the founder controls. Names and public addresses are refused. |
| Image input | Must be shown by the capability check (§2). It is not presumed from the model's name or family. |

The arm is configured as an `mmeval` local arm (candidate r6) with `allowed_data_classes` including `private_local_only`. The configuration layer refuses that data class on any cloud arm, refuses a non-loopback endpoint for a local arm unless it is listed as trusted, and has no fallback field. Offline checks: r6 G3, G5, G7, G8, G10, G11; probe tooling T12, T13.

## 2 · Feasibility check (D-1's condition) — on public synthetic data only

1. **Capability check.** Four public synthetic calendars, one per slice, one trial, unscored for any comparison. It shows that the model accepts the image request, that the answer parses, and which model identity is served.
2. **Synthetic run.** All 40 public synthetic calendars, the v1 task prompt unchanged, one trial, scored by the v1 scorer. This run is the **Arm B synthetic baseline** (§3). It can also serve as the `openweight` arm's first trial in the multi-model comparison, if the protocol settings match.
3. **Feasibility criterion — PROPOSED, founder to confirm.** The route is feasible if at least **36 of 40** synthetic answers are usable (parsed and schema-valid). Otherwise Arm B needs a new decision before any photograph is scored: a different local model, or dropping Arm B.

No probe photograph is involved in §2.

## 3 · The synthetic baseline for Arm B

- **Same arm.** The same model, runtime, quantization and settings as the Arm B run. A baseline from a different model is not a baseline (PROBE-B.md compares a model against its own synthetic run).
- **Counted in error documents** (Amendment 01): a synthetic calendar is an error document if it has at least one status error. **An unusable answer counts as an error document.** That choice is conservative for B-PROCEED. *Founder to confirm.*
- **Read from the run's results file**, never typed in (`probe_b.py --baseline <arm>=<run>`). Trial 1 of each calendar.
- **Known difference, carried over unchanged.** The synthetic run uses the v1 prompt, which states the legend. Arm B's deciding output is LEGEND-BLIND. This was the original design (PROBE-B.md §6), and it is stated here so that it is not mistaken for a new choice.
- **Reachability depends on the baseline. It is computed now, before the baseline exists** (`tooling/arm-b_reachability_by-baseline.txt`). The decision uses the 6 grid documents, with G3 excluded.

| Synthetic error documents (of 40) | Minimum real error documents (of 6) that fire B-PROCEED |
|---|---|
| 0–1 | 2 |
| 2–4 | 3 |
| 5–9 | 4 (9 of 40 → 4, as in Amendment 01 for Haiku) |
| 10–13 | 5 |
| 14–21 | 6 |
| **22 or more** | **unreachable**: B-PROCEED cannot fire; Arm B can only return B-CONTINUE or a descriptive report |

*Computed by `probe_decide.reachability_table()`. A first hand-written version of this table had wrong band edges and was corrected against the computed table before saving.*

> **If the local model's synthetic baseline is 22 of 40 or worse, Arm B cannot decide.** That is stated here, before collection. It is not a finding to be discovered afterwards. The founder then chooses: run Arm B as descriptive only, or qualify a stronger local model first.

## 4 · What "cross-family" means now

The OpenAI-family requirement existed to make CLOSE valid. CLOSE is retired (Amendment 01 §3), so the requirement no longer gates any branch. It is kept as a statement:

- Results name every model family that ran.
- A single-family run says that it describes one family only.
- **Recommended, not required:** if the hardware allows, a second local vision model from a different family, with its own capability check and its own synthetic baseline. Each model is reported separately. The rule still decides on the best model, as before.

Nothing about the cloud models' behaviour on public synthetic data can be carried over to private documents. The cloud comparison (ED-MM-PROTOCOL) never receives probe images.

## 5 · Arm A under the local route

The rules are unchanged from Amendment 01 §4:

- the unit is the document;
- Stage 1 (3 per arm) is a pilot and reports no verdict;
- Stage 2 (7 per arm) needs at least 5 of 7 authored error documents against 0 of 7 copyist, a two-sided Fisher p below 0.05, and non-overlapping Wilson intervals;
- parse failures are excluded and listed, as in PROBE.md;
- CLOSE is retired.

Arm A needs no synthetic baseline. The local route replaces the cloud adapters, and the same capability check applies.

## 6 · Arm B parse failures — carried rule, made explicit

PROBE-B.md (carried over unchanged by Amendment 01 §4) scores "every document including badly photographed ones". In the amended unit, **a deciding grid document whose answer cannot be parsed counts as an error document and is listed.** The 2026-09-12 code excluded such documents. That was a mismatch, and the candidate corrects it (probe_b T8). *Founder to confirm that this is the intended reading.*

## 7 · What leaves the machine

On the local route, the images are **not transmitted to any third party**. That restores the original PROBE-B.md sentence ("only derived numbers leave the machine") as a statement about transmission, as long as the endpoint is loopback or a trusted machine the founder controls. Raw model answers stay local (gitignored). Request logs and dry-run packets replace image bytes with a hash.

## 8 · Code alignment (candidate A02-r1, not yet adopted)

| File | Change | Checks |
|---|---|---|
| `probe_decide.py` (new) | Amendment 01 §3/§4 rules in one place; CLOSE cannot be returned | self-test 18/18 reproduces every number in Amendment 01 §3 and §4 |
| `probe_score.py` | Document-level Arm A decision; Stage 1 PILOT; local route only; strict JSON; PROCEED no longer mentions recruiting writers (R-3) | self-test PASS |
| `probe_b.py` | Document-level Arm B; G3 excluded; parse failures counted; baseline from a results file in error documents; local route; **RES-03 fixed** (legal statuses only) | 18/18 in a clean room, and with a synthetic map present; the published Sonnet and Haiku runs give 0/40 and 9/40 |
| `probe_integration_test.py` | T4–T6, T8 re-specified; T6b–T6d (Stage 2 minimums); T12–T13 (local only) | 16/16 |
| `make_probe_kit.py` | MANIFEST carries the amended rule; the 2026-09-03 rule is kept under its own key | runs inside the integration test (T1) |
| Positive controls | 7 planted defects | 6 caught; 1 equivalent mutant (direction is implied by non-overlap), recorded as such |

A real run requires `--amendment-02-frozen`. Pass it only after A-02 is frozen and published.

## 9 · Inputs still needed (founder)

- [ ] §1 runtime, model, digest or weights hash, quantization, hardware, `num_ctx`
- [ ] §2 feasibility criterion (proposed: at least 36 of 40 usable)
- [ ] §3 an unusable synthetic answer counts as an error document (proposed: yes)
- [ ] §6 an Arm B parse failure counts as an error document (proposed: yes, per PROBE-B.md)
- [ ] D-1 scope: does Amendment 02 have to be frozen before capture (I-9), or only before scoring (I-11)? The draft assumes before scoring.
- [ ] A-02 ruling: FROZEN, REVISE or REJECT

## 10 · What this does not change

- No image has been scored, and no result exists.
- The v1 benchmark numbers are untouched.
- The document sets are frozen as before.
- The Arm A confound stands: a hand rushed under a timer is also a less legible hand.
- One writer bounds everything.
