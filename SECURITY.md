# Security and privacy boundaries

Report a suspected vulnerability through [GitHub private vulnerability reporting](https://github.com/Ledbetter117/ed-availability-intake-eval/security/advisories/new). Do not place real credentials, photographs, schedules, or raw model responses in a public issue. Include the affected commit and a synthetic reproducer when possible.

The current source branch receives fixes. Historical tags preserve the original evidence and can contain known defects or outdated dependencies. Use the current patched requirements with Python 3.11 or later. Dependency scans identify known published advisories; they do not establish that a package has no vulnerabilities. The original rendering environment is not the supported environment for opening new files.

If using the optional PDF renderer, install it with `pip install -r requirements.txt reportlab` in the same environment so its Pillow dependency uses the patched project constraint. The existing paper PDF was not regenerated during the security repair.

This is local evaluation software, not a service for accepting arbitrary uploads. Run it in a directory you control. Configuration, gold labels, manifests, source code and replay folders are trusted operator inputs. Do not execute code or open replay packages from an unreviewed source. No archive unpacker, model-weight loader or shell-command interpreter is provided by the evaluation. Filesystem hashes detect drift, not a hostile party able to replace both code and manifest. There is no protection against another process that can change your files while a run is active.

Real photo probes accept JPEG and PNG content only, with a 32 MiB input limit and a 40-million-pixel limit before full decoding. Private photo mappings must name files within the selected photo folder; external linked paths are refused. Document and arm IDs cannot contain output paths. Keep the image decoder updated even with these checks.

The HTTP transports refuse redirects and environment proxies, enforce their configured destinations, and limit a response body to 16 MiB. Model responses are parsed as data and never executed. Explicit request credentials are scrubbed from errors and retained response content; a credential echoed by a successful response makes that response unavailable for scoring. This catches literal credential values, not every possible encoded or transformed secret. Do not put secrets into prompts, notes, model names or configuration text.

Private photographs are sent only to a validated local vision route. Authenticated local endpoints must be on loopback. A separately trusted private-IP endpoint is still another computer: its operator can see the inputs. Confirm its ownership before use. Loopback routing does not establish that the local model service itself has no telemetry.

Photo probe output includes raw model transcriptions and can contain private document text. Keep photos, intended labels, private maps, raw answers, and probe output outside public exports. `.gitignore` is a convenience, not a security boundary: inspect the exact staged files before publication. This public repository contains generated calendars and aggregate historical results; real photo endpoints remain unfinished.
