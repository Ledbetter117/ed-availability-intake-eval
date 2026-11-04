# Root dispatch contract

Run inference only after FREEZE.json exists and its file hashes verify. `requests.json` is the caller input; it contains the common prompt path/hash, generation settings and ordered requests with opaque request_id, image path and image_sha256. Resolve paths against the simulation directory. Only the prompt text and image bytes enter the model request. Do not attach FREEZE.json, manifest.json, gold/, PLAN.md, file paths or request metadata to the model.

Before the first call save a run identity/settings receipt and the SHA256 of FREEZE.json. Caller must enforce the finite 36-request list. Record actual elapsed time, model identity, endpoint class and effective settings. No credentials belong in observations. The reviewed shared transport can be reused by the root; this package does not open a network connection.

One output file per opaque request ID (or an array in one file):

```json
{"request_id":"opaque identifier from requests.json","outcome":"response","text":"raw model text","finish_reason":"stop","model":"exact identifier","elapsed_s":1.2}
```

Allowed `outcome`: response, transport_error, timeout, refused. For errors, keep `text` empty and optionally add `error_type` without credentials. `finish_reason` must retain the actual API value; length/max_tokens is failure. Root may retain richer sanitized transport records beside this envelope. The scorer accepts only these known IDs, refuses duplicates and unknown IDs, preserves raw input, and records absent IDs as not observed. All actual requests and failures count toward coverage; missing IDs are not silently treated as completed calls.

Offline scoring command: `python -B -X utf8 simulation/score_simulation.py --root simulation --observations OBSERVATIONS.json --out NEW_RESULTS_DIRECTORY`. The output directory must not exist. No model calls occur. Public release includes synthetic gold only after inference is finished; no human-private data is present.
