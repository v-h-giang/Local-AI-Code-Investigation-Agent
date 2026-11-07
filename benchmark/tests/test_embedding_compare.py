"""Unit tests for gold-blind retrieval ablation; no Ollama required."""
import unittest
from unittest.mock import patch
from benchmark import embedding_compare as ec


class RetrievalAblationTests(unittest.TestCase):
    def test_evaluation_does_not_turn_a_symbol_candidate_into_a_citation(self):
        rows=[{'path':'src/a.f90','start_line':10,'end_line':12,
               'retrieval_views':['exact-symbol'],'line_hint_source':'exact-symbol'}]
        gold=[{'id':'E1','path':'src/a.f90','start_line':11,'end_line':14},
              {'id':'E2','path':'src/a.f90','start_line':40,'end_line':42}]
        result=ec._evaluate(rows,gold)
        self.assertEqual(result['file_hits_at_8'],1)
        self.assertEqual(result['chunk_span_overlap_ids_at_20'],['E1'])
        self.assertEqual(result['top8_diagnostics'][0]['line_hint_source'],'exact-symbol')

    def test_no_symbol_view_does_not_change_hybrid_rank(self):
        from semantic_retrieval import _rrf
        filename=[{'path':'src/a.f90'}]
        fts=[{'path':'src/b.f90'}]
        dense=[{'path':'src/a.f90','start_line':100,'end_line':120}]
        views=[('filename',1.0,filename),('fts-line',1.1,fts),
               ('dense',1.4,dense)]
        self.assertEqual(_rrf(views,limit=8),
                         _rrf(views+[('exact-symbol',1.3,[])],limit=8))

    def test_symbol_view_changes_ranking_but_provenance_remains_navigation(self):
        from semantic_retrieval import _rrf
        views=[('filename',1.0,[{'path':'src/a.f90'}]),
               ('fts-line',1.1,[]),
               ('dense',1.4,[{'path':'src/b.f90','start_line':8,'end_line':12}])]
        symbols=[{'path':'src/a.f90','line_hint':40,'line_start':40,
                  'line_end':40,'citation':False}]
        normal=_rrf(views,limit=8)
        changed=_rrf(views+[('exact-symbol',1.3,symbols)],limit=8)
        self.assertEqual(len(normal),2)
        self.assertEqual(changed[0]['path'],'src/a.f90')
        self.assertEqual(changed[0]['line_hint_source'],'exact-symbol')
        self.assertFalse(changed[0]['citation'])


if __name__=='__main__':
    unittest.main()
