"""Regression tests for Python, C#, Markdown indexing and source-backed retrieval."""
import tempfile
import unittest
from pathlib import Path

from architecture import _scan, export_architecture
from codebase import Repo
from code_intelligence import build_intelligence, search_intelligence, symbol_query


class MultilanguageIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        self.root.mkdir()
        (self.root / 'worker.py').write_text(
            'import math\n\nclass Worker:\n'
            '    async def process_order(self):\n'
            '        validate_request()\n'
            '\ndef validate_request():\n'
            '    return "uniquePythonSearchTerm"\n', encoding='utf-8')
        (self.root / 'Service.cs').write_text(
            'namespace Example;\n'
            'public class OrderService {\n'
            '    public void SaveOrder() { ValidateOrder(); }\n'
            '    private void ValidateOrder() { }\n'
            '}\n', encoding='utf-8')
        (self.root / 'README.md').write_text(
            '# Overview\n\n'
            '## Reliable streaming resume\n'
            'This explains a uniqueMarkdownSearchTerm.\n', encoding='utf-8')
        self.repo = Repo(self.root)
        self.out = Path(self.tmp.name) / 'generated'

    def test_scanner_and_source_access(self):
        seen = {name for name, _ in _scan(self.root)}
        self.assertEqual(seen, {'worker.py', 'Service.cs', 'README.md'})
        for filename in seen:
            self.assertIn(filename, {item.path for item in self.repo.files(limit=50)})
            self.assertIn('  1 |', self.repo.read_file(filename, 1, 1))
        self.assertIn('process_order', self.repo.outline_file('worker.py'))
        self.assertIn('SaveOrder', self.repo.outline_file('Service.cs'))
        self.assertIn('Reliable streaming resume', self.repo.outline_file('README.md'))

    def test_architecture_inventory_and_intelligence(self):
        architecture = export_architecture(self.repo, self.out, verbose=False)
        self.assertEqual(architecture['files_scanned'], 3)
        result = build_intelligence(self.repo, self.out, verbose=False)
        self.assertEqual(result['changed_files'], 3)
        self.assertEqual(len(symbol_query(self.repo, 'Worker')['definitions']), 1)
        self.assertEqual(len(symbol_query(self.repo, 'process_order')['definitions']), 1)
        self.assertEqual(len(symbol_query(self.repo, 'SaveOrder')['definitions']), 1)
        self.assertTrue(search_intelligence(self.repo, 'uniquePythonSearchTerm'))
        self.assertTrue(search_intelligence(self.repo, 'uniqueMarkdownSearchTerm'))
        self.assertTrue(any(r['path'] == 'Service.cs' for r in
                            search_intelligence(self.repo, 'SaveOrder')))
        self.assertEqual(build_intelligence(self.repo, self.out, verbose=False)['changed_files'], 0)

    def test_invalid_python_still_indexed_as_text(self):
        target = self.root / 'broken.py'
        target.write_text('def broken(:\n  uniqueBrokenCodeToken = 42\n', encoding='utf-8')
        build_intelligence(self.repo, self.out, verbose=False)
        self.assertTrue(search_intelligence(self.repo, 'uniqueBrokenCodeToken'))
        self.assertFalse(any(d['path'] == 'broken.py' for d in
                             symbol_query(self.repo, 'broken')['definitions']))

    def test_indexing_does_not_execute_python(self):
        target = self.root / 'never_execute.py'
        target.write_text('raise RuntimeError("SOURCE_WAS_EXECUTED")\n'
                          'def defined_only(): pass\n', encoding='utf-8')
        build_intelligence(self.repo, self.out, verbose=False)
        self.assertTrue(search_intelligence(self.repo, 'SOURCE_WAS_EXECUTED'))
        self.assertEqual(len(symbol_query(self.repo, 'defined_only')['definitions']), 1)


if __name__ == '__main__':
    unittest.main()
