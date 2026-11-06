"""Offline tests for Dense source windows in existing Hybrid top-eight files."""
import unittest
from benchmark.top8_multiwindow_diagnostics import (
    window, extra_lines, select_alternates, inspect_case,
    select_from_dense_windows, diagnose_scored_inventory,
)


class Top8MultiWindowTests(unittest.TestCase):
    def test_does_not_add_duplicate_or_near_identical_windows(self):
        hybrid=[{'path':'src/a.f90','line_start':10,'line_end':40}]
        dense=[{'path':'src/a.f90','line_start':12,'line_end':42},
               {'path':'src/a.f90','line_start':70,'line_end':90}]
        selected=select_alternates(hybrid,dense,max_extra=4)
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]['start_line'],70)
        self.assertEqual(selected[0]['new_lines'],21)

    def test_additive_windows_do_not_change_existing_gold_hits(self):
        question='Where are two flows connected?'
        saved={'question':question,'variants':{
            'hybrid':{'top8_diagnostics':[
                {'path':'src/a.f90','line_start':10,'line_end':20}]},
            'dense':{'top8_diagnostics':[
                {'path':'src/a.f90','line_start':70,'line_end':80}]}
        }}
        case={'id':'one','question':question,
              'gold_spans':[{'id':'E1','path':'src/a.f90',
                             'start_line':12,'end_line':15},
                            {'id':'E2','path':'src/a.f90',
                             'start_line':74,'end_line':75}]}
        result=inspect_case(saved,case)
        self.assertEqual(result['hybrid_top8_span_ids'],['E1'])
        self.assertEqual(result['augmented_span_ids'],['E1','E2'])
        self.assertEqual(result['new_span_ids'],['E2'])
        self.assertEqual(result['lost_span_ids'],[])

    def test_only_paths_already_in_hybrid_head_are_eligible(self):
        hybrid=[{'path':'src/a.f90','line_start':1,'line_end':12}]
        dense=[{'path':'src/b.f90','line_start':70,'line_end':90}]
        self.assertEqual(select_alternates(hybrid,dense),[])

    def test_invalid_windows_are_rejected_and_new_lines_counted(self):
        self.assertIsNone(window({'path':'src/a.f90','line_start':0,'line_end':3}))
        self.assertEqual(extra_lines(('a',15,25),[('a',10,20)]),5)
        self.assertEqual(extra_lines(('a',30,34),[('b',30,34)]),5)


    def test_window_supports_both_hybrid_and_raw_dense_field_names(self):
        hybrid={'path':'src/a.f90','line_start':15,'line_end':31}
        raw_dense={'path':'src/a.f90','start_line':15,'end_line':31}
        self.assertEqual(window(hybrid),('src/a.f90',15,31))
        self.assertEqual(window(raw_dense),('src/a.f90',15,31))
        self.assertEqual(window({'path':'src/a.f90',
                                 'start_line':100,'end_line':200}),
                         ('src/a.f90',100,147))
        self.assertIsNone(window({'path':'src/a.f90',
                                  'start_line':None,'end_line':200}))

    def test_scored_inventory_gate_counts_and_selection_agree(self):
        head=[{'path':'src/long.py','line_start':1,'line_end':48}]
        scored={'src/long.py':[
            {'path':'src/long.py','start_line':1,'end_line':48,
             'similarity':0.90},
            {'path':'src/long.py','start_line':37,'end_line':84,
             'similarity':0.80},
            {'path':'src/long.py','start_line':145,'end_line':192,
             'similarity':0.70}]}
        report=diagnose_scored_inventory(head,scored)
        chosen=select_from_dense_windows(head,scored,max_extra=4)
        self.assertEqual(report['top8_paths_in_scored_dense'],1)
        self.assertEqual(report['scored_chunk_rows_in_top8'],3)
        self.assertEqual(report['qualifying_chunk_rows_before_limit'],2)
        self.assertEqual(len(chosen),2)

    def test_full_dense_inventory_can_supply_second_chunk(self):
        hybrid=[{'path':'src/a.f90','line_start':1,'line_end':48},
                {'path':'src/b.f90','line_start':10,'line_end':20}]
        inventory={
            'src/a.f90':[
                {'path':'src/a.f90','start_line':1,'end_line':48,
                 'similarity':0.99},
                {'path':'src/a.f90','start_line':37,'end_line':84,
                 'similarity':0.80},
                {'path':'src/a.f90','start_line':145,'end_line':192,
                 'similarity':0.70}],
            'src/unrelated.f90':[
                {'path':'src/unrelated.f90','start_line':1,'end_line':48,
                 'similarity':1.0}],
        }
        alternatives=select_from_dense_windows(hybrid,inventory,max_extra=2)
        self.assertEqual([r['start_line'] for r in alternatives],[37,145])
        self.assertEqual(alternatives[0]['new_lines'],36)
        self.assertEqual(alternatives[1]['new_lines'],48)
        self.assertTrue(all(not r['citation'] for r in alternatives))


if __name__=='__main__':
    unittest.main()
