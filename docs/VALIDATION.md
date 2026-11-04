# Validation record

The final package run recorded **246 PASS, 0 FAIL, and 9 UNVERIFIED** across ten suites on Windows with Python 3.12.14. All 161 manifest entries matched before and after that code verification. Later documentation/export additions are recorded by the final package manifest. These are software checks, not model-accuracy observations.

| Suite | PASS | FAIL | UNVERIFIED |
|---|---:|---:|---:|
| Harness | 105 | 0 | 7 |
| r7.1 | 15 | 0 | 0 |
| r7.2 | 66 | 0 | 0 |
| r7.3 | 10 | 0 | 2 |
| Scripted partial responses | 11 | 0 | 0 |
| Lock release race | 2 | 0 | 0 |
| Resume/reporting | 21 | 0 | 0 |
| Local authentication and reflection | 7 | 0 | 0 |
| Probe dispatch/baseline | 5 | 0 | 0 |
| Package integrity wrapper | 4 | 0 | 0 |

Separate checks: the private historical-response re-score reported **120 PASS, 0 FAIL, 4 UNVERIFIED**, using the saved 40 responses per model. This resolves the raw-answer requirements absent from the public tree, without exporting those answers. Probe decision self-tests passed 18/18, Arm B self-tests 18/18, Arm A self-test passed, and the Arm A integration path passed 16 checks. These are overlapping suites and are not added to a single unique-coverage total.

The public run's exact unverified checks were A:results, A:results_haiku, G38 (raw answers absent); C8 and G41 (temporary copy has no Git metadata); G36 and G37 (reference DejaVu font path/rendering environment unavailable); and FT1-A2/FT1-B2 (partial Content-Length body withheld below the application on this host). The private re-score retained only C8, G36, G37, and G41 as unverified. The checks distinguish software behavior from empirical model accuracy and preserve failed attempts as evidence.

Validation includes the complete existing harness, resume/recovery suites, transport and lock-race regressions, local authentication and credential-reflection tests, installation-integrity controls, and the photograph-probe self-tests and integration path. A private re-score of the saved historical responses verifies scoring consistency; no new model inference was performed.

The original defect controls fail on the previous edition. The authentication path is tested against a temporary local HTTP server that returns synthetic responses. Explicit credentials are tested in both successful and error responses, including short values. A successful response that reflects a credential is excluded from scoring and its retained body is redacted.

The public checkout lacks raw historical answers by design. Exact image re-render checks require the original fonts and image-library environment. Git-ignore checks require a real Git checkout. On this host, two partial Content-Length HTTP-body observations remain unverified because bytes are withheld below the application; deterministic response-stream and chunked-loopback tests exercise the repaired client paths separately.

## Reproduce the checks

Use Python with the dependencies in `requirements.txt`. From the repository root in PowerShell:

```powershell
python -B -X utf8 .\tests\test_harness.py --allow-unverified
python -B -X utf8 .\tests\test_r71.py .
python -B -X utf8 .\tests\test_r72.py .
python -B -X utf8 .\tests\test_r73.py .
python -B -X utf8 .\tests\test_ft1_scripted.py .
python -B -X utf8 .\tests\test_unlock_race.py .
python -B -X utf8 .\tests\test_resume_reporting.py .
python -B -X utf8 .\tests\test_r74.py .
python -B -X utf8 .\tests\test_probe_dispatch.py .
```

Run the separate [photo-probe checks](../probe/README.md) as well. An environment that blocks local socket connections cannot establish the loopback checks. Report that execution restriction explicitly; do not mark it as a model or product failure.

Passing synthetic tests does not establish live Studio authentication, local model image capability, photo accuracy, scientific acceptance, or completion of the original study.

## Final public-checkout observation

The root ran `python -B tools/run_checks.py` in the actual publication Git checkout: 249 PASS, zero FAIL, seven UNVERIFIED. C8a, C8b and G41 passed; they had been unavailable in the temporary package copy. This is a distinct run, not a retroactive change to the earlier counts. See `RELEASE-REVIEW.md`.
