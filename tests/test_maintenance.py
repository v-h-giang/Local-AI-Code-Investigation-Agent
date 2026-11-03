"""Maintenance regression tests: no source/knowledge/machine data is deleted."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import maintenance


class MaintenanceTests(unittest.TestCase):
    def test_dry_run_and_apply_preserve_master_and_knowledge(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            results=root/'benchmark'/'results'
            master=results/'demo'/'_prepared_indexes'/'repocontextbench'/'middle-files'/'code_intelligence.sqlite'
            master.parent.mkdir(parents=True)
            sqlite3.connect(master).close()
            kb=root/'global.sqlite'
            with sqlite3.connect(kb) as conn:
                conn.execute('CREATE TABLE concepts (name TEXT)')
                conn.execute('INSERT INTO concepts VALUES (?)',('keep',))
            case=results/'demo'/'case_0001'
            copy=case/'middle-files'/'code_intelligence.sqlite'
            copy.parent.mkdir(parents=True)
            sqlite3.connect(copy).close()
            (case/'runner_record.json').write_text(
                json.dumps({'machine_result_available':True}),encoding='utf-8')
            incomplete=results/'demo'/'case_0002'/'middle-files'/'code_intelligence.sqlite'
            incomplete.parent.mkdir(parents=True)
            sqlite3.connect(incomplete).close()
            def call(*options):
                out=io.StringIO()
                with contextlib.redirect_stdout(out):
                    maintenance.main(['--root',str(root),'--kb-path',str(kb),*options])
                return json.loads(out.getvalue())
            report=call()
            self.assertEqual(report['mode'],'dry-run')
            self.assertTrue(copy.exists())
            applied=call('--apply')
            self.assertEqual(applied['summary']['copies_removed'],1)
            self.assertFalse(copy.exists())
            self.assertTrue(incomplete.exists())
            self.assertTrue(master.exists())
            with sqlite3.connect(kb) as conn:
                self.assertEqual(conn.execute('SELECT name FROM concepts').fetchone()[0],'keep')

    def test_corrupt_db_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            kb=root/'corrupt.sqlite'
            kb.write_bytes(b'invalid sqlite database')
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                maintenance.main(['--root',str(root),'--kb-path',str(kb),'--apply'])
            self.assertEqual(kb.read_bytes(),b'invalid sqlite database')


if __name__=='__main__':
    unittest.main()
