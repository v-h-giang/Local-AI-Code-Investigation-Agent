import tempfile
import unittest
from pathlib import Path
from architecture import export_architecture
from codebase import Repo
from module_summary import summarize_modules

class OutputLayoutTests(unittest.TestCase):
    def test_middle_files_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'src'
            (root/'sample').mkdir(parents=True)
            (root/'sample'/'Example.java').write_text('/** Handles example module. */\npublic class Example {}',encoding='utf-8')
            out=Path(tmp)/'out'
            repo=Repo(root)
            first=export_architecture(repo,out,verbose=False)
            self.assertFalse(first['reused_graph'])
            summarize_modules(repo,out,verbose=False)
            for name in ('architecture.json','module_summary.json','file_links.csv','dependencies.csv'):
                self.assertTrue((out/'middle-files'/name).exists())
                self.assertFalse((out/name).exists())
            report=(out/'module_summary.md').read_text(encoding='utf-8')
            self.assertIn('| Module | File | Vai trò tạm xác định |',report)
            self.assertNotIn('Phương pháp',report)
            for name in ('architecture.json','module_summary.json','file_links.csv','dependencies.csv'):
                (out/'middle-files'/name).replace(out/name)
            again=export_architecture(repo,out,verbose=False)
            self.assertTrue(again['reused_graph'])
            self.assertTrue((out/'middle-files'/'architecture.json').exists())

    def test_old_ai_cache_preserved(self):
        class FakeLLM:
            model='qwen3:8b'
            num_ctx=2048
            def __init__(self):self.calls=0
            def call(self,messages,**kwargs):
                self.calls+=1
                return {'content':'Handles events: sample/Example.java:1'}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'src'
            (root/'sample').mkdir(parents=True)
            (root/'sample'/'Example.java').write_text('/** Handles events and communication. */\npublic class Example {}',encoding='utf-8')
            out=Path(tmp)/'out'
            repo=Repo(root)
            export_architecture(repo,out,verbose=False)
            llm=FakeLLM()
            summarize_modules(repo,out,llm=llm,verbose=False)
            self.assertEqual(llm.calls,1)
            cache=out/'middle-files'/'.module_summary_cache'
            cache.replace(out/'.module_summary_cache')
            summary=summarize_modules(repo,out,llm=llm,verbose=False)
            self.assertEqual(llm.calls,1)
            self.assertEqual(summary['ai_cached'],1)

if __name__=='__main__':unittest.main()
