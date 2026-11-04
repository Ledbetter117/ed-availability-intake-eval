# ED(i) simulation edition

This separate, source-preserving edition evaluates model extraction from fictional calendars rendered with typed text and licensed handwriting fonts. It does not complete the original human handwriting or private-intent study.

`simulation/FREEZE.json` binds the prospective plan, scorer, generated truth, images, fonts and image-only request order. `simulation/requests.json` and `simulation/PROMPT.txt` are the only caller inputs. The model receives prompt text and image bytes only. The pairing manifest and gold are for offline scoring.

Run the tests with Python 3.12 and Pillow 13.0.0: `python -B -X utf8 simulation/test_simulation.py`. Score actual saved responses with `python -B -X utf8 simulation/score_simulation.py --root simulation --observations simulation/results/OBSERVATIONS.json --out NEW_RESULTS_DIRECTORY`. Existing outputs are refused. This scorer never opens a network connection or launches a model.

To reproduce image bytes, copy the frozen source text files and assets into a new empty directory, leaving generated manifest, requests, FREEZE.json, images and gold out of that new directory, then run `build_simulation.py` there. It refuses an existing corpus. Compare generated truth/image/request hashes with the original FREEZE.json; the freeze timestamp itself changes. The original frozen data must remain intact.

Methods and result status are in [the study report](../docs/SIMULATION-STUDY.md); quantity provenance is in `simulation/NUMERICAL-SOURCES.json`. Tests and oracle controls are software evidence, never model performance evidence. The released actual model observations are in simulation/results/OBSERVATIONS.json. All 36 first observations are included; frozen inputs were unchanged. The committed score object is simulation/results/SCORES.json.

Render the written report with `python -m pip install -r simulation/requirements-report.txt`, then `python -B simulation/render_report.py paper/SIMULATION-PILOT.md paper/SIMULATION-PILOT.pdf`. The PNG figure is already included. The original report source and prior release remain in history.
