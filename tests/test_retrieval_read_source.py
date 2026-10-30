"""Source-reading and diversified search regression tests; local and offline."""
import tempfile
import unittest
from pathlib import Path

from codebase import Repo
from code_intelligence import build_intelligence, search_relevant_sources
from investigation_loop import _validate_action, _tool_execute, investigate_iteratively


class SourceRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'code'
        self.root.mkdir()
        (self.root / 'worker.py').write_text(
            'class Dispatcher:\n'
            '    def distribute_tasks(self):\n'
            '        return aggregate_results()\n'
            '\n'
            'def aggregate_results():\n'
            '    return "fan_in_final"\n', encoding='utf-8')
        (self.root / 'other.py').write_text(
            'def unrelated_tasks():\n'
            '    return "tasks"\n', encoding='utf-8')
        self.repo = Repo(self.root)
        build_intelligence(self.repo, Path(self.temp.name) / 'output', verbose=False)

    def test_search_relevant_sources_returns_real_diverse_files(self):
        results = search_relevant_sources(self.repo, 'distribute tasks aggregate results', limit=8)
        self.assertTrue(results)
        self.assertTrue(any(x['path'] == 'worker.py' for x in results))
        self.assertTrue(all(x['line'] > 0 for x in results))
        self.assertTrue(all((self.root / x['path']).exists() for x in results))

    def test_read_source_is_bounded_and_cites_actual_lines(self):
        action = _validate_action({'tool':'read_source','path':'worker.py',
                                   'start_line':2,'end_line':6})
        self.assertIsNotNone(action)
        result = _tool_execute(self.repo, action)
        self.assertIn('aggregate_results', result['content'])
        self.assertIn('worker.py:5', result['source_refs'])
        self.assertNotIn('worker.py:7', result['source_refs'])

    def test_read_source_denies_escape_and_oversized_range(self):
        for path in ('../secret.py', '/etc/passwd', 'C:/temp/secret.py',
                     'dir/../../secret.py', 'dir\\secret.py'):
            self.assertIsNone(_validate_action({'tool':'read_source','path':path}))
        self.assertIsNone(_validate_action({'tool':'read_source','path':'worker.py',
                                             'start_line':1,'end_line':101}))
        self.assertIsNone(_validate_action({'tool':'shell','query':'python worker.py'}))

    def test_source_is_read_without_execution(self):
        (self.root / 'never.py').write_text(
            'raise RuntimeError("executed")\n', encoding='utf-8')
        action = _validate_action({'tool':'read_source','path':'never.py',
                                   'start_line':1,'end_line':1})
        result = _tool_execute(self.repo, action)
        self.assertIn('raise RuntimeError', result['content'])


if __name__ == '__main__':
    unittest.main()
