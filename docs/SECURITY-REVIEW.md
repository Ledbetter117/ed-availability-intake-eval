# Public release repair — 3 November 2026

The review started from published commit `9fad1e497d2f67bb4d63fe9adaca24e886761c6a`. It examined the public software and presentation, using synthetic requests and offline records. No model inference or new photograph scoring was performed.

Verified defects were repaired:

- The legacy runner used the default HTTP opener and could retain a provider's credential echo. It now uses the shared transport with explicit destinations, no redirects or environment proxies, and successful-response reflection rejection. Short explicit credentials are included.
- Successful and error response bodies were unbounded. Both now have a 16 MiB limit; oversized bodies are discarded before parsing or retention.
- Probe photo decoding autodetected formats and lacked practical size limits. It now permits JPEG/PNG content only, limits bytes and pixels, and treats decompression warnings as errors. IDs and private photo mappings cannot provide output paths or override document identity.
- Pillow 10.4.0 was affected by published decoder advisories. The current runtime pins Pillow 13.0.0 and Matplotlib 3.11.2. Python 3.11 or later is required. The original dataset bytes are preserved.
- Actions now use verified full commit identifiers, read-only repository permission, no persisted checkout credential, and job time limits. Dependency advisory checks and Dependabot updates cover the current requirement files.
- Two historical Haiku chart PNGs failed decoding. They were rebuilt from unchanged metrics and CSV records. Both models' slice-difference charts now describe observed contrasts without implying that rendering caused the difference. No result was removed or improved numerically.
- Older analysis text overstated safety, general model performance, causal explanations, and proposed controls. The corrections retain observed counts and identify interpretations and untested proposals. Historical probe text now links its adopted amendment and identifies the later draft. The paper PDF and numerical source records were unchanged.

The full offline run reported 258 PASS, zero FAIL and seven UNVERIFIED across eleven child suites. These are printed test outcomes, including overlapping or nested contracts, not 258 independent experiments. Nine new security tests also fail against the exact original public code and pass after repair. Both probe selftests pass; these use synthetic fixtures and establish no real-photo result.

The unverified checks are `A:results`, `A:results_haiku` and `G38` (private raw responses intentionally absent), `G36` and `G37` (original Linux reference font/render environment absent), and `FT1-A2` and `FT1-B2` (Windows withheld the partial response body from the application). The transport's scripted partial-body controls pass. Expected refusal text printed by fault-control tests is not a failed suite.

The bundled Patrick Hand font passed table parsing and exactly matched [Google Fonts revision 2fe1e8c6](https://github.com/google/fonts/tree/2fe1e8c6b137fb13041a7cfca6fdcd8a910ea4dc/ofl/patrickhand). Its SIL Open Font License notice is retained. This provenance check does not establish that arbitrary fonts are safe.

This review is bounded. Known-advisory scanning does not discover all unknown vulnerabilities. Trusted local files and replay folders are not hostile upload surfaces. Credential scrubbing covers literal echoes, not every encoding or transformation. Historical Git tags remain available and may contain defects fixed in the current source. See [SECURITY.md](../SECURITY.md) for practical boundaries and private reporting.

Primary dependency sources: [Pillow Ghostscript argument injection, patched in 13.0.0](https://github.com/python-pillow/Pillow/security/advisories/GHSA-w889-685w-c8fh), [FITS decompression advisory](https://github.com/python-pillow/Pillow/security/advisories/GHSA-whj4-6x5x-4v2j), and [PSD tile-extent advisory](https://github.com/python-pillow/Pillow/security/advisories/GHSA-pwv6-vv43-88gr). Advisory applicability depends on format and execution path; no successful exploit was demonstrated here.


## Model-response parsing follow-up

Static analysis identified two regular expressions in `parse_json` whose runtime
grew sharply on malformed responses. A long whitespace run or many unmatched
opening braces could delay processing even within the response-size limit.
The parser now removes code fences and locates the outer object with fixed-string
operations. Strict JSON checks and rejection of conflicting duplicate keys remain.

The regression test supplies two malformed 1 MiB responses in isolated processes.
Both exceed the five-second deadline with the previous parser; the repaired parser
finishes both and passes the valid-input and strict-rejection controls. The test is
part of `tools/run_checks.py`. The affected harness also reports 105 passed checks,
zero failures and the same seven unavailable checks described above. These results
support the parser repair; they are not new model or clinical measurements.

Remaining static-analysis path findings were reviewed against the documented local
command-line inputs and existing containment checks. No new boundary-crossing path
was confirmed in those reviewed flows. This is a scoped assessment, not a claim
that every path operation is safe for a hosted service or untrusted operators.
