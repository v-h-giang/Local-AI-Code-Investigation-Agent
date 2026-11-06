"""Regression tests for read-only multiwindow budget replay."""
import unittest

from benchmark.multiwindow_budget_ablation import evaluate_case, analyze


class MultiwindowBudgetAblationTests(unittest.TestCase):
    def fixture(self):
        question='How does retry middleware work?'
        source={'id':'test_0001','suite':'repocontextbench',
                'question':question,'gold_spans':[
                    {'id':'E1','path':'src/a.py','start_line':3,'end_line':7},
                    {'id':'E2','path':'src/a.py','start_line':73,'end_line':78},
                    {'id':'E3','path':'src/a.py','start_line':120,'end_line':122}]}
        saved={'id':'test_0001','question':question,
               'variants':{'hybrid':{'top8_diagnostics':[
                   {'path':'src/a.py','line_start':1,'line_end':20}]}},
               'multiwindow_diagnostics':{'alternates':[
                   {'path':'src/a.py','start_line':70,'end_line':85,
                    'new_lines':16},
                   {'path':'src/a.py','start_line':115,'end_line':130,
                    'new_lines':16},
                   {'path':'src/a.py','start_line':145,'end_line':160,
                    'new_lines':16},
                   {'path':'src/a.py','start_line':170,'end_line':185,
                    'new_lines':16},
               ],'augmented_top8_window_span_ids':['E1','E2','E3']}}
        return saved,source

    def test_each_prefix_counts_actual_new_spans(self):
        saved,source=self.fixture()
        result=evaluate_case(saved,source)['by_budget']
        self.assertEqual([result[str(i)]['gold_span_window_hits']
                          for i in range(5)],[1,2,3,3,3])
        self.assertEqual([result[str(i)]['extra_source_lines']
                          for i in range(5)],[0,16,32,48,64])
        self.assertEqual(result['2']['new_gold_span_ids'],['E2','E3'])

    def test_aggregate_marginal_yield_and_budget(self):
        saved,source=self.fixture()
        report={'suite':'repocontextbench','cases':[saved]}
        result=analyze(report,[source])['summary']
        self.assertEqual(result['budgets']['2']['new_gold_spans_vs_baseline'],2)
        self.assertEqual(result['budgets']['4']['extra_windows'],4)
        self.assertEqual(result['marginal']['1']['new_gold_spans_at_this_window'],1)
        self.assertEqual(result['marginal']['3']['new_gold_spans_at_this_window'],0)
        self.assertEqual(result['budgets']['4']['source_lines_per_new_gold_span'],32.0)

    def test_rejects_alternate_outside_top8(self):
        saved,source=self.fixture()
        saved['multiwindow_diagnostics']['alternates'][0]['path']='src/else.py'
        with self.assertRaises(ValueError):
            evaluate_case(saved,source)

    def test_rejects_untruthful_source_line_cost(self):
        saved,source=self.fixture()
        saved['multiwindow_diagnostics']['alternates'][1]['new_lines']=17
        with self.assertRaises(ValueError):
            evaluate_case(saved,source)


if __name__=='__main__':
    unittest.main()
