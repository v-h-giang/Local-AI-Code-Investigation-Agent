"""Offline tests for P1.12 candidate-window builder using stubbed retrieval."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import heldout_window_builder as wb

SHA='a'*40
REPO='pallets/click'


class DummyRepo:
    def __init__(self): self.calls=[]
    def read_file(self,path,lo,hi):
        self.calls.append((path,lo,hi))
        return '\n'.join(f'{n:5d} | def foo(): pass' for n in range(lo,hi+1))


class CandidateWindowBuilderTests(unittest.TestCase):
    def questions(self):
        return [{'id':'external_001','suite':'external','repo':REPO,
                 'commit':SHA,'question':'How is retry handled?'}]

    def manifest(self,rows):
        tmp=tempfile.TemporaryDirectory()
        path=Path(tmp.name)/'questions.jsonl'
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        self.addCleanup(tmp.cleanup)
        return path

    def test_accepts_question_only_manifest(self):
        rows=wb.read_questions(self.manifest(self.questions()),
                               repository=REPO,commit=SHA)
        self.assertEqual(len(rows),1)

    def test_rejects_gold_from_question_input(self):
        rows=self.questions();rows[0]['gold_spans']=[{'id':'E1'}]
        with self.assertRaises(ValueError):
            wb.read_questions(self.manifest(rows),repository=REPO,commit=SHA)

    def test_rejects_duplicate_question(self):
        rows=self.questions();rows.append(dict(rows[0],id='external_002'))
        with self.assertRaises(ValueError):
            wb.read_questions(self.manifest(rows),repository=REPO,commit=SHA)

    def test_rejects_wrong_commit(self):
        with self.assertRaises(ValueError):
            wb.read_questions(self.manifest(self.questions()),repository=REPO,commit='b'*40)

    def test_exact_coordinate_window(self):
        repo=DummyRepo()
        item=wb._window_for_candidate(repo,{'path':'src/a.py','line_start':10,
                                             'line_end':88},'retry')
        self.assertEqual(item,{'path':'src/a.py','line_start':10,'line_end':57})
        self.assertEqual(repo.calls, [('src/a.py',10,57)])

    def test_fallback_uses_source_location_without_labels(self):
        with patch.object(wb,'search_file_locations',return_value=[{'line':90}]):
            item=wb._window_for_candidate(DummyRepo(),{'path':'src/a.py'},'retry')
        self.assertEqual((item['line_start'],item['line_end']),(78,125))

    def test_rejects_empty_source(self):
        class EmptyRepo:
            def read_file(self,*args):return '(Empty file)'
        self.assertIsNone(wb._window_for_candidate(
            EmptyRepo(),{'path':'src/a.py','line_start':1,'line_end':50},'retry'))

    def test_report_matches_p11_schema_and_has_no_gold(self):
        class Model: model='qwen3-embedding:0.6b'
        dense=[{'path':'src/a.py','start_line':1,'end_line':35}]
        inventory={'src/a.py':[{'path':'src/a.py','start_line':1,
                                'end_line':35,'similarity':.9},
                               {'path':'src/a.py','start_line':70,
                                'end_line':98,'similarity':.8}]}
        with patch.object(wb,'search_file_candidates',return_value=[
                {'path':'src/a.py','line_hint':4}]),patch.object(
                wb,'search_relevant_sources',return_value=[]),patch.object(
                wb,'dense_search',return_value=(dense,inventory)):
            result=wb.build_report(DummyRepo(),self.questions(),'fake.db',Model())
        candidate=result['cases'][0]
        self.assertEqual(len(candidate['variants']['hybrid']['top8_diagnostics']),1)
        self.assertEqual(len(candidate['multiwindow_diagnostics']['alternates']),1)
        self.assertEqual(candidate['multiwindow_diagnostics']['alternates'][0]['new_lines'],29)
        self.assertNotIn('gold_spans',json.dumps(result))
        self.assertEqual(result['method']['frozen_source_commit'],SHA)

    def test_no_hybrid_candidate_fails(self):
        class Model: model='qwen3-embedding:0.6b'
        with patch.object(wb,'search_file_candidates',return_value=[]),patch.object(
                wb,'search_relevant_sources',return_value=[]),patch.object(
                wb,'dense_search',return_value=([],{})):
            with self.assertRaises(ValueError):
                wb.build_report(DummyRepo(),self.questions(),'fake.db',Model())


if __name__=='__main__': unittest.main()
