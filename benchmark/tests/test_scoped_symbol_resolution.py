"""Offline regression tests for experimental scope-local symbol navigation.

Uses a synthetic SQLite fixture (no Ollama/Generative LLM and no gold labels).
"""
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest

from scoped_symbol_resolution import scoped_symbol_resolve


class ScopedSymbolResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'code_intelligence.sqlite'
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('CREATE TABLE symbols (path TEXT,line INTEGER,'
                         'end_line INTEGER,name TEXT,kind TEXT)')
            conn.executemany('INSERT INTO symbols VALUES (?,?,?,?,?)', [
                ('python/core.py',10,20,'restore_state','function'),
                ('python/core.py',30,35,'streaming_response_handler','function'),
                ('python/helper.py',5,10,'restore_state','function'),
                ('dotnet/Core.cs',11,18,'restore_state','method'),
                ('python/README.md',8,8,'restore_state','heading'),
                ('python/delegation.py',14,26,'delegate_independent_tasks','function'),
                ('dotnet/Other.cs',23,24,'unrelatedSymbol','method'),
            ])
            conn.commit()
        self.repo = SimpleNamespace(intelligence_db=self.db)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def base():
        return [
            {'path':'python/delegation.py','line_hint':100,'line_start':88,
             'line_end':112,'retrieval_views':['dense'],'citation':False},
            {'path':'python/core.py','line_hint':200,'line_start':188,
             'line_end':212,'retrieval_views':['filename','dense'],'citation':False},
        ]

    def test_natural_language_annotation_only_and_preserves_order(self):
        rows=self.base()
        original=[dict(x) for x in rows]
        out=scoped_symbol_resolve(
            self.repo,'How do we delegate independent tasks?',rows)
        self.assertEqual([r['path'] for r in out],[r['path'] for r in rows])
        self.assertEqual(out[0]['line_hint'],100)
        self.assertEqual(out[0]['symbol_hints'][0]['name'],
                         'delegate_independent_tasks')
        self.assertEqual(rows,original)
        self.assertTrue(all(not h['citation']
                            for h in out[0]['symbol_hints']))

    def test_explicit_unique_identifier_is_rescued(self):
        rows=[{'path':'python/delegation.py','line_hint':22,
               'line_start':12,'line_end':44}]
        result=scoped_symbol_resolve(
            self.repo,'Where is streaming_response_handler()?',rows)
        self.assertEqual(result[0]['path'],'python/core.py')
        self.assertEqual(result[0]['line_hint_source'],'scoped-symbol')
        self.assertFalse(result[0]['citation'])

    def test_duplicate_unscoped_identifier_does_not_displace_hybrid(self):
        rows=self.base()
        result=scoped_symbol_resolve(self.repo,'Find restore_state()',rows)
        self.assertEqual([r['path'] for r in result],
                         [r['path'] for r in rows])

    def test_explicit_language_filters_rescue(self):
        rows=[{'path':'python/delegation.py','line_hint':10}]
        result=scoped_symbol_resolve(
            self.repo,'Where is restore_state() in .NET?',rows)
        self.assertEqual(result[0]['path'],'dotnet/Core.cs')
        self.assertEqual(result[0]['line_hint_source'],'scoped-symbol')

    def test_missing_index_returns_same_hybrid(self):
        rows=self.base()
        result=scoped_symbol_resolve(
            SimpleNamespace(intelligence_db=Path(self.tmp.name)/'absent.sqlite'),
            'restore_state()',rows)
        self.assertEqual(result,rows)

    def test_no_ambiguous_generic_titlecase_boost(self):
        rows=self.base()
        out=scoped_symbol_resolve(self.repo,
                                  'How does an Agent run workflows?',rows)
        self.assertEqual([r['path'] for r in out],
                         [r['path'] for r in rows])
        self.assertTrue(all('symbol_hints' not in r for r in out))


if __name__=='__main__':
    unittest.main()
