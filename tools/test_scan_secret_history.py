"""Focused negative controls for the scanner's exit/diagnostic boundary."""
import unittest
from datetime import date
from scan_secret_history import assess_scan, exception_review_expiry

CLEAN = 'INF 11 commits scanned.\nINF scanned ~948813 bytes (948.81 KB) in 200ms\nINF no leaks found\n'

class ScannerResultControls(unittest.TestCase):
    def test_clean_completion(self):
        self.assertTrue(assess_scan(0, CLEAN, [], 13)['pass'])
    def test_zero_exit_fatal_is_failure(self):
        r = assess_scan(0, 'ERR [git] fatal: unable to read files to diff\nERR error="stderr is not empty"\n'+CLEAN, [], 13)
        self.assertFalse(r['pass']); self.assertIn('scanner_diagnostic_error', r['errors'])
    def test_each_diagnostic_marker_fails(self):
        for prefix in ['fatal: failed', 'ERR failed', 'FTL failed', 'error="failed"', 'stderr is not empty']:
            with self.subTest(prefix=prefix):
                self.assertFalse(assess_scan(0, prefix+'\n'+CLEAN, [], 13)['pass'])
    def test_known_leak_fails(self):
        r = assess_scan(1, CLEAN.replace('no leaks found', 'leaks found: 1'), [{'RuleID': 'synthetic-test'}], 13)
        self.assertFalse(r['pass']); self.assertIn('secret_findings', r['errors'])
    def test_missing_completion_or_report_fails(self):
        self.assertFalse(assess_scan(0, '', [], 13)['pass'])
        self.assertFalse(assess_scan(0, CLEAN, None, 13)['pass'])
    def test_zeroexit_findings_still_fail(self):
        self.assertFalse(assess_scan(0, CLEAN, [{}], 13)['pass'])
    def test_exception_expiry_is_enforced(self):
        config = '[release_review]\nexpires_on = "2027-02-01"\n'
        self.assertEqual(exception_review_expiry(config, date(2027, 1, 31)), '2027-02-01')
        with self.assertRaises(ValueError):
            exception_review_expiry(config, date(2027, 2, 1))
        with self.assertRaises(ValueError):
            exception_review_expiry('[extend]\nuseDefault = true\n', date(2026, 11, 3))

if __name__ == '__main__':
    unittest.main()
