"""Read-only structural audit unit tests; no Ollama."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from benchmark.multiwindow_index_audit import audit, self_test


class MultiwindowIndexAuditTests(unittest.TestCase):
    def test_selector_accepts_raw_dense_fields(self):
        self.assertTrue(self_test())

    def test_index_reports_eligible_second_chunk(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/'emb.sqlite'
            with closing(sqlite3.connect(db)) as conn:
                conn.execute('CREATE TABLE chunks (path TEXT,start_line INTEGER,end_line INTEGER)')
                conn.executemany('INSERT INTO chunks VALUES (?,?,?)',[
                    ('src/long.py',1,48),
                    ('src/long.py',37,84),
                    ('src/long.py',145,192),
                ])
                conn.commit()
                report={'cases':[{'id':'case-1','variants':{
                    'hybrid':{'top8_diagnostics':[
                        {'path':'src/long.py','line_start':1,'line_end':48}]}}
                }]}
                result=audit(report,conn)
                summary=result['summary']
                self.assertEqual(summary['top8_multi_chunk_path_occurrences'],1)
                self.assertEqual(summary['top8_structurally_viable_path_occurrences'],1)
                self.assertTrue(summary['needs_instrumentation'])
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')


if __name__=='__main__':
    unittest.main()
