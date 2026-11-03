"""Offline test: benchmark cleanup only removes per-case SQLite copies."""
from pathlib import Path
import tempfile
import unittest

from benchmark.run import cleanup_case_index


class BenchmarkCleanupTests(unittest.TestCase):
    def test_cleanup_preserves_master_index_and_records(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)
            master=run/"_prepared_indexes"/"repocontextbench"/"middle-files"/"code_intelligence.sqlite"
            master.parent.mkdir(parents=True)
            master.write_bytes(b"master")
            case=run/"case_0001"
            copy=case/"middle-files"/"code_intelligence.sqlite"
            copy.parent.mkdir(parents=True)
            copy.write_bytes(b"private")
            record=case/"runner_record.json"
            record.write_text('{"machine_result_available": true}',encoding="utf-8")
            cleanup_case_index(case)
            self.assertFalse(copy.exists())
            self.assertEqual(master.read_bytes(),b"master")
            self.assertTrue(record.is_file())
            cleanup_case_index(case)  # idempotent


if __name__=="__main__":
    unittest.main()
