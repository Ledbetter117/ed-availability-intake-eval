# Public release policy

Public work should make its contribution, evidence and limits easy to inspect.
This policy covers professional presentation, privacy, software security and the
exact files delivered to readers. It is not a guarantee of zero risk.

Before a public change:

1. Review factual claims, credentials, attribution, denominators, uncertainty and
   the boundary between software tests and empirical results. Preserve adverse
   findings. Describe achievements directly without claiming unmeasured safety.
2. Inspect source, generated documents/images, metadata, relevant history and
   release downloads for sensitive information, secrets, unsafe behavior and
   licensing problems. Inspect applicable dependency advisories and workflows.
3. Run software checks and the release guard, including deliberately failing
   controls. A missing parser, unsupported binary, stale exception, changed
   reviewed file or missing review record must not count as a clean result.
4. Obtain a separate substantive review of the exact candidate. Record reviewer
   arrangement and limitations in `.public-release-review.json`. The file hashes
   bind that review to the content; they do not prove the review was correct.
5. Check the staged change and publish only under existing authority. Retrieve
   the public result and compare it with the reviewed source and assets.

## Running checks

```text
python -m pip install -r requirements-guard.txt
python -B -m unittest discover -s tools -p test_public_release_guard.py
python -B tools/public_release_guard.py --index
```

The CI workflow runs the committed version and a checksum-pinned Gitleaks scan
of fetched history. The wrapper rejects scanner diagnostic errors even when
the scanner returns exit zero. Reachable commits and scanned patch counts are
reported separately; a zero exit alone is not coverage evidence.
Dependency alerts and private vulnerability reporting are
separate repository settings, not implied by a passing workflow. Review and
refresh parser/scanner pins and dependency advisories when updates are proposed.

`--inventory` prints current hashes for preparing a review record. It does not
approve anything. `--no-review` is diagnostic only and cannot authorize release.
Do not regenerate a review receipt merely to silence a failed check. Changed
bytes require the affected substantive checks and a new accountable review.

The integrity manifest is checked separately to avoid a circular hash with the
review receipt. Its presence is itself bound by the receipt. Content exceptions must
name an exact path, rule, SHA-256, reason and expiry; broad exclusions are not
permitted. History-scanner exceptions instead bind an exact synthetic value and
exact path together, with a review expiry, because historical file contents can
differ. The scanner configuration is itself bound by the review receipt. An
unrelated secret in that same file must remain detectable. Sensitive evidence
belongs outside public Git.

## Boundaries and response

Automated checks cover supported text, PDF objects/text, image metadata and
workflow structure. Visual review remains necessary. Fonts require recorded
source/license review. Archives and unsupported formats need a separately
reviewed export. Repository settings, external sites, old downloads, rights and
contextual claims require additional inspection.

Serious security or privacy findings stop the affected release until repaired
or effectively contained. Ordinary wording polish should not become an endless
delivery gate. Use `SECURITY.md` to report vulnerabilities privately. Preserve
corrections and prior evidence; do not rewrite history or claim a retrospective
pass. If credentials are exposed, revocation/rotation comes before treating a
deletion as remediation.
