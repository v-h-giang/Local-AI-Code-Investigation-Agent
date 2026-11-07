"""P1.14 saved-control accounting and provenance diagnostic tests."""
import copy
import unittest

from benchmark.structure_packing_ablation import MODE, CONTROLS, _aggregate


def fixture():
    def old(ids, full=()):
        return {'gold_any_line_ids': list(ids),
                'gold_complete_span_ids': list(full)}
    def new(ids, full=()):
        return {**old(ids, full), 'serialized_chars': 980,
                'displayed_source_lines': 12, 'isolated_source_lines': 0,
                'selected_blocks': 1, 'candidate_blocks': 4}
    rows = [
        {'id': 't1', 'gold_span_count': 2,
         'controls': {'baseline': old(['E1']), 'adaptive_1': old(['E2']),
                      'merge_balanced_1': old(['E1']),
                      'merge_anchored_1': old(['E1', 'E2'])},
         'structure': new(['E1', 'E2'], ['E1'])},
        {'id': 't2', 'gold_span_count': 1,
         'controls': {'baseline': old(['E3']), 'adaptive_1': old(['E3']),
                      'merge_balanced_1': old(['E3']),
                      'merge_anchored_1': old(['E3'])},
         'structure': new([])},
    ]
    prior = {'summary': {'case_count': 2, 'gold_spans_total': 3,
             'modes': {key: {'gold_spans_any_line': sum(
                  len(row['controls'][key]['gold_any_line_ids']) for row in rows)}
                       for key in CONTROLS}}}
    return rows, prior


class PackingAblationTests(unittest.TestCase):
    def test_aggregate_preserves_controls_and_counting(self):
        rows, prior = fixture()
        report = _aggregate(rows, prior)
        self.assertEqual(report[MODE]['gold_spans_any_line'], 2)
        self.assertEqual(report[MODE]['gold_spans_complete'], 1)
        self.assertEqual(report[MODE]['gross_gains_vs_baseline'], 1)
        self.assertEqual(report[MODE]['gross_losses_vs_baseline'], 1)
        self.assertEqual(report[MODE]['gross_losses_vs_anchored_1'], 1)
        self.assertEqual(report[MODE]['isolated_source_lines'], 0)
        self.assertEqual(report[MODE]['coverage_any_line'], 0.6667)
        self.assertTrue(report['controls_identical_to_saved_p11'])

    def test_aggregate_detects_control_mismatch(self):
        rows, prior = fixture()
        prior['summary']['modes']['baseline']['gold_spans_any_line'] += 1
        with self.assertRaises(ValueError):
            _aggregate(rows, prior)

    def test_aggregate_detects_span_mismatch(self):
        rows, prior = fixture()
        rows[0]['structure']['gold_complete_span_ids'] = ['E3']
        with self.assertRaises(ValueError):
            _aggregate(rows, prior)

    def test_aggregate_rejects_duplicate_refs(self):
        rows, prior = fixture()
        rows[0]['structure']['gold_any_line_ids'] = ['E1', 'E1']
        with self.assertRaises(ValueError):
            _aggregate(rows, prior)

    def test_aggregate_rejects_incorrect_case_count(self):
        rows, prior = fixture()
        prior['summary']['case_count'] = 3
        with self.assertRaises(ValueError):
            _aggregate(rows, prior)


if __name__ == '__main__':
    unittest.main()
