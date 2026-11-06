"""Tests for evidence A/B gain/loss audit using saved-style records."""
import unittest

from benchmark.evidence_window_case_diagnostics import inspect


class EvidenceCaseDiagnosticsTests(unittest.TestCase):
    def test_net_zero_still_reports_gain_and_loss(self):
        def variant(ids, chars, emitted):
            return {'gold_citable_ids':ids,'gold_visible_ids':ids,
                    'serialized_chars':chars,'displayed_source_lines':5,
                    'alternate_windows_requested':emitted,
                    'alternate_windows_emitted':emitted,
                    'alternate_windows_skipped':0}
        evidence={
            'suite':'repocontextbench','cases':[
                {'id':'one','variants':{
                    '0':variant(['A'],600,0),
                    '1':variant([],500,1),
                    '2':variant([],500,2)}},
                {'id':'two','variants':{
                    '0':variant([],600,0),
                    '1':variant(['B'],500,1),
                    '2':variant(['B'],500,2)}},
            ]}
        multi={
            'suite':'repocontextbench','cases':[
                {'id':'one','multiwindow_diagnostics':{'new_gold_span_ids':[]}},
                {'id':'two','multiwindow_diagnostics':{'new_gold_span_ids':['B']}},
            ]}
        result=inspect(evidence,multi)
        self.assertEqual(result['summary']['by_budget']['1']
                         ['gross_gained_gold_spans'],1)
        self.assertEqual(result['summary']['by_budget']['1']
                         ['gross_lost_gold_spans'],1)
        self.assertEqual(result['summary']['by_budget']['1']
                         ['opportunity_gold_spans_gained'],1)
        self.assertEqual(set(result['summary']['case_ids_with_changed_gold_evidence']),
                         {'one','two'})

    def test_citation_must_be_visible(self):
        evidence={'suite':'repocontextbench','cases':[{
            'id':'one','variants':{
                '0':self._variant([],[]),
                '1':self._variant(['E1'],[]),
                '2':self._variant([],[])}}]}
        multi={'suite':'repocontextbench','cases':[{
            'id':'one','multiwindow_diagnostics':{'new_gold_span_ids':['E1']}}]}
        with self.assertRaises(ValueError):
            inspect(evidence,multi)

    @staticmethod
    def _variant(citable, visible):
        return {'gold_citable_ids':citable,'gold_visible_ids':visible,
                'serialized_chars':200,'displayed_source_lines':1,
                'alternate_windows_requested':0,
                'alternate_windows_emitted':0,
                'alternate_windows_skipped':0}


if __name__=='__main__':
    unittest.main()
