"""Tests for saved P1.7 evidence change accounting."""
import unittest

from benchmark.context_budget_case_diagnostics import diagnose


def entry(ids, *, chars=200, lines=3, dense=0):
    return {
        'gold_citable_ids': sorted(ids),
        'gold_visible_ids': sorted(ids),
        'gold_spans_citable': len(ids),
        'serialized_chars': chars,
        'displayed_source_lines': lines,
        'selected_dense_alternates': dense,
    }


def fixture():
    cases = [
        {'id': 'c1', 'modes': {
            'baseline': entry(['A']),
            'adaptive_0': entry(['A','B'], chars=180),
            'adaptive_1': entry(['A','B'], chars=190, dense=1),
            'adaptive_2': entry(['A','B'], chars=195, dense=2),
        }},
        {'id': 'c2', 'modes': {
            'baseline': entry(['C']),
            'adaptive_0': entry([], chars=160),
            'adaptive_1': entry(['D'], chars=175, dense=1),
            'adaptive_2': entry(['C'], chars=185, dense=2),
        }},
    ]
    modes = {key: {
        field: sum(case['modes'][key][field] for case in cases)
        for field in ('gold_spans_citable','serialized_chars',
                      'displayed_source_lines','selected_dense_alternates')}
        for key in ('baseline','adaptive_0','adaptive_1','adaptive_2')}
    return {'summary': {'case_count': 2,'max_chars_per_case':3000,'modes':modes},
            'cases':cases}


class ContextBudgetCaseDiagnosticsTests(unittest.TestCase):
    def test_gross_changes_do_not_cancel_in_diagnostics(self):
        result = diagnose(fixture())
        summary = result['summary']
        delta = summary['comparisons']['adaptive_1_vs_baseline']
        self.assertEqual(delta['gross_gold_span_gains'], 2)
        self.assertEqual(delta['gross_gold_span_losses'], 1)
        self.assertEqual(delta['net_gold_span_change'], 1)
        self.assertEqual(delta['cases_gaining_gold'], 2)
        self.assertEqual(delta['cases_losing_gold'], 1)
        self.assertEqual(summary['changed_case_ids'], ['c1', 'c2'])

    def test_incremental_comparisons_not_confused_with_baseline(self):
        result = diagnose(fixture())
        delta = result['summary']['comparisons']['adaptive_1_vs_adaptive_0']
        self.assertEqual(delta['gross_gold_span_gains'], 1)
        self.assertEqual(delta['gross_gold_span_losses'], 0)
        self.assertEqual(delta['net_gold_span_change'], 1)
        delta2 = result['summary']['comparisons']['adaptive_2_vs_adaptive_1']
        self.assertEqual(delta2['gross_gold_span_gains'], 1)
        self.assertEqual(delta2['gross_gold_span_losses'], 1)
        self.assertEqual(delta2['net_gold_span_change'], 0)

    def test_rejects_invalid_refs(self):
        report = fixture()
        report['cases'][0]['modes']['adaptive_1']['gold_visible_ids'] = []
        with self.assertRaises(ValueError):
            diagnose(report)

    def test_rejects_summary_mismatch(self):
        report = fixture()
        report['summary']['modes']['adaptive_1']['serialized_chars'] += 10
        with self.assertRaises(ValueError):
            diagnose(report)

    def test_rejects_budget_overrun(self):
        report = fixture()
        report['cases'][0]['modes']['adaptive_1']['serialized_chars'] = 3001
        with self.assertRaises(ValueError):
            diagnose(report)


if __name__ == '__main__':
    unittest.main()
