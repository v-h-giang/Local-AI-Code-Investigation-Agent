import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout

from agent import main
from codebase import Repo
from suggested_investigations import suggest_investigations, auto_investigate


class SuggestionsTest(unittest.TestCase):
    def _project(self, root):
        src = root / 'source'
        src.mkdir()
        (src / 'OrderService.java').write_text('''public class OrderService {
 public void saveOrder() { processOrder(); }
 public void processOrder() { saveOrder(); }
}
''',encoding='utf-8')
        (src / 'OrderController.java').write_text('''import OrderService;
public class OrderController { public void submitOrder() { } }
''', encoding='utf-8')
        (src / 'order.sql').write_text('SELECT * FROM orders;\nINSERT INTO orders VALUES (1);',encoding='utf-8')
        return src

    def test_source_backed_two_groups_and_20_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            repo=Repo(self._project(root))
            out=root/'out'
            report=suggest_investigations(repo,out)
            self.assertLessEqual(report['suggestions_count'],20)
            self.assertGreater(report['suggestions_count'],0)
            self.assertEqual(report['suggestion_groups'],['Business Flows','Technical Architecture'])
            doc=json.loads((out/'middle-files'/'suggested_investigations.json').read_text(encoding='utf-8'))
            self.assertEqual(doc['generated_count'],len(doc['candidates']))
            self.assertTrue(all(x['source_evidence'] and ':' in x['source_evidence'][0] for x in doc['candidates']))
            for group in doc['groups']:
                self.assertIn(group,(out/'suggested_investigations.md').read_text(encoding='utf-8'))
            self.assertTrue(any(x['group']=='Business Flows' for x in doc['candidates']))
            self.assertTrue(any(x['group']=='Technical Architecture' for x in doc['candidates']))
            self.assertEqual(doc['candidates'][0]['id'],'INV-001')

    def test_empty_project_does_not_fabricate_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'source';src.mkdir()
            doc=suggest_investigations(Repo(src),root/'out')
            self.assertEqual(doc['suggestions_count'],0)

    def test_architecture_default_never_initializes_qwen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=self._project(root)
            with patch('agent.print_ram_status'), patch('agent.Ollama') as llm, redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--project',str(src),'architecture','--out',str(root/'out')]),0)
                llm.assert_not_called()
            self.assertTrue((root/'out'/'suggested_investigations.md').exists())

    def test_auto_top_executes_only_requested_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=self._project(root)
            with patch('agent.print_ram_status'), patch('agent.Ollama') as model, \
                 patch('suggested_investigations.investigate',return_value={'answer':'Evidence only'}) as run, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--project',str(src),'architecture','--auto-investigate-top','2',
                                       '--out',str(root/'out')]),0)
            self.assertEqual(run.call_count,2)
            self.assertEqual(json.loads((root/'out'/'investigations'/'manifest.json').read_text())['executed'],2)
            self.assertTrue((root/'out'/'investigations'/'INV-002.json').exists())

    def test_auto_top_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=self._project(root)
            with patch('agent.print_ram_status'), patch('agent.Ollama'), \
                 patch('suggested_investigations.investigate',side_effect=RuntimeError('Ollama disconnected')), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--project',str(src),'architecture','--auto-investigate-top','1',
                                       '--out',str(root/'out')]),2)
            manifest=json.loads((root/'out'/'investigations'/'manifest.json').read_text())
            self.assertEqual(manifest['successful'],0)
            self.assertEqual(manifest['results'][0]['status'],'failed')

if __name__=='__main__':unittest.main()
