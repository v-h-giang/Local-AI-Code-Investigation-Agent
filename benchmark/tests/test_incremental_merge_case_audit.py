"""Tests for saved P1.9 per-case evidence coverage audit."""
import copy
import unittest

from benchmark.incremental_merge_case_audit import inspect


class IncrementalMergeCaseAuditTests(unittest.TestCase):
    @staticmethod
    def report():
        def row(ids, chars=400):
            return {
                "gold_citable_ids": ids,
                "serialized_chars": chars,
                "displayed_source_lines": len(ids),
            }
        return {
            "summary": {
                "case_count": 2,
                "max_chars_per_case": 3000,
                "unbudgeted_union_ceiling": 3,
                "modes": {
                    "merge_balanced": {"gold_spans_citable": 2},
                    "merge_anchored": {"gold_spans_citable": 2},
                },
            },
            "cases": [
                {
                    "id": "case_0013",
                    "gold_union_ceiling_ids": ["E2", "E3"],
                    "modes": {
                        "baseline": row(["E3"]),
                        "adaptive_1": row(["E2"]),
                        "merge_balanced": row(["E2"]),
                        "merge_anchored": row(["E3"]),
                    },
                },
                {
                    "id": "case_0016",
                    "gold_union_ceiling_ids": ["E2"],
                    "modes": {
                        "baseline": row(["E2"]),
                        "adaptive_1": row([]),
                        "merge_balanced": row(["E2"]),
                        "merge_anchored": row(["E2"]),
                    },
                },
            ],
        }

    def test_reports_separate_baseline_and_adaptive_losses(self):
        output = inspect(self.report())
        self.assertEqual(output["summary"]["union_ceiling_gold_spans"], 3)
        self.assertEqual(
            output["summary"]["cases_with_any_merge_baseline_loss"],
            ["case_0013"],
        )
        self.assertEqual(
            output["summary"]["merges"]["merge_anchored"]["cases_with_baseline_losses"],
            0,
        )
        case = output["focus_cases"][0]
        self.assertEqual(case["merges"]["merge_balanced"]["lost_vs_baseline"], ["E3"])
        self.assertEqual(case["merges"]["merge_anchored"]["missing_union"], ["E2"])

    def test_rejects_union_mismatch(self):
        report = self.report()
        report["cases"][0]["gold_union_ceiling_ids"] = ["E2"]
        with self.assertRaises(ValueError):
            inspect(report)

    def test_rejects_exceeded_budget(self):
        report = self.report()
        report["cases"][0]["modes"]["merge_balanced"]["serialized_chars"] = 3001
        with self.assertRaises(ValueError):
            inspect(report)

    def test_rejects_duplicate_ids(self):
        report = self.report()
        report["cases"][1]["id"] = "case_0013"
        with self.assertRaises(ValueError):
            inspect(report)


if __name__ == "__main__":
    unittest.main()
