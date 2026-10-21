import tempfile
import unittest
from pathlib import Path
from codebase import Repo

class AutoIndexTests(unittest.TestCase):
    def test_auto_reuse_and_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'repo'
            src.mkdir()
            f = src / 'Hello.java'
            f.write_text('class Hello {}', encoding='utf-8')
            repo = Repo(src, Path(tmp) / 'index.sqlite')
            first = repo.ensure_index()
            self.assertEqual(first['status'], 'created-or-refreshed')
            self.assertIn('Hello', repo.semantic_search('Hello'))
            second = repo.ensure_index()
            self.assertEqual(second['status'], 'up-to-date')
            f.write_text('class ChangedName { }', encoding='utf-8')
            third = repo.ensure_index()
            self.assertEqual(third['status'], 'created-or-refreshed')
            self.assertIn('ChangedName', repo.semantic_search('ChangedName'))

if __name__ == '__main__': unittest.main()
