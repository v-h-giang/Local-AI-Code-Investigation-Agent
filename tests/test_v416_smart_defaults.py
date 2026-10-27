"""v4.16: auto-investigate-top is a one-switch, fully local workflow."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import main
from test_v415_workflows import TinyLocalModel


class SmartDefaultsTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.src = self.root / 'project'
        (self.src / 'backend').mkdir(parents=True)
        (self.src / 'frontend').mkdir()
        (self.src / 'backend' / 'OrderService.java').write_text(
            'public class OrderService {\n'
            ' public void saveOrder() { }\n'
            ' public void processOrder() { saveOrder(); }\n'
            '}\n', encoding='utf-8')
        (self.src / 'frontend' / 'OrderScreen.mxml').write_text(
            '<root>\n <mx:RemoteObject destination="orderService" />\n</root>\n', encoding='utf-8')
        self.out = self.root / 'out'

    def run_cli(self, *args):
        stdout = io.StringIO()
        with patch('agent.print_ram_status'), patch('agent.Ollama', return_value=TinyLocalModel()), redirect_stdout(stdout):
            status = main(['--project', str(self.src), 'architecture', *args, '--out', str(self.out)])
        return status, stdout.getvalue()

    def test_switch_without_number_enables_all_recommended_phases(self):
        status, log = self.run_cli('--auto-investigate-top')
        self.assertEqual(status, 0, log[-800:])
        manifest = json.loads((self.out / 'middle-files' / 'investigations' / 'manifest.json').read_text('utf-8'))
        self.assertEqual(manifest['requested'], 5)
        self.assertTrue((self.out / 'system_knowledge_report.md').is_file())
        self.assertTrue((self.out / 'system_knowledge.drawio').is_file())
        self.assertTrue((self.out / 'system_knowledge.svg').is_file())
        self.assertIn('"max_llm_calls": 160', log)
        config = json.loads((self.out / 'middle-files' / 'workflow' / 'config.json').read_text('utf-8'))
        self.assertEqual(config['auto_investigate_top'], 5)
        self.assertEqual(config['max_llm_calls'], 160)
        self.assertEqual(config['question_review_rounds'], 2)
        self.assertIn('"synthesize": true', log)
        self.assertIn('"local_ai_question_ranking": true', log)
        self.assertIn('"investigation_review_rounds": 1', log)
        self.assertIn('"synthesis_review_rounds": 2', log)
        ranking = json.loads((self.out / 'middle-files' / 'suggested_investigations.json').read_text('utf-8'))
        self.assertEqual(ranking['ranking_method'], 'local-qwen-reviewed')
        self.assertGreater(manifest['executed'], 0)
        self.assertTrue((self.out / 'investigations' / 'INV-001' / 'result.md').is_file())
        self.assertTrue((self.out / 'investigations' / 'INV-001' / 'investigation.drawio').is_file())
        self.assertFalse(any(self.out.glob('*.json')), 'Machine data belongs in middle-files')

    def test_non_flags_disable_only_selected_phases(self):
        status, log = self.run_cli(
            '--auto-investigate-top', '1', '--non-synthesize', '--non-ai-suggestions',
            '--non-review', '--non-markdown', '--non-diagram', '--non-update-drawio')
        self.assertEqual(status, 0, log[-800:])
        self.assertFalse((self.out / 'system_knowledge_report.md').exists())
        self.assertFalse((self.out / 'investigations' / 'INV-001' / 'result.md').exists())
        self.assertFalse((self.out / 'investigations' / 'INV-001' / 'investigation.drawio').exists())
        self.assertFalse((self.out / 'architecture.investigated.drawio').exists())
        self.assertTrue((self.out / 'middle-files' / 'investigations' / 'INV-001.json').exists())
        self.assertIn('"synthesize": false', log)
        self.assertIn('"local_ai_question_ranking": false', log)
        self.assertIn('"investigation_review_rounds": 0', log)
        self.assertIn('"synthesis_review_rounds": 0', log)
        config = json.loads((self.out / 'middle-files' / 'workflow' / 'config.json').read_text('utf-8'))
        self.assertEqual(config['question_review_rounds'], 0)
        self.assertEqual(config['investigation_review_rounds'], 0)
        ranking = json.loads((self.out / 'middle-files' / 'suggested_investigations.json').read_text('utf-8'))
        self.assertNotEqual(ranking['ranking_method'], 'local-qwen-reviewed')

    def test_legacy_n_and_explicit_budget_still_work(self):
        status, log = self.run_cli('--auto-investigate-top', '1', '--max-llm-calls', '60')
        self.assertEqual(status, 0, log[-800:])
        self.assertIn('"auto_investigate_top": 1', log)
        self.assertIn('"max_llm_calls": 60', log)
        self.assertTrue((self.out / 'system_knowledge_report.md').is_file())

    def test_static_architecture_does_not_start_ollama(self):
        with patch('agent.print_ram_status'), patch('agent.Ollama', side_effect=AssertionError('should not call Ollama')), \
             redirect_stdout(io.StringIO()):
            status = main(['--project', str(self.src), 'architecture', '--out', str(self.out)])
        self.assertEqual(status, 0)
        self.assertTrue((self.out / 'suggested_investigations.md').is_file())
        self.assertFalse((self.out / 'system_knowledge_report.md').exists())

    def test_non_synthesis_works_with_optional_n_without_value(self):
        status, log = self.run_cli('--auto-investigate-top', '--non-synthesize')
        self.assertEqual(status, 0, log[-800:])
        self.assertIn('"auto_investigate_top": 5', log)
        self.assertIn('"synthesize": false', log)
        self.assertFalse((self.out / 'system_knowledge_report.md').exists())

    def test_invalid_top_rejected(self):
        status, log = self.run_cli('--auto-investigate-top', '21')
        self.assertEqual(status, 1)
        self.assertFalse((self.out / 'architecture.md').exists())

if __name__ == '__main__':
    unittest.main()
