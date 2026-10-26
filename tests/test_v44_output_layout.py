import json
import tempfile
import unittest
from pathlib import Path
from architecture import export_architecture
from codebase import Repo
from module_summary import summarize_modules

class TestOutputLayout(unittest.TestCase):
    def test_layout_cache_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); src=base/'src'; (src/'m').mkdir(parents=True)
            (src/'m'/'X.java').write_text('package m;\n/** Processes the activity event. */\npublic class X {}',encoding='utf-8')
            output=base/'out';repo=Repo(src)
            first=export_architecture(repo,output,verbose=False)
            self.assertFalse(first['reused_graph'])
            summarize_modules(repo,output,verbose=False)
            self.assertTrue((output/'architecture.md').is_file())
            self.assertTrue((output/'architecture.drawio').is_file())
            self.assertTrue((output/'module_summary.md').is_file())
            for file in ('architecture.json','module_summary.json','file_links.csv','dependencies.csv'):
                self.assertTrue((output/'middle-files'/file).exists())
                self.assertFalse((output/file).exists())
            content=(output/'module_summary.md').read_text(encoding='utf-8')
            self.assertIn('| Module | File | Vai trò tạm xác định |',content)
            self.assertNotIn('Phương pháp',content)
            self.assertTrue(export_architecture(repo,output,verbose=False)['reused_graph'])
            # simulate the previous root-level layout
            for file in ('architecture.json','module_summary.json','file_links.csv','dependencies.csv'):
                (output/'middle-files'/file).replace(output/file)
            self.assertTrue(export_architecture(repo,output,verbose=False)['reused_graph'])
            for file in ('architecture.json','module_summary.json','file_links.csv','dependencies.csv'):
                self.assertTrue((output/'middle-files'/file).exists())
                self.assertFalse((output/file).exists())
    def test_ai_checkpoint_migrates_without_reanalysis(self):
        class LLM:
            model='qwen3:8b';num_ctx=2048
            def __init__(self):self.n=0
            def call(self,messages,**kwargs):
                self.n+=1
                return {'content':'Service processes activity; m/X.java:2'}
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);src=base/'src';(src/'m').mkdir(parents=True)
            (src/'m'/'X.java').write_text('/** Service processes activity events. */\npublic class X {}',encoding='utf-8')
            out=base/'out';repo=Repo(src);llm=LLM()
            export_architecture(repo,out,verbose=False)
            summarize_modules(repo,out,llm=llm,verbose=False)
            self.assertEqual(llm.n,1)
            cache=out/'middle-files'/'.module_summary_cache'
            cache.replace(out/'.module_summary_cache')
            again=summarize_modules(repo,out,llm=llm,verbose=False)
            self.assertEqual(llm.n,1)
            self.assertEqual(again['ai_cached'],1)
            self.assertFalse((out/'.module_summary_cache').exists())
if __name__=='__main__':unittest.main()
