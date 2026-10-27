"""Ensure investigate defaults to AI while --non-ai explicitly opts out."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent import main


class InvestigateDefaultsTest(unittest.TestCase):
    def test_default_uses_llm_and_non_ai_skips_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            root.mkdir()
            args = ['--project', str(root), 'investigate', 'What does OrderService do?', '--out', str(Path(tmp) / 'out')]
            captured = []

            def fake_investigate(repo, question, llm=None, budget=1200, max_steps=4, review_rounds=1):
                captured.append(llm)
                return {'mode': 'ai' if llm is not None else 'non-ai'}

            with patch('agent.print_ram_status'), patch('agent.Ollama') as fake_llm, \
                    patch('code_intelligence.investigate', side_effect=fake_investigate), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
                self.assertIs(captured[-1].llm, fake_llm.return_value)
                fake_llm.assert_called_once()
                self.assertEqual(main(args + ['--non-ai']), 0)
                self.assertIsNone(captured[-1])
                self.assertEqual(fake_llm.call_count, 1)

    def test_help_mentions_non_ai(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as caught:
                main(['--project', '.', 'investigate', '--help'])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn('--non-ai', output.getvalue())
