import json
from types import SimpleNamespace
from unittest.mock import patch
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
            self.assertEqual(score['gold_file_recall_proxy'], 1.0)
            self.assertEqual(score['gold_files'], 1)
            self.assertEqual(score['gold_file_hits'], 1)

    def test_candidate_observed_and_reported_recall_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root / 'a.py').write_text(
                'first line\nimportant gold line\nlast line\n',encoding='utf-8')
            (root / 'b.py').write_text(
                'other code\n',encoding='utf-8')
            case={'gold_spans':[{'path':'a.py','start_line':2,'end_line':2}]}
            record={
                'evidence':[{'path':'b.py','line':1,'provenance':'investigation'}],
                'investigation':{
                    'file_discovery':{'candidates':[
                        {'path':'a.py','citation':False},
                        {'path':'../outside.py','citation':False}]},
                    'steps':[{'tool':'search_file','source_refs':['a.py:2']}]}
            }
            result=run.score_evidence(root,case,record)
            self.assertEqual(result['candidate_file_recall_at_8'],1.0)
            self.assertEqual(result['observed_file_recall'],1.0)
            self.assertEqual(result['observed_span_recall'],1.0)
            self.assertEqual(result['gold_file_recall_proxy'],0.0)
            self.assertEqual(result['gold_span_recall_proxy'],0.0)
            self.assertEqual(result['citation_validity'],1.0)

    def test_production_has_no_dependency_on_benchmark(self):
        # Test from parent root without executing the model, importing application
        # modules, or modifying any production source.
        agent = ROOT.parent / 'agent.py'
        self.assertTrue(agent.is_file())
        self.assertNotIn('from benchmark', agent.read_text(encoding='utf-8'))
        self.assertNotIn('import benchmark', agent.read_text(encoding='utf-8'))
        assert (ROOT.parent / 'codebase.py').is_file()

    def test_recovery_from_windows_console_failure_without_rerunning_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / 'project'
            project.mkdir()
            (project / 'source.java').write_text('class A {}\n', encoding='utf-8')
            folder = root / 'results' / 'case'
            machine_folder = folder / 'middle-files' / 'investigations'
            machine_folder.mkdir(parents=True)
            (machine_folder / 'INV.json').write_text(json.dumps({
                'status': 'completed',
                'evidence': [{'path': 'source.java', 'line': 1, 'provenance': 'investigation'}],
                'investigation': {'answer': 'đã tìm được', 'answer_status': 'qwen-grounded-attempt'}
            }), encoding='utf-8')
            old = {'id': 'case', 'status': 'failed', 'exit_code': 1, 'elapsed_seconds': 95}
            (folder / 'runner_record.json').write_text(json.dumps(old), encoding='utf-8')
            case = {'id': 'case', 'gold_spans': []}
            recovered = run.recover_existing(case, project, folder, old)
            self.assertEqual(recovered['status'], 'completed')
            self.assertTrue(recovered['machine_result_available'])
            self.assertTrue(recovered['recovered_from_machine'])
            self.assertEqual(recovered['elapsed_seconds'], 95)

    def test_runner_forces_utf8_in_child_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / 'src'
            project.mkdir()
            (project / 'code.java').write_text('class Test {}\n', encoding='utf-8')
            fake_agent = root / 'agent.py'
            fake_agent.write_text('print("ok")\n', encoding='utf-8')
            args = SimpleNamespace(model='qwen3:8b', host='http://127.0.0.1:11434',
                                   max_steps=1, review_rounds=0, mode='ai',
                                   max_llm_calls=5, timeout=10)
            with patch.object(run.subprocess, 'run') as execute:
                execute.return_value = SimpleNamespace(stdout='', stderr='error', returncode=1)
                result = run.run_case({'id': 'mock', 'suite': 'repocontextbench',
                                       'repo': 'microsoft/agent-framework', 'question': 'test'},
                                      project, fake_agent, root / 'results', args)
                self.assertEqual(execute.call_args.kwargs['env']['PYTHONIOENCODING'], 'utf-8')
                self.assertEqual(execute.call_args.kwargs['env']['PYTHONUTF8'], '1')
                command = execute.call_args.args[0]
                self.assertEqual(command[command.index('--timeout') + 1], '240')
                self.assertFalse(result['machine_result_available'])

    def test_preflight_does_not_import_app_or_run_model(self):
        # Source-index expansion means all 99 pinned evidence spans are eligible.
        # Preflight must stay static and must not invoke Git, the app CLI, or Qwen.
        with patch.object(run.subprocess, 'run',
                          side_effect=AssertionError('preflight must not run a subprocess')):
            report = run.preflight_report(run.read_cases())
        self.assertEqual(report['gold_spans_total'], 99)
        self.assertEqual(report['gold_spans_indexable'], 99)
        self.assertEqual(report['gold_spans_unsupported'], 0)
        self.assertEqual(report['unsupported_extensions'], {})
        self.assertEqual(report['examples_unreachable'], [])
        self.assertTrue(report['compatible'])

    def test_summary_includes_failed_gold_spans_and_preserves_review_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [
                {'id': 'a', 'suite': 'repocontextbench',
                 'gold_spans': [{'path':'a.py'}, {'path':'a.py'}]},
                {'id': 'b', 'suite': 'repocontextbench',
                 'gold_spans': [{'path':'b.cs'}]},
            ]
            args = SimpleNamespace(suite='repocontextbench', mode='ai')
            records = [
                {'id':'a','suite':'repocontextbench','elapsed_seconds':1,
                 'exit_code':0,'machine_result_available':True,
                 'valid_evidence_items':1,'citation_validity':1.0,
                 'gold_spans':2,'gold_span_hits':1,'gold_files':1,'gold_file_hits':1},
                {'id':'b','suite':'repocontextbench','elapsed_seconds':1,
                 'exit_code':1,'machine_result_available':False}
            ]
            summary = run.save_report(root, records, args, 2, cases=cases)
            self.assertEqual(summary['gold_spans_selected'], 3)
            self.assertEqual(summary['gold_span_recall_proxy'], 0.3333)
            self.assertEqual(summary['successful_case_gold_span_recall_proxy'], 0.5)
            self.assertEqual(summary['gold_file_recall_proxy'], 0.5)
            with (root/'review_template.csv').open(encoding='utf-8-sig') as stream:
                import csv
                rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            rows[0]['notes']='manual grade'
            with (root/'review_template.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                import csv
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            run.save_report(root, records, args, 2, cases=cases)
            with (root/'review_template.csv').open(encoding='utf-8-sig') as stream:
                import csv
                self.assertEqual(list(csv.DictReader(stream))[0]['notes'],'manual grade')

    def test_child_env_utf8(self):
        env = run.child_environment()
        self.assertEqual(env['PYTHONIOENCODING'], 'utf-8')
        self.assertEqual(env['PYTHONUTF8'], '1')

    def test_preflight_cli(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'run.py'), '--preflight'],
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('gold_spans_unsupported', proc.stdout)

    def test_list_requires_no_model_or_repo_checkout(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'run.py'), '--list'],
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('Total: 30', proc.stdout)

if __name__ == '__main__':
    unittest.main()
