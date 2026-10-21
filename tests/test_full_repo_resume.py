"""Offline integration tests for repository-wide, power-loss-safe resumability."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from codebase import Repo
from overview import export_overview
from agent_core import OllamaError

class SimulatedOllama:
    model = 'qwen3:8b'
    num_ctx = 2048
    def __init__(self, fail_at=None):
        self.calls = 0
        self.fail_at = fail_at
    def call(self, messages, **kwargs):
        self.calls += 1
        if self.calls == self.fail_at:
            raise OllamaError('simulated power or Ollama failure')
        return {'content':'Nhận định có bằng chứng ở dòng source.'}

class FullRepoResumeTests(unittest.TestCase):
    def test_all_files_and_long_file_resume_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)/'repo'
            project.mkdir()
            for i in range(120):
                (project/f'Service{i:04}.java').write_text(f'public class Service{i} {{}}\n', encoding='utf-8')
            (project/'LargeService.java').write_text(''.join(
                f'public int method{i}() {{ return {i}; }}\n' for i in range(220)), encoding='utf-8')
            output = Path(directory)/'out'
            repo = Repo(project, Path(directory)/'index.db')
            first_llm = SimulatedOllama(fail_at=30)
            export_overview(repo, output, llm=first_llm, verbose=False)
            before = json.loads((output/'analysis_manifest.json').read_text('utf-8'))
            self.assertEqual(before['status'], 'incomplete')
            self.assertEqual(before['chunks_completed'], 29)
            self.assertGreater(before['chunks_planned'], 121)
            self.assertEqual(len(list((output/'.investigation_cache/chunks').rglob('*.json'))), 29)
            resumed = SimulatedOllama()
            export_overview(repo, output, llm=resumed, verbose=False)
            after = json.loads((output/'analysis_manifest.json').read_text('utf-8'))
            self.assertEqual(after['status'], 'complete')
            self.assertEqual(after['files_completed'], 121)
            self.assertEqual(after['chunks_completed'], after['chunks_planned'])
            self.assertEqual(after['chunks_loaded_from_cache'],29)
            self.assertEqual(resumed.calls, after['chunks_planned']-29)
            self.assertEqual(len(list((output/'analysis_files').glob('*.md'))),121)

if __name__=='__main__':
    unittest.main()
