"""Source-reading and diversified search regression tests; local and offline."""
import tempfile
import unittest
from pathlib import Path

from codebase import Repo
from code_intelligence import build_intelligence, search_relevant_sources, search_file_candidates, search_file_locations
from investigation_loop import _validate_action, _tool_execute, _compact_tool_result, investigate_iteratively


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

    def test_file_discovery_uses_path_terms_without_fabricating_citations(self):
        (self.root / 'concurrent_pipeline.py').write_text(
            'def dispatch():\n    return 42\n', encoding='utf-8')
        build_intelligence(self.repo, Path(self.temp.name) / 'output', verbose=False)
        matches = search_file_candidates(
            self.repo, 'How do parallel agents combine responses?', limit=8)
        self.assertTrue(any(x['path'] == 'concurrent_pipeline.py' for x in matches))
        self.assertTrue(all(x['citation'] is False for x in matches))
        self.assertTrue(all('line' not in x for x in matches))

    def test_file_discovery_prefers_requested_language(self):
        (self.root / 'python').mkdir()
        (self.root / 'dotnet').mkdir()
        (self.root / 'python' / 'checkpoint_resume.py').write_text(
            'def restore():\n    return 1\n', encoding='utf-8')
        (self.root / 'dotnet' / 'CheckpointResume.cs').write_text(
            'public class CheckpointResume {}\n', encoding='utf-8')
        build_intelligence(self.repo, Path(self.temp.name) / 'output', verbose=False)
        matches = search_file_candidates(
            self.repo, 'How does a .NET workflow resume from a checkpoint?', limit=6)
        self.assertTrue(matches)
        self.assertTrue(matches[0]['path'].startswith('dotnet/'))

    def test_v5_domain_filename_beats_generic_response_files(self):
        (self.root / 'python' / 'packages' / 'orchestrations').mkdir(parents=True)
        (self.root / 'python' / 'samples' / '03-workflows' / 'functional').mkdir(parents=True)
        (self.root / 'python' / 'packages' / 'orchestrations' / '_concurrent.py').write_text(
            'def run_concurrent():\n    return aggregate()\n',
            encoding='utf-8')
        (self.root / 'python' / 'samples' / '03-workflows' / 'functional' /
         'parallel_pipeline.py').write_text(
            'def concurrent_tasks():\n    return 1\n',encoding='utf-8')
        distractors=self.root / 'python' / 'packages' / 'responses'
        distractors.mkdir(parents=True)
        for n in range(12):
            (distractors / ('AgentResponse%d.py' % n)).write_text(
                'class AgentResponse%d:\n    pass\n' % n,encoding='utf-8')
        build_intelligence(self.repo,Path(self.temp.name) / 'output',verbose=False)
        matches=search_file_candidates(
            self.repo,
            'How would you run several specialist agents in parallel on '
            'the same request and then combine their answers into one response?',
            limit=8)
        paths={item['path'] for item in matches}
        self.assertIn('python/packages/orchestrations/_concurrent.py',paths)
        self.assertIn('python/samples/03-workflows/functional/parallel_pipeline.py',paths)
        self.assertTrue(all(item['citation'] is False for item in matches))

    def test_v5_realistic_decision_and_ci_noise(self):
        (self.root / 'python' / 'packages' / 'orchestrations').mkdir(parents=True)
        (self.root / 'python' / 'samples' / '03-workflows' / 'functional').mkdir(parents=True)
        (self.root / 'docs' / 'decisions').mkdir(parents=True)
        (self.root / '.github' / 'workflows').mkdir(parents=True)
        (self.root / 'python' / 'packages' / 'orchestrations' / '_concurrent.py').write_text(
            'def concurrent_workflow():\n    return aggregate_results()\n',encoding='utf-8')
        (self.root / 'python' / 'samples' / '03-workflows' / 'functional' /
         'parallel_pipeline.py').write_text(
            'def pipeline():\n    return parallel_tasks()\n',encoding='utf-8')
        for i in range(12):
            (self.root / 'docs' / 'decisions' / ('decision_%d.md' % i)).write_text(
                ('you their response combine parallel\n' * 25),encoding='utf-8')
            (self.root / '.github' / 'workflows' / ('ci_%d.yml' % i)).write_text(
                'steps: combine parallel response\n',encoding='utf-8')
        build_intelligence(self.repo,Path(self.temp.name) / 'output',verbose=False)
        ranked=search_file_candidates(self.repo,
            'How would you run several specialist agents in parallel on '
            'the same request and then combine their answers into one response?',
            limit=8)
        top={item['path'] for item in ranked}
        self.assertIn('python/packages/orchestrations/_concurrent.py',top)
        self.assertIn('python/samples/03-workflows/functional/parallel_pipeline.py',top)
        self.assertTrue(all(not p.startswith(('.github/','docs/decisions/')) for p in top))
        self.assertTrue(all('you' not in c['content_terms'] and
                            'their' not in c['content_terms'] for c in ranked))

    def test_v5_dotnet_checkpoint_keeps_implementation(self):
        (self.root / 'dotnet' / 'src').mkdir(parents=True)
        (self.root / 'python' / 'samples').mkdir(parents=True)
        (self.root / 'dotnet' / 'src' / 'CheckpointManager.cs').write_text(
            'class CheckpointManager { }\n',encoding='utf-8')
        (self.root / 'python' / 'samples' / 'checkpoint_resume.py').write_text(
            'def resume():\n    return True\n',encoding='utf-8')
        build_intelligence(self.repo,Path(self.temp.name) / 'output',verbose=False)
        matches=search_file_candidates(
            self.repo, 'For a .NET workflow with mutable executor state, '
            'what is needed to resume from a saved point?',limit=8)
        self.assertTrue(matches)
        self.assertEqual(matches[0]['path'],'dotnet/src/CheckpointManager.cs')

    def test_scoped_source_search_does_not_invent_citations(self):
        (self.root / 'checkpoint_resume.py').write_text(
            'def checkpoint():\n    return 1\n'
            'def resume():\n    return checkpoint()\n',encoding='utf-8')
        build_intelligence(self.repo,Path(self.temp.name) / 'output',verbose=False)
        hits=search_file_locations(self.repo,'checkpoint_resume.py',
                                   'How to resume from checkpoint?',limit=8)
        self.assertTrue(hits)
        self.assertTrue(all(row['path']=='checkpoint_resume.py' for row in hits))
        self.assertTrue(all(row['line']>0 for row in hits))
        with self.assertRaises(ValueError):
            search_file_locations(self.repo,'../secret.py','resume')

    def test_scoped_search_expands_parallel_to_concurrent(self):
        (self.root / 'concurrent.py').write_text(
            'class ConcurrentGroup:\n    def concurrent_tasks(self):\n'
            '        return 1\n', encoding='utf-8')
        build_intelligence(self.repo,Path(self.temp.name) / 'output',verbose=False)
        hits=search_file_locations(self.repo,'concurrent.py','parallel',limit=5)
        self.assertTrue(hits)
        self.assertTrue(all(hit['path']=='concurrent.py' for hit in hits))

    def test_source_window_uses_real_visible_line_refs(self):
        lines=['%5d | line number %s' % (i,i) for i in range(1,70)]
        lines[43]='   44 | def restore_session():'
        raw={'path':'worker.py','content':'\n'.join(lines),
             'source_refs':['worker.py:%d' % i for i in range(1,70)]}
        compact=_compact_tool_result(raw,max_chars=1000,question='restore session')
        self.assertIn('worker.py:44',compact['source_refs'])
        self.assertNotIn('worker.py:1',compact['source_refs'])
        self.assertLessEqual(len(compact['source_refs']),15)
        self.assertIn('def restore_session()',compact['content'])

    def test_file_candidate_prefill_stays_without_source_citations(self):
        (self.root / 'concurrent.py').write_text('class Empty:\n    pass\n',encoding='utf-8')
        build_intelligence(self.repo,Path(self.temp.name) / 'output',verbose=False)
        class FinishModel:
            def call(self,messages,tools=False,num_predict=None,**kwargs):
                if num_predict==180:
                    return {'content':'{"action":"finish"}'}
                return {'content':'No code evidence.'}
        result=investigate_iteratively(self.repo,'parallel concurrent',
                         FinishModel(),{'intent':'locate','queries':['MissingToken777'],
                                         'symbols':[]},max_steps=2,review_rounds=0)
        self.assertTrue(result['file_discovery']['candidates'])
        self.assertLessEqual(result['steps_used'],2)
        self.assertFalse(result['source_citations'])

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
