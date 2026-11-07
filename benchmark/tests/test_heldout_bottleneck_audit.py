"""Tests for retrospective candidate-window opportunity analysis."""
import copy
import unittest

from benchmark.heldout_bottleneck_audit import diagnose

COMMIT = 'a' * 40
REPO = 'pallets/click'
MODES = ('baseline','adaptive_1','merge_balanced_1','merge_anchored_1')


def fixture():
    labels = [{'id':'one', 'question':'How does retry work?', 'repo':REPO,
               'commit':COMMIT, 'suite':'independent', 'gold_spans':[
                   {'id':'E1','path':'src/a.py','start_line':11,'end_line':12},
                   {'id':'E2','path':'src/a.py','start_line':60,'end_line':62},
                   {'id':'E3','path':'src/b.py','start_line':5,'end_line':5},
               ]}]
    saved = {'suite':'independent','repo':REPO,'method':{'frozen_source_commit':COMMIT},'cases':[
        {'id':'one', 'question':labels[0]['question'],
         'variants':{'hybrid':{'top8_diagnostics':[
             {'path':'src/a.py','line_start':10,'line_end':15},
             {'path':'src/b.py','line_start':1,'line_end':2}
         ]}},'multiwindow_diagnostics':{'alternates':[
             {'path':'src/a.py','start_line':54,'end_line':65,'new_lines':12}
         ]}}
    ]}
    def result(hits,complete):
        return {'gold_any_line_ids':hits,'gold_complete_span_ids':complete}
    results = {
        'baseline':result(['E1'],['E1']),
        'adaptive_1':result(['E1','E2'],['E1']),
        'merge_balanced_1':result(['E1'],['E1']),
        'merge_anchored_1':result(['E1','E2'],['E1']),
    }
    evaluation = {'repository':REPO,'source_commit':COMMIT,'suite':'independent',
                  'summary':{'case_count':1,'gold_spans_total':3,'modes':{
                      k:{'gold_spans_any_line':len(v['gold_any_line_ids']),
                         'gold_spans_complete':len(v['gold_complete_span_ids'])}
                      for k,v in results.items()}},
                  'cases':[{'id':'one','gold_span_count':3,'modes':results}]}
    return labels,saved,evaluation


class HeldoutBottleneckAuditTests(unittest.TestCase):
    def test_candidate_ceiling_distinguished_from_final_evidence(self):
        output = diagnose(*fixture())
        view = output['summary']['candidate_window_opportunity']
        self.assertEqual(view['hybrid'], {'any':1,'complete':1})
        self.assertEqual(view['hybrid_plus_dense_1'], {'any':2,'complete':2})
        self.assertEqual(output['summary']['selection']['baseline']['available_in_all_windows_but_missed'],1)
        self.assertEqual(output['summary']['span_length']['single_line'],1)
        self.assertEqual(output['cases'][0]['selected']['adaptive_1']['partial'],['E2'])

    def test_rejects_selected_span_outside_windows(self):
        a,b,c=fixture()
        c['cases'][0]['modes']['baseline']['gold_any_line_ids']=['E1','E3']
        with self.assertRaisesRegex(ValueError,'outside candidate'):
            diagnose(a,b,c)

    def test_rejects_mismatched_commit(self):
        a,b,c=fixture();b['method']['frozen_source_commit']='b'*40
        with self.assertRaisesRegex(ValueError,'Frozen'):
            diagnose(a,b,c)

    def test_rejects_duplicate_case(self):
        a,b,c=fixture();a.append(copy.deepcopy(a[0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            diagnose(a,b,c)

    def test_rejects_mismatched_summary(self):
        a,b,c=fixture();c['summary']['modes']['baseline']['gold_spans_any_line']=2
        with self.assertRaisesRegex(ValueError,'mode totals'):
            diagnose(a,b,c)

    def test_rejects_corrupt_range(self):
        a,b,c=fixture();b['cases'][0]['variants']['hybrid']['top8_diagnostics'][0]['line_end']=0
        with self.assertRaisesRegex(ValueError,'source window range'):
            diagnose(a,b,c)

    def test_dense_alternates_must_match_scope(self):
        a,b,c=fixture();b['cases'][0]['multiwindow_diagnostics']['alternates'][0]['path']='src/other.py'
        with self.assertRaisesRegex(ValueError,'outside Hybrid'):
            diagnose(a,b,c)


if __name__ == '__main__':
    unittest.main()
