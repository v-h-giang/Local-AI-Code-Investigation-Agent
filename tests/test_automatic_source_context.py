"""Auto context integration: ordinary commands require no manual KB/index steps."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import main


class AutomaticSourceContextTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace=Path(temp.name)
        self.project=self.workspace/'project'
        self.project.mkdir()
        (self.project/'solver.f90').write_text(
            'module solver\ncontains\nsubroutine advance(dt)\nend subroutine advance\nend module solver\n',
            encoding='utf-8')
        self.out=self.workspace/'reports'
        env=patch.dict(os.environ,{
            'LOCAL_CODE_AGENT_KB_PATH':str(self.workspace/'knowledge'/'global.sqlite')})
        env.start()
        self.addCleanup(env.stop)

    def _call(self, command, *params):
        buffer=io.StringIO()
        with contextlib.redirect_stdout(buffer),patch('agent.print_ram_status'):
            status=main(['--project',str(self.project),command,*params,
                         '--out',str(self.out)])
        return status,buffer.getvalue()

    def test_architecture_automatically_initializes_all_three_layers(self):
        status,log=self._call('architecture')
        self.assertEqual(status,0,log[-1200:])
        context=json.loads((self.out/'middle-files'/'source_context.json').read_text(
            encoding='utf-8'))
        self.assertEqual(context['knowledge']['status'],'ready')
        self.assertGreaterEqual(context['knowledge']['concepts'],126)
        self.assertEqual(context['intelligence']['files'],1)
        self.assertIn({'language':'fortran','files':1},
                      context['technologies']['languages'])
        self.assertEqual(context['technologies']['module_count'],1)
        self.assertTrue((self.out/'middle-files'/'code_intelligence.sqlite').is_file())
        self.assertTrue((self.out/'suggested_investigations.html').is_file())
        self.assertTrue((self.workspace/'knowledge'/'global.sqlite').is_file())

    def test_architecture_reuses_prepared_index_in_suggestions(self):
        from code_intelligence import build_intelligence
        calls=[]
        def tracking(*args,**kwargs):
            calls.append(1)
            return build_intelligence(*args,**kwargs)
        with patch('source_context.build_intelligence',side_effect=tracking):
            status,log=self._call('architecture')
        self.assertEqual(status,0,log[-1200:])
        self.assertEqual(len(calls),1)

    def test_investigate_starts_without_manual_intelligence_or_knowledge(self):
        status,log=self._call('investigate','Where is Fortran advance?', '--non-ai')
        self.assertEqual(status,0,log[-1200:])
        context=json.loads((self.out/'middle-files'/'source_context.json').read_text(
            encoding='utf-8'))
        self.assertEqual(context['intelligence']['files'],1)
        self.assertIn({'language':'fortran','files':1},
                      context['technologies']['languages'])
        records=list((self.out/'middle-files'/'investigations').glob('INV-*.json'))
        self.assertTrue(records)
        result=json.loads(records[0].read_text(encoding='utf-8'))
        self.assertEqual(result['investigation']['source_context']['knowledge']['status'],'ready')

    def test_missing_global_kb_does_not_block_source_analysis(self):
        with patch('source_context.build_knowledge',side_effect=PermissionError('denied')):
            status,log=self._call('architecture')
        self.assertEqual(status,0,log[-1200:])
        context=json.loads((self.out/'middle-files'/'source_context.json').read_text(
            encoding='utf-8'))
        self.assertEqual(context['knowledge']['status'],'unavailable')
        self.assertEqual(context['intelligence']['files'],1)

    def test_repeated_invocation_reuses_intelligence_index(self):
        status,log=self._call('architecture')
        self.assertEqual(status,0,log[-1000:])
        status,log=self._call('investigate','Where is advance?', '--non-ai')
        self.assertEqual(status,0,log[-1000:])
        context=json.loads((self.out/'middle-files'/'source_context.json').read_text(
            encoding='utf-8'))
        self.assertEqual(context['intelligence']['changed_files'],0)
        self.assertEqual(context['intelligence']['graph_rebuilt'],False)


if __name__=='__main__':
    unittest.main()
