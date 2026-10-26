import json
import tempfile
import unittest
from pathlib import Path
from codebase import Repo
from module_summary import collect_module_evidence, summarize_modules
from architecture import export_architecture, load_architecture

class FakeLLM:
    model='qwen3:8b'
    num_ctx=2048
    def __init__(self):self.calls=0
    def call(self,messages,tools=False,**kwargs):
        self.calls+=1
        return {'content':'Module xử lý đơn hàng theo mô tả tại app/Order.java:2.'}

class ModuleSummaryTests(unittest.TestCase):
    def test_comments_evidence_offline_and_ai_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'src'; (root/'app').mkdir(parents=True)
            (root/'app'/'Order.java').write_text('package app;\n/** Handles order processing and validation. */\npublic class Order {}\n',encoding='utf-8')
            repo=Repo(root)
            out=Path(tmp)/'out'
            export_architecture(repo,out,verbose=False)
            graph=load_architecture(repo,out)
            data=collect_module_evidence(repo,graph)
            self.assertEqual(data['app']['files'],1)
            self.assertTrue(any('Handles order processing' in c['text'] for c in data['app']['comments']))
            offline=summarize_modules(repo,out,verbose=False)
            self.assertEqual(offline['modules_summarized'],1)
            self.assertIn('Handles order processing',(out/'module_summary.md').read_text('utf-8'))
            llm=FakeLLM()
            summarize_modules(repo,out,llm=llm,verbose=False)
            self.assertEqual(llm.calls,1)
            again=summarize_modules(repo,out,llm=llm,verbose=False)
            self.assertEqual(llm.calls,1)
            self.assertEqual(again['ai_cached'],1)
            self.assertIn('app/Order.java:2',(out/'module_summary.md').read_text('utf-8'))
if __name__=='__main__':unittest.main()
