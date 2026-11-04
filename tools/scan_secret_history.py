"""Fail-closed, read-only full-ref history scan. Not proof of absence of secrets."""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib

DIAGNOSTIC_ERROR = re.compile(r'(?im)(?:\bfatal\b|\bERR\b|\bFTL\b|\berror\s*=|stderr is not empty)')

def exception_review_expiry(config_text, today=None):
    """Exceptions expire at the start of expires_on (UTC). Missing metadata refuses."""
    data = tomllib.loads(config_text)
    review = data.get('release_review')
    if not isinstance(review, dict) or not isinstance(review.get('expires_on'), str):
        raise ValueError('missing_exception_review_expiry')
    expires = date.fromisoformat(review['expires_on'])
    if (today or datetime.now(timezone.utc).date()) >= expires:
        raise ValueError('exception_review_expired')
    return expires.isoformat()

def assess_scan(returncode, text, findings, reachable_commits):
    """Do not trust scanner exit zero alone; keep coverage counts distinct."""
    counts = re.findall(r'\b(\d+) commits? scanned\.', text)
    bytes_seen = re.findall(r'scanned\s+~?([\d.,]+)\s+bytes\b', text)
    terminal = bool(re.search(r'\b(?:no leaks found|leaks found:\s*\d+)\b', text))
    errors = []
    if returncode != 0:
        errors.append('scanner_nonzero_exit')
    if DIAGNOSTIC_ERROR.search(text):
        errors.append('scanner_diagnostic_error')
    if not isinstance(findings, list):
        errors.append('missing_or_invalid_json_report')
    elif findings:
        errors.append('secret_findings')
    if not counts or not bytes_seen or not terminal:
        errors.append('missing_scan_completion_metadata')
    scanned = int(counts[-1]) if counts else None
    if reachable_commits > 0 and (scanned is None or scanned == 0):
        errors.append('no_commits_scanned')
    return {'pass': not errors, 'errors': errors, 'scanner_exit': returncode,
            'findings_count': len(findings) if isinstance(findings, list) else None,
            'coverage': {'reachable_commits': reachable_commits, 'scanner_commits_scanned': scanned,
                         'scanner_bytes': bytes_seen[-1] if bytes_seen else None,
                         'completion_marker': terminal,
                         'count_note': 'Reachable commits and scanned patch commits can differ for merges, empty diffs or binary-only changes; equality is not asserted. Git patch scanning does not inspect all historical binary contents.'}}

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('repo', type=Path)
    ap.add_argument('--gitleaks', required=True, type=Path)
    ap.add_argument('--config', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--expected-head')
    ap.add_argument('--timeout', type=int, default=120)
    args = ap.parse_args(argv)
    repo, config, out = args.repo.resolve(), args.config.resolve(), args.out.resolve()
    if args.timeout <= 0:
        ap.error('--timeout must be positive')
    if out.exists() or out.with_suffix('.log').exists():
        raise SystemExit('REFUSED: evidence output already exists; choose a new path')
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', NO_COLOR='1')
    # An explicit config and empty ignore file defeat implicit per-repo/env overrides.
    env.pop('GITLEAKS_CONFIG', None)
    env.pop('GITLEAKS_CONFIG_TOML', None)
    def git(*items):
        p = subprocess.run(['git', '-C', str(repo), *items], capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=args.timeout, env=env)
        if p.returncode or p.stderr.strip():
            raise RuntimeError('git_metadata_query_failed')
        return p.stdout.strip()
    def snapshot():
        return {'head': git('rev-parse', 'HEAD'),
                'refs': git('for-each-ref', '--format=%(refname) %(objectname)').splitlines(),
                'reachable_commits': int(git('rev-list', '--all', '--count')),
                'nonmerge_commits': int(git('rev-list', '--all', '--no-merges', '--count'))}
    def clean(text):
        for p, label in [(repo, '<repo>'), (out.parent, '<evidence>'), (Path.home(), '<home>')]:
            for name in [str(p), p.as_posix()]:
                text = text.replace(name, label)
        return text
    result = {'schema': 'secret-history-scan/1', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'all local Git refs; historical Git patches, not untracked files or remote refs not fetched',
              'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
              'flags': ['--log-opts=--all', '--redact=100', '--ignore-gitleaks-allow',
                        '--gitleaks-ignore-path=<empty-file>', '--max-archive-depth=3'],
              'pass': False}
    text = ''
    try:
        result['exception_review_expires_on_utc'] = exception_review_expiry(config.read_text(encoding='utf-8'))
        before = snapshot(); result['git_before'] = before
        if args.expected_head and before['head'] != args.expected_head:
            raise RuntimeError('unexpected_head')
        ver = subprocess.run([str(args.gitleaks.resolve()), 'version'], capture_output=True,
                             text=True, timeout=args.timeout, env=env)
        if ver.returncode:
            raise RuntimeError('scanner_version_query_failed')
        result['scanner_version'] = ver.stdout.strip()
        with tempfile.TemporaryDirectory(prefix='gitleaks-private-', dir=out.parent) as temp:
            raw = Path(temp)/'redacted.json'
            empty_ignore = Path(temp)/'empty.ignore'; empty_ignore.write_text('', encoding='utf-8')
            command = [str(args.gitleaks.resolve()), 'git', str(repo), '--log-opts=--all',
                       '--config='+str(config), '--redact=100', '--ignore-gitleaks-allow',
                       '--gitleaks-ignore-path='+str(empty_ignore), '--max-archive-depth=3',
                       '--no-banner', '--no-color', '--report-format=json', '--report-path='+str(raw),
                       '--timeout='+str(args.timeout)]
            p = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                               timeout=args.timeout+10, env=env)
            text = p.stdout+'\n'+p.stderr
            try:
                findings = json.loads(raw.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                findings = None
            result.update(assess_scan(p.returncode, text, findings, before['reachable_commits']))
            # Preserve diagnostics and finding locations; omit matches, secrets, author/email/message.
            result['findings'] = [{k: f.get(k) for k in ['RuleID', 'File', 'StartLine', 'EndLine', 'Commit', 'Fingerprint']}
                                  for f in findings] if isinstance(findings, list) else None
        after = snapshot(); result['git_after'] = after
        result['git_stable'] = before == after
        if before != after:
            result['errors'].append('git_refs_changed_during_scan'); result['pass'] = False
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        result['pass'] = False
        result['errors'] = result.get('errors', []) + [type(exc).__name__]
        # Do not print exception strings: third-party arguments/output may contain private paths.
    out.with_suffix('.log').write_text(clean(text), encoding='utf-8')
    out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'pass': result['pass'], 'errors': result.get('errors', []),
                      'findings_count': result.get('findings_count'), 'coverage': result.get('coverage')}))
    return 0 if result['pass'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
