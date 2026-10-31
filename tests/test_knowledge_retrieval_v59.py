"""V5.9 independent KB search, graph expansion and baseline parity tests.

Synthetic project files are test fixtures, not gold-label shortcuts.
"""
from __future__ import annotations
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from codebase import Repo
from code_intelligence import build_intelligence, search_file_candidates
from knowledge_base import build_knowledge


class KnowledgeRetrievalV59Test(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.src=self.base/"project"
        self.src.mkdir()
        self.output=self.base/"out"
        kbpath=self.base/"kb.sqlite"
        env=patch.dict(os.environ,{"LOCAL_CODE_AGENT_KB_PATH":str(kbpath)})
        env.start()
        self.addCleanup(env.stop)
        pack_dir=self.base/"packs"
        pack_dir.mkdir()
        pack={
            "schema_version":1,
            "pack_id":"test-general-concepts",
            "version":"1.0.0",
            "license":"CC0-1.0",
            "concepts":[{
                "id":"reliability.retry",
                "domain":"distributed-systems",
                "label":"retry",
                "description":"Repeat a failed operation cautiously.",
                "source":"curated-test",
                "aliases":["retry","backoff"]
            }],
            "relations":[],
        }
        (pack_dir/"test.json").write_text(json.dumps(pack),encoding="utf-8")
        build_knowledge(db_path=kbpath,pack_dir=pack_dir)

    def _repo(self):
        repo=Repo(self.src)
        build_intelligence(repo,self.output,verbose=False)
        return repo

    def test_kb_only_fts_file_is_admitted_when_original_words_miss(self):
        (self.src/"background_tasks.py").write_text(
            "def background_task():\n"
            "    method = 'backoff algorithm with delay'\n"
            "    return method\n",encoding="utf-8")
        repo=self._repo()
        baseline=search_file_candidates(
            repo,"Where is retry implemented?",limit=8,strategy="baseline")
        expanded=search_file_candidates(
            repo,"Where is retry implemented?",limit=8,strategy="v59")
        self.assertNotIn("background_tasks.py",{r["path"] for r in baseline})
        found={row["path"]:row for row in expanded}
        self.assertIn("background_tasks.py",found)
        self.assertIn("backoff",found["background_tasks.py"]["kb_fts_terms"])
        self.assertFalse(found["background_tasks.py"]["citation"])

    def test_kb_symbol_name_can_find_file_without_exact_fts_token(self):
        (self.src/"strategy.py").write_text(
            "def BackoffStrategy():\n    return 123\n",encoding="utf-8")
        repo=self._repo()
        baseline=search_file_candidates(
            repo,"Show retry implementation",limit=8,strategy="baseline")
        expanded=search_file_candidates(
            repo,"Show retry implementation",limit=8,strategy="v59")
        self.assertNotIn("strategy.py",{r["path"] for r in baseline})
        found={row["path"]:row for row in expanded}
        self.assertIn("strategy.py",found)
        self.assertIn("backoff",found["strategy.py"]["kb_symbol_terms"])

    def test_one_hop_file_graph_adds_nonmatching_neighbor_only_in_v59(self):
        (self.src/"driver.py").write_text(
            "def driver():\n    accelerator = 123\n    return accelerator\n",
            encoding="utf-8")
        (self.src/"storage.py").write_text(
            "def persist():\n    return 321\n",encoding="utf-8")
        repo=self._repo()
        with closing(sqlite3.connect(repo.intelligence_db)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO relations VALUES (?,?,?,?,?,?,?)",
                    ("file:driver.py","file:storage.py","static-import",
                     "driver.py",2,"static","driver.py:2"))
        baseline=search_file_candidates(
            repo,"accelerator",limit=8,strategy="baseline")
        expanded=search_file_candidates(
            repo,"accelerator",limit=8,strategy="v59")
        self.assertNotIn("storage.py",{r["path"] for r in baseline})
        by_path={row["path"]:row for row in expanded}
        self.assertIn("storage.py",by_path)
        self.assertEqual(by_path["storage.py"]["graph_neighbors"],["driver.py"])
        self.assertFalse(by_path["storage.py"]["citation"])

    def test_original_exact_filename_stays_ahead_of_kb_only(self):
        (self.src/"retry_handler.py").write_text(
            "def retry_handler():\n    return 1\n",encoding="utf-8")
        (self.src/"backoff_worker.py").write_text(
            "def backoff_worker():\n    return 2\n",encoding="utf-8")
        repo=self._repo()
        hits=search_file_candidates(repo,"retry",limit=8)
        self.assertEqual(hits[0]["path"],"retry_handler.py")

    def test_v591_preserves_baseline_top8_when_kb_distractors_compete(self):
        # Baseline must retain its eight strongest file candidates even when
        # many knowledge-expanded files have higher synthetic lexical scores.
        for n in range(12):
            (self.src/('retry_handler_%02d.py' % n)).write_text(
                'def retry_operation():\n    return 1\n',encoding='utf-8')
            (self.src/('background_%02d.py' % n)).write_text(
                'def backoff():\n    return 2\n',encoding='utf-8')
        repo=self._repo()
        question='Where is retry handled?'
        baseline=search_file_candidates(repo,question,limit=20,strategy='baseline')
        expanded=search_file_candidates(repo,question,limit=20,strategy='v59')
        self.assertGreaterEqual(len(baseline),8)
        self.assertEqual(
            [r['path'] for r in expanded[:8]],
            [r['path'] for r in baseline[:8]])
        self.assertEqual(len({r['path'] for r in expanded}),len(expanded))
        self.assertTrue(all(r['citation'] is False for r in expanded))

    def test_v591_expansion_fills_after_protected_baseline(self):
        (self.src/'retry_handler.py').write_text(
            'def retry_handler():\n    return 1\n',encoding='utf-8')
        (self.src/'background_tasks.py').write_text(
            'def backoff():\n    return 2\n',encoding='utf-8')
        repo=self._repo()
        q='retry'
        baseline=search_file_candidates(repo,q,limit=20,strategy='baseline')
        expanded=search_file_candidates(repo,q,limit=20,strategy='v59')
        self.assertEqual([r['path'] for r in expanded[:len(baseline)]],
                         [r['path'] for r in baseline])
        self.assertIn('background_tasks.py',
                      {r['path'] for r in expanded})
        self.assertEqual(len({r['path'] for r in expanded}),len(expanded))

    def test_reject_invalid_strategy(self):
        (self.src/"retry_handler.py").write_text(
            "def retry_handler():\n    return 1\n",encoding="utf-8")
        repo=self._repo()
        with self.assertRaises(ValueError):
            search_file_candidates(repo,"retry",strategy="invalid")


if __name__=="__main__":
    unittest.main()
