# Photograph probe tooling

Both original probe arms remain in scope. These scripts prepare and test the pipeline; they do not contain completed real-photo results or confirmed personal intent labels.

The adopted Amendment 01 uses documents as the decision unit and retires CLOSE. Its owner ruling requires local scoring for photographed documents. Amendment 02 is still a draft and must identify the model, runtime, synthetic baseline, and chosen failure rules before real-photo scoring. The historical pre-registration files remain available unchanged; the amendment heading erratum is explicit.

## Run the synthetic checks

From the repository root, in PowerShell:

```powershell
python -B -X utf8 .\probe\probe_decide.py --selftest
python -B -X utf8 .\probe\probe_score.py --selftest
python -B -X utf8 .\probe\probe_b.py --selftest
python -B -X utf8 .\probe\probe_integration_test.py --mmeval-root .
python -B -X utf8 .\tests\test_probe_dispatch.py .
```

These checks use synthetic maps, labels, images, and response doubles. They do not read the author's real photo corpus or call a model.

## Prepare a real run after qualification

1. Record the local model identity and settings, qualify image input on public synthetic data, and freeze the amended protocol before photo scoring. A stored response or a passing mock does not establish live image capability.
2. Configure only local arms with `private_local_only` allowed, `dispatch.enabled: true`, verified image capability, explicit model identity, positive limits, and an optional credential environment-variable name. The selected credential must exist. Authenticated endpoints must be on loopback. No credential belongs in a file or command argument.
3. Keep all photos, mappings, completed intentions, and real-run output outside the public repository. Use a new output directory per run. Existing nonempty output directories are refused.
4. Arm A uses generated copyist references and the author's independently completed intent for authored sheets. It preserves each response attempt. Arm B uses the private document mapping and independently completed intended meanings. Its real baseline must be a complete `mmeval` run containing the same arm identity and all published synthetic trial-one outcomes. Bare historical CSVs remain usable for offline diagnostics, not as proof of a current local arm's identity.
5. Pass `--amendment-02-frozen` only when the recorded and published amendment actually exists. That argument asserts a prerequisite; it does not create a freeze record or prove it.

`configs/arms.local-auth.example.json` is disabled and contains placeholders. It is an example for public synthetic qualification, not a ready private-data run configuration. The project does not ship a model credential, private map, completed personal labels, or model weights.

## Evidence limits

The public generated dataset and copyist specifications are recoverable from code. Blank-day meanings, actual work intentions, behavior coding, and time spent authoring are not established by those generated references. An inferred legend or a model reading cannot be relabeled as the author's intention. Where personal intent is unavailable, the original endpoint remains unmeasured.

Read [release status](../docs/RELEASE-STATUS.md) and [validation](../docs/VALIDATION.md) before reusing this candidate.
