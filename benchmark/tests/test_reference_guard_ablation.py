"""P1.8 accounting and control replay tests with synthetic pinned-style source."""
import unittest

from benchmark.reference_guard_ablation import analyze, verify_p17
from benchmark.context_budget_ablation import analyze as prior_analyze
from benchmark.tests.test_context_budget_selector import (
    ContextBudgetSelectorTests, DemoRepo,
)


class ReferenceGuardAblationTests(unittest.TestCase):
    def fixture(self):
        saved = ContextBudgetSelectorTests.saved()
        gold_case = {'id': saved['id'], 'suite':'repocontextbench',
                     'question': saved['question'], 'gold_spans':[
                         {'id':'E1', 'path':'src/engine.py',
                          'start_line':75,'end_line':77}]}
        return {'suite':'repocontextbench','cases':[saved]}, [gold_case]

    def test_modes_respect_equal_budget_and_gold_accounting(self):
        saved, gold = self.fixture()
        output = analyze(saved,gold,DemoRepo(),max_chars=3000,limit=6)
        modes = output['summary']['modes']
        self.assertEqual(set(modes), {
            'baseline','adaptive_1','guard_critical','guard_query'})
        self.assertEqual(output['summary']['gold_spans_total'],1)
        for m in modes.values():
            self.assertLessEqual(m['serialized_chars'],3000)
            self.assertEqual(m['gross_losses_vs_baseline'],0)

    def test_controls_match_p17_existing_selector(self):
        saved, gold = self.fixture()
        previous = prior_analyze(saved,gold,DemoRepo(),max_chars=3000,limit=6)
        previous['suite']='repocontextbench'
        current = analyze(saved,gold,DemoRepo(),max_chars=3000,limit=6)
        current['suite']='repocontextbench'
        self.assertTrue(verify_p17(previous,current)['controls_identical_to_p17'])
        previous['cases'][0]['modes']['baseline']['serialized_chars'] += 1
        with self.assertRaises(ValueError):
            verify_p17(previous,current)

    def test_unknown_case_rejected(self):
        saved,_ = self.fixture()
        with self.assertRaises(ValueError):
            analyze(saved, [], DemoRepo())


if __name__ == '__main__':
    unittest.main()
