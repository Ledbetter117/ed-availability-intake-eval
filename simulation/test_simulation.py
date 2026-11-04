"""Synthetic test controls, never empirical observations."""
import copy
import json
from pathlib import Path
import random
import tempfile
import unittest

import build_simulation as build
import score_simulation as score


def observed(gold, finish="stop"):
    return {"outcome": "response", "text": json.dumps(gold), "finish_reason": finish}


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.gold = build.truth(2028, 2, random.Random(4))

    def test_month_lengths_and_required_content(self):
        for year, month, days in [(2027, 2, 28), (2028, 2, 29), (2028, 4, 30), (2028, 1, 31)]:
            gold = build.truth(year, month, random.Random(4))
            self.assertEqual(len(gold["days"]), days)
            self.assertEqual({x["status"] for x in gold["days"].values()}, score.STATUSES)
            self.assertEqual(sum(bool(x["note"]) for x in gold["days"].values()), 5)
            score.valid_prediction(gold)
            self.assertTrue(score.score_one(gold, observed(gold))["calendar_exact"])

    def test_all_single_status_mutations_and_note_omissions_detected(self):
        for date in self.gold["days"]:
            mutated = copy.deepcopy(self.gold)
            old = mutated["days"][date]["status"]
            mutated["days"][date]["status"] = "AVAILABLE" if old != "AVAILABLE" else "UNAVAILABLE"
            result = score.score_one(self.gold, observed(mutated))
            self.assertFalse(result["calendar_exact"])
            self.assertEqual(result["status_correct"], 28)
        for date, cell in self.gold["days"].items():
            if cell["note"]:
                mutated = copy.deepcopy(self.gold)
                mutated["days"][date]["note"] = ""
                result = score.score_one(self.gold, observed(mutated))
                self.assertFalse(result["calendar_exact"])
                self.assertEqual(result["nonempty_note_correct"], 4)

    def test_blank_is_not_available_and_critical_flip(self):
        for target, flip in [("NOT_SPECIFIED", 0), ("UNAVAILABLE", 1)]:
            mutated = copy.deepcopy(self.gold)
            date = next(d for d, cell in self.gold["days"].items() if cell["status"] == target)
            mutated["days"][date]["status"] = "AVAILABLE"
            result = score.score_one(self.gold, observed(mutated))
            self.assertFalse(result["calendar_exact"])
            self.assertEqual(result["critical_flips"], flip)

    def test_strict_notes_case_spaces_global_order(self):
        for mutate in (lambda g: g["global_notes"].reverse(),
                       lambda g: g["days"][next(iter(g["days"]))].update(note=" "),
                       lambda g: g["days"][next(d for d in g["days"] if g["days"][d]["note"])].update(note="invented")):
            mutated = copy.deepcopy(self.gold)
            mutate(mutated)
            self.assertFalse(score.score_one(self.gold, observed(mutated))["calendar_exact"])

    def test_failed_missing_truncated_unknown_finish_have_no_safe_zero_claim(self):
        examples = [None, {"outcome": "timeout"}, observed(self.gold, "length"), observed(self.gold, "unknown")]
        for item in examples:
            result = score.score_one(self.gold, item)
            self.assertFalse(result["calendar_exact"])
            self.assertEqual(result["status_correct"], 0)
            self.assertIsNone(result["critical_flips"])

    def test_impossible_date_missing_date_and_bad_status_rejected(self):
        for mutate in (lambda g: g["days"].update({"2028-02-30": {"status": "AM", "note": ""}}),
                       lambda g: g["days"].pop("2028-02-29"),
                       lambda g: g["days"]["2028-02-01"].update(status="MAYBE"),
                       lambda g: g.update(extra=True),
                       lambda g: g.update(global_notes="no call")):
            mutated = copy.deepcopy(self.gold)
            mutate(mutated)
            result = score.score_one(self.gold, observed(mutated))
            self.assertFalse(result["schema_valid"])
            self.assertEqual(result["status_correct"], 0)

    def test_wrong_valid_month_is_failure(self):
        other = build.truth(2028, 3, random.Random(4))
        result = score.score_one(self.gold, observed(other))
        self.assertTrue(result["schema_valid"])
        self.assertEqual(result["failure"], "wrong_month")
        self.assertEqual(result["note_correct"], 0)

    def test_duplicate_keys_nonfinite_fences_and_huge_response(self):
        for text in ['{"a":1,"a":2}', '{"a":NaN}', '```json\n{}\n```', 'x' * (1024 * 1024 + 1)]:
            with self.assertRaises(ValueError):
                score.strict_json(text)

    def test_unknown_duplicate_observations_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "obs.json"
            item = {"request_id": "one", **observed(self.gold)}
            for value in ([item, item], [{**item, "request_id": "unknown"}]):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(ValueError):
                    score.load_observations(path, {"one"})

    def test_cluster_intervals_and_pairing_extremes(self):
        self.assertLess(score.wilson(0, 12)[1], 0.25)
        self.assertGreater(score.wilson(12, 12)[0], 0.75)
        result = score.paired_summary([-1] * 6 + [0] * 6)
        self.assertEqual(result["n_calendars"], 12)
        self.assertEqual(result["mean_difference"], -0.5)
        self.assertLess(result["bootstrap_95_percentile"][0], -0.5)
        self.assertGreater(result["bootstrap_95_percentile"][1], -0.5)
        self.assertTrue(score.paired_summary([0] * 12)["degenerate"])

    def test_frozen_file_tampering_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "x.txt"
            payload.write_text("original", encoding="utf-8")
            (root / "FREEZE.json").write_text(json.dumps({"files": [{"path": "x.txt", "sha256": score.sha(payload)}]}), encoding="utf-8")
            score.verify_freeze(root)
            payload.write_text("changed", encoding="utf-8")
            with self.assertRaises(ValueError):
                score.verify_freeze(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
