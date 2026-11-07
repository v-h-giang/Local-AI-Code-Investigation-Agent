"""Source-evidence merge A/B accounting and historical-control checks."""
import unittest
from unittest.mock import patch

from benchmark import incremental_merge_ablation as ab
from benchmark.tests.test_incremental_evidence_merge import excerpt


class IncrementalMergeAblationTests(unittest.TestCase):
    def fixture(self):
        base=[excerpt('src/a.py',[(10,'def retry_rate_limit():'),
                                  (11,'    return handle_retry()')])]
        adaptive=[excerpt('src/a.py',[(50,'class RetryRateLimitMiddleware:'),
                                      (51,'    def handle_retry(): return True')])]
        saved={'id':'demo','suite':'repocontextbench',
               'question':'How does rate limit retry work?'}
        gold={'id':'demo','suite':'repocontextbench',
              'question':saved['question'],
              'gold_spans':[
                  {'id':'E1','path':'src/a.py','start_line':10,'end_line':10},
                  {'id':'E2','path':'src/a.py','start_line':50,'end_line':50},
              ]}
        return saved,gold,base,adaptive

    def test_merge_compares_real_line_references(self):
        saved,gold,base,adaptive=self.fixture()
        with patch.object(ab,'acquire_prefetch_variants',return_value={
                '0':{'excerpts':base}}), patch.object(ab,'select_evidence',
                return_value={'excerpts':adaptive}):
            result=ab.evaluate_case(None,saved,gold,max_chars=3000)
        self.assertEqual(result['modes']['baseline']['gold_citable_ids'],['E1'])
        self.assertEqual(result['modes']['adaptive_1']['gold_citable_ids'],['E2'])
        self.assertEqual(result['modes']['merge_balanced']['gold_citable_ids'],['E1','E2'])
        self.assertEqual(result['modes']['merge_anchored']['gold_citable_ids'],['E1','E2'])
        self.assertEqual(result['gold_union_ceiling_ids'],['E1','E2'])

    def test_aggregate_ceiling_and_net_gain(self):
        saved,gold,base,adaptive=self.fixture()
        with patch.object(ab,'acquire_prefetch_variants',return_value={
                '0':{'excerpts':base}}), patch.object(ab,'select_evidence',
                return_value={'excerpts':adaptive}):
            output=ab.analyze({'suite':'repocontextbench','cases':[saved]},
                              [gold],None,max_chars=3000)
        summary=output['summary']
        self.assertEqual(summary['unbudgeted_union_ceiling'],2)
        self.assertEqual(summary['modes']['merge_balanced']['gold_spans_citable'],2)
        self.assertEqual(summary['modes']['merge_anchored']['gross_losses_vs_baseline'],0)
        self.assertLessEqual(summary['modes']['merge_balanced']['serialized_chars'],3000)

    def test_control_verification_detects_divergence(self):
        saved,gold,base,adaptive=self.fixture()
        with patch.object(ab,'acquire_prefetch_variants',return_value={
                '0':{'excerpts':base}}), patch.object(ab,'select_evidence',
                return_value={'excerpts':adaptive}):
            current=ab.analyze({'suite':'repocontextbench','cases':[saved]},
                               [gold],None)
        current['suite']='repocontextbench'
        previous={'suite':'repocontextbench','cases':[{'id':'demo','modes':{
            mode:{key:current['cases'][0]['modes'][mode][key] for key in (
                'gold_citable_ids','serialized_chars','displayed_source_lines')}
            for mode in ('baseline','adaptive_1')}}]}
        self.assertTrue(ab.verify_p18_control(previous,current)['controls_identical_to_p18'])
        previous['cases'][0]['modes']['adaptive_1']['serialized_chars']+=1
        with self.assertRaises(ValueError):
            ab.verify_p18_control(previous,current)

    def test_rejects_unknown_case(self):
        saved,_,_,_=self.fixture()
        with self.assertRaises(ValueError):
            ab.analyze({'suite':'repocontextbench','cases':[saved]},[],None)


if __name__=='__main__':
    unittest.main()
