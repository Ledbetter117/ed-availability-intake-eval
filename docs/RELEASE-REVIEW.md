# Public software review - 3 November 2026

The root reviewer inspected the changed code, complete technical report, numerical map, public README, export inventory and all five rendered PDF pages. A separate same-family agent reviewed the targeted repairs using its own copies and tests. This is AI-assisted review within one model family, not an independent human panel or clinical validation.

## Reproduced evidence

- 36 source-hash and arithmetic checks independently reproduced the report's historical counts from the public CSV/JSON records.
- A synthetic credential-reflection probe exposed a real successful-response leak before release. The repair now rejects that response as malformed/unavailable, redacts nested keys/values, preserves other JSON types, and prevents accuracy scoring. Long and short test credentials were rechecked independently.
- The separate repair review passed 16 regression tests and seven grouped additional checks covering routes, credential persistence, failed-call caps, baseline identity/completeness and installation drift.
- The root ran all ten public software suites in a real Git checkout: **249 PASS, zero FAIL, seven UNVERIFIED**. The earlier temporary-package run is preserved separately as 246/0/9. Git-specific C8a/C8b/G41 checks passed in the actual checkout.
- Three remaining public checks need intentionally excluded private raw responses; the private stored-answer re-score covers those paths. Two checks need the original font/rendering environment. Two partial HTTP-body observations remain unverified on this Windows host. No unknown was converted into a passing result.

The root also removed unsupported README statements that synthetic accuracy is a mathematical upper bound or that the project establishes clinical safety. Future scheduling ideas remain identified as future work. Exact Git-index bytes were compared against the reviewed export; the gold JSON and calendar PNGs remain unchanged from the prior public data.

Run `python -B tools/run_checks.py` to reproduce the public checks without model inference. The CI definition runs that same entry point on Linux and Windows. Remote CI is separate evidence and is only established when its workflow completes.

## Scope still open

The two real-photograph endpoints require genuine author intent and the missing Arm A material. This release includes their repaired local-only tooling and preserves adopted versus draft amendments. It does not fabricate those inputs, report a new model evaluation, or close the original empirical study.
