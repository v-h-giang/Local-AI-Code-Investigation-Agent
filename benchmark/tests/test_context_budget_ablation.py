"""A/B accounting tests for P1.7 against synthetic source."""
import json
import unittest

from benchmark.context_budget_ablation import analyze, verify_previous_ablation
from benchmark.tests import test_context_budget_selector as fixtures


class ContextBudgetAblationTests(unittest.TestCase):
    def test_modes_share_character_budget(self):
        saved = fixtures.ContextBudgetSelectorTests.saved()
        source = {'id':'demo','suite':'repocontextbench',
                  'question':saved['question'],
                  'gold_spans':[{'id':'E1','path':'src/engine.py',
                                 'start_line':75,'end_line':77}]}
        report=analyze({'suite':'repocontextbench','cases':[saved]},
                       [source],fixtures.DemoRepo(),max_chars=3000,
                       fixed_window_chars=500,limit=6)
        modes=report['summary']['modes']
        self.assertEqual(set(modes),{
            'baseline','fixed_1','fixed_2',
            'adaptive_0','adaptive_1','adaptive_2'})
        for key,row in modes.items():
            self.assertLessEqual(row['serialized_chars'],3000,key)
            self.assertEqual(row['gold_spans_citable'],row['gold_spans_visible'])
        self.assertEqual(modes['baseline']['selected_dense_alternates'],0)
        self.assertEqual(report['summary']['gold_spans_total'],1)

    def test_previous_ablation_controls_must_match(self):
        saved=fixtures.ContextBudgetSelectorTests.saved()
        source={'id':'demo','suite':'repocontextbench',
                'question':saved['question'],'gold_spans':[]}
        current=analyze({'suite':'repocontextbench','cases':[saved]},
                        [source],fixtures.DemoRepo())
        current['suite']='repocontextbench'
        controls={'baseline':'0','fixed_1':'1','fixed_2':'2'}
        reference={'suite':'repocontextbench','cases':[{
            'id':'demo','variants':{
                old:{field: current['cases'][0]['modes'][mode][field]
                     for field in ('gold_visible_ids','gold_citable_ids',
                                   'serialized_chars')}
                for mode,old in controls.items()}}]}
        self.assertTrue(verify_previous_ablation(reference,current)
                        ['controls_identical_to_p16'])
        reference['cases'][0]['variants']['0']['serialized_chars']+=1
        with self.assertRaises(ValueError):
            verify_previous_ablation(reference,current)

    def test_rejects_unknown_case(self):
        saved=fixtures.ContextBudgetSelectorTests.saved()
        with self.assertRaises(ValueError):
            analyze({'suite':'repocontextbench','cases':[saved]},
                    [],fixtures.DemoRepo())


if __name__=='__main__':
    unittest.main()
