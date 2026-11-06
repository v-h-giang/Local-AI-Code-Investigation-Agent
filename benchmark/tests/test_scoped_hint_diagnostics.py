"""Unit tests for saved-hybrid scoped symbol hint diagnosis (no Ollama)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmark.scoped_hint_diagnostics import diagnose_case, overlapping_ids, summarize


class ScopedHintDiagnosticsTests(unittest.TestCase):
    def test_window_overlap_and_added_coverage(self):
        gold=[{'id':'E1','path':'src/a.f90','start_line':20,'end_line':22},
              {'id':'E2','path':'src/a.f90','start_line':50,'end_line':60}]
        self.assertEqual(overlapping_ids(gold,[('src/a.f90',12,19)]),set())
        self.assertEqual(overlapping_ids(gold,[('src/a.f90',18,26)]),{'E1'})
        self.assertEqual(overlapping_ids(gold,[('src/a.f90',1,100)]),{'E1','E2'})

    def test_scoped_hint_is_navigation_not_citation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'intelligence.sqlite'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE symbols (path TEXT,line INTEGER,'
                             'end_line INTEGER,name TEXT,kind TEXT)')
                conn.execute('INSERT INTO symbols VALUES (?,?,?,?,?)',
                             ('src/a.f90',21,24,'restore_persistent_state','subroutine'))
            case={'id':'test-case','suite':'repocontextbench',
                  'question':'How do we restore persistent state?',
                  'gold_spans':[{'id':'E1','path':'src/a.f90',
                                 'start_line':20,'end_line':23}]}
            stored={'id':'test-case','question':case['question'],
                    'variants':{'hybrid':{'top8_diagnostics':[
                        {'path':'src/a.f90','line_start':1,'line_end':10,
                         'retrieval_views':['dense']} ]}}}
            row=diagnose_case(case,stored,SimpleNamespace(intelligence_db=db),
                              radius=8)
            self.assertEqual(row['hint_count'],1)
            self.assertEqual(row['new_window_overlap_ids'],['E1'])
            self.assertEqual(row['exact_line_overlap_ids'],['E1'])
            self.assertEqual(summarize([row])['new_gold_span_window_hits'],1)

    def test_rejects_wrong_case_question(self):
        case={'id':'test-case','question':'real question','gold_spans':[]}
        stored={'question':'different','variants':{'hybrid':{'top8_diagnostics':[]}}}
        with self.assertRaises(ValueError):
            diagnose_case(case,stored,SimpleNamespace(intelligence_db='unused'))


if __name__=='__main__':
    unittest.main()
