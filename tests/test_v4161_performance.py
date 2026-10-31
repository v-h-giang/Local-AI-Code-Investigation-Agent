"""Regression tests for scalable code intelligence indexing and bounded ranking."""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from codebase import Repo
from code_intelligence import build_intelligence
from suggested_investigations import _qwen_rank_candidates


class IndexPerformanceRegression(unittest.TestCase):
    def test_incremental_index_reuses_resolved_edges_and_removes_changed_fts_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'src'
            root.mkdir()
            source = root / 'OrderService.java'
            source.write_text('''public class OrderService {
  public void saveOrder() { legacyUniqueToken(); }
  public void legacyUniqueToken() {}
}\n''', encoding='utf-8')
            repo = Repo(root)
            out = Path(td) / 'out'
            with contextlib.redirect_stdout(io.StringIO()):
                first = build_intelligence(repo, out, verbose=False)
            self.assertEqual(first['changed_files'], 1)
            self.assertTrue(first['graph_rebuilt'])
            target = Path(first['index'])
            with contextlib.closing(sqlite3.connect(target)) as con:
                rows = con.execute('SELECT COUNT(*) FROM search_fts').fetchone()[0]
                mappings = con.execute('SELECT COUNT(*) FROM fts_row_paths').fetchone()[0]
                self.assertGreater(rows, 0)
                self.assertEqual(rows, mappings)
            second = build_intelligence(repo, out, verbose=False)
            self.assertEqual(second['changed_files'], 0)
            self.assertFalse(second['graph_rebuilt'])
            self.assertEqual(first['relations'], second['relations'])
            source.write_text('''public class OrderService {
  public void saveOrder() { newUniqueToken(); }
  public void newUniqueToken() {}
}\n''', encoding='utf-8')
            third = build_intelligence(repo, out, verbose=False)
            self.assertEqual(third['changed_files'], 1)
            self.assertTrue(third['graph_rebuilt'])
            with contextlib.closing(sqlite3.connect(target)) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM search_fts WHERE search_fts MATCH 'legacyUniqueToken'").fetchone()[0],0)
                self.assertGreater(con.execute("SELECT COUNT(*) FROM search_fts WHERE search_fts MATCH 'newUniqueToken'").fetchone()[0],0)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM search_fts').fetchone()[0],
                                 con.execute('SELECT COUNT(*) FROM fts_row_paths').fetchone()[0])

    def test_ranking_second_pass_reviews_only_top_candidates_both_groups(self):
        class Stub:
            def __init__(self): self.calls = []
            def call(self, messages, tools=False, num_predict=270):
                self.calls.append(messages[-1]['content'])
                return {'content':json.dumps({'ranking':[]})}
        pool=[]
        for i in range(40):
            pool.append({'candidate_id':f'CAND-{i+1:03d}',
                         'group':'Business Flows' if i<20 else 'Technical Architecture',
                         'question':f'Investigate method {i}',
                         'source_evidence':[f'src/A{i}.java:1'],
                         'score':100-i,'priority':'P1'})
        ai=Stub()
        with contextlib.redirect_stdout(io.StringIO()):
            rounds=_qwen_rank_candidates(ai,pool,rounds=2)
        self.assertEqual(len(ai.calls),13)
        self.assertEqual(sum(r['round']==1 for r in rounds),10)
        self.assertEqual(sum(r['round']==2 for r in rounds),3)
        self.assertTrue(any('CAND-021' in prompt for prompt in ai.calls[10:]))
        self.assertTrue(any('CAND-001' in prompt for prompt in ai.calls[10:]))


if __name__=='__main__':
    unittest.main()
