import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run


class BenchmarkTests(unittest.TestCase):
    def test_dataset_exactly_30(self):
        cases = run.read_cases()
        self.assertEqual(len(cases), 30)
        self.assertEqual(sum(x['suite'] == 'repocontextbench' for x in cases), 20)
        self.assertEqual(sum(x['suite'] == 'stackrepoqa' for x in cases), 10)
        self.assertEqual(sum(len(x['gold_spans']) for x in cases), 99)

    def test_repo_pins_match(self):
        for case in run.read_cases():
            self.assertEqual((case['repo'], case['commit']), run.REPOS[case['suite']][:2])

    def test_run_id_security(self):
        for bad in ('../outside', '/root', '..', 'a/b', 'a\\b', ''):
            with self.assertRaises(ValueError):
                run.check_run_id(bad)
        self.assertEqual(run.check_run_id('test-30_1'), 'test-30_1')

    def test_valid_refs_are_confined_and_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'foo.py').write_text('first\nsecond\n', encoding='utf-8')
            self.assertEqual(run.valid_ref(root, {'path': 'foo.py', 'line': 2}), ('foo.py', 2))
            self.assertIsNone(run.valid_ref(root, {'path': 'foo.py', 'line': 3}))
            self.assertIsNone(run.valid_ref(root, {'path': '../foo.py', 'line': 1}))

    def test_evidence_is_not_confused_with_correctness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'file.py').write_text('a\nb\nc\n', encoding='utf-8')
            case = {'gold_spans': [{'id': 'E1', 'path': 'file.py', 'start_line': 2, 'end_line': 3}]}
            record = {'evidence': [
                {'path': 'file.py', 'line': 2, 'provenance': 'investigation'},
                {'path': 'missing.py', 'line': 1, 'provenance': 'investigation'}]}
            score = run.score_evidence(root, case, record)
            self.assertEqual(score['gold_span_hits'], 1)
            self.assertEqual(score['citation_validity'], .5)
            self.assertEqual(score['gold_span_recall_proxy'], 1.0)

    def test_production_has_no_dependency_on_benchmark(self):
        # Test from parent root without executing the model, importing application
        # modules, or modifying any production source.
        agent = ROOT.parent / 'agent.py'
        self.assertTrue(agent.is_file())
        self.assertNotIn('from benchmark', agent.read_text(encoding='utf-8'))
        self.assertNotIn('import benchmark', agent.read_text(encoding='utf-8'))
        assert (ROOT.parent / 'codebase.py').is_file()

    def test_list_requires_no_model_or_repo_checkout(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'run.py'), '--list'],
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('Total: 30', proc.stdout)

if __name__ == '__main__':
    unittest.main()
