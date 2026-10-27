"""v4.15: all workflow phases share bounded local AI, grounded IDs and checkpoints."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from codebase import Repo
from code_intelligence import build_intelligence, investigate
from local_workflow import LocalCallBudget, CallBudgetExceeded
from suggested_investigations import suggest_investigations
from synthesis_workflow import gather_evidence, synthesize
from agent import main


class TinyLocalModel:
    model='qwen3:8b'
    num_ctx=2048
    host='http://127.0.0.1:11434'
    def __init__(self): self.calls=[]
    def call(self,messages,tools=False,num_predict=None,**kwargs):
        self.calls.append(num_predict)
        prompt=messages[-1]['content']
        if num_predict==270:
            # Try to inject a phantom candidate; Python must reject it.
            ids=list(dict.fromkeys(__import__('re').findall(r'CAND-\d{3}',prompt)))
            ranking=[{'id':i,'score':95,'reason':'Important source evidence'} for i in ids]
            ranking.append({'id':'CAND-999','score':100,'reason':'fabricated'})
            return {'content':json.dumps({'ranking':ranking})}
        if num_predict==220:
            return {'content':json.dumps({'intent':'locate','symbols':['saveOrder'],
                                          'queries':['OrderService'],'graph_depth':2})}
        if num_predict==180:
            return {'content':'{"action":"finish"}'}
        if num_predict==340:
            return {'content':'Có bằng chứng tại backend/OrderService.java:2, không xác nhận runtime.'}
        # Generate grounded citations and one false citation (must be discarded).
        refs=list(dict.fromkeys(__import__('re').findall(r'(?:backend|frontend)/[\w.\-/]+:\d+',prompt)))
        return {'content':json.dumps({'summary':'Tổng hợp hệ thống theo bằng chứng tĩnh.',
                                      'citations':refs[:3]+['phantom/Missing.java:999'],
                                      'risks':['Cần xác minh DI và reflection'],
                                      'unknowns':['Chưa xác minh runtime']},ensure_ascii=False)}


class ReviewToolModel(TinyLocalModel):
    def __init__(self): super().__init__();self.decisions=0
    def call(self,messages,tools=False,num_predict=None,**kwargs):
        if num_predict==180:
            self.calls.append(180)
            self.decisions+=1
            if self.decisions==1:return {'content':'{"action":"finish"}'}
            return {'content':'{"action":"tool","tool":"search","query":"OrderService"}'}
        return super().call(messages,tools,num_predict,**kwargs)


class V415WorkflowsTest(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.src=self.root/'project'
        (self.src/'backend').mkdir(parents=True)
        (self.src/'frontend').mkdir()
        (self.src/'backend'/'OrderService.java').write_text(
            "public class OrderService {\n public void saveOrder() { }\n public void processOrder() { saveOrder(); }\n}\n",encoding='utf-8')
        (self.src/'frontend'/'OrderScreen.mxml').write_text(
            '<root>\n <mx:RemoteObject destination="orderService" />\n</root>\n',encoding='utf-8')
        self.out=self.root/'out'
        self.repo=Repo(self.src)

    def test_local_call_budget_checkpoint_and_hard_stop(self):
        fake=TinyLocalModel()
        model=LocalCallBudget(fake,self.out,max_calls=1)
        prompt=[{'role':'user','content':'A'}]
        self.assertIsInstance(model.call(prompt),dict)
        self.assertIsInstance(model.call(prompt),dict)
        self.assertEqual(model.usage()['llm_calls'],1)
        self.assertEqual(model.usage()['cache_hits'],1)
        with self.assertRaises(CallBudgetExceeded):model.call([{'role':'user','content':'B'}])
        self.assertTrue((self.out/'middle-files'/'workflow'/'call_audit.jsonl').exists())

    def test_rejects_nonlocal_ollama_host(self):
        fake=TinyLocalModel();fake.host='https://external.example'
        with self.assertRaises(ValueError):LocalCallBudget(fake,self.out)

    def test_question_loop_keeps_only_real_source_id(self):
        model=TinyLocalModel()
        report=suggest_investigations(self.repo,self.out,top=20,llm=model,ai_rounds=2)
        self.assertGreater(report['suggestions_count'],0)
        self.assertEqual(report['suggestion_groups'],['Business Flows','Technical Architecture'])
        data=json.loads((self.out/'middle-files'/'suggested_investigations.json').read_text(encoding='utf-8'))
        self.assertEqual(data['ranking_method'],'local-qwen-reviewed')
        self.assertTrue(data['ai_ranking_log'])
        self.assertFalse(any(x['subject']=='CAND-999' for x in data['candidates']))
        self.assertTrue(all(x['source_evidence'] and x['id'].startswith('INV-') for x in data['candidates']))
        self.assertTrue(all(x['group'] in data['groups'] for x in data['candidates']))

    def test_critic_can_trigger_extra_bounded_tool(self):
        build_intelligence(self.repo,self.out,verbose=False)
        model=ReviewToolModel()
        result=investigate(self.repo,'Explain saveOrder',model,budget=1200,max_steps=4,review_rounds=1)
        self.assertTrue(result['source_citations'])
        self.assertTrue(any(x.get('status')=='followup-executed' for x in result['review_log']))
        self.assertLessEqual(result['steps_used'],4)
        self.assertEqual(result['steps'][-1]['tool'],'search')

    def test_synthesis_checkpoint_and_citation_whitelist(self):
        from architecture import export_architecture
        from module_summary import summarize_modules
        export_architecture(self.repo,self.out,verbose=False)
        summarize_modules(self.repo,self.out,verbose=False)
        records=gather_evidence(self.repo,self.out)['records']
        self.assertTrue(records)
        model=LocalCallBudget(TinyLocalModel(),self.out,max_calls=12)
        result=synthesize(self.repo,self.out,model,review_rounds=2)
        self.assertEqual(result['status'],'completed')
        self.assertTrue((self.out/'system_knowledge.drawio').is_file())
        self.assertTrue((self.out/'system_knowledge.svg').is_file())
        self.assertFalse((self.out/'middle-files'/'synthesis'/'claim_ledger.json').read_text().count('phantom/Missing.java:999'))
        self.assertNotIn('phantom/Missing.java:999',(self.out/'system_knowledge_report.md').read_text())
        self.assertTrue((self.out/'middle-files'/'synthesis'/'manifest.json').is_file())
        second=LocalCallBudget(TinyLocalModel(),self.out,max_calls=12)
        again=synthesize(self.repo,self.out,second,review_rounds=2)
        self.assertEqual(again['status'],'completed')
        self.assertEqual(second.calls_used,0)
        self.assertGreater(again['checkpoints_reused'],0)

    def test_cli_integrated_phases_local_only(self):
        from architecture import export_architecture
        from module_summary import summarize_modules
        with patch('agent.print_ram_status'),patch('agent.Ollama',return_value=TinyLocalModel()),\
             redirect_stdout(StringIO()) as output:
            status=main(['--project',str(self.src),'architecture',
                        '--auto-investigate-top','1','--synthesize',
                        '--max-llm-calls','45','--out',str(self.out)])
        self.assertEqual(status,0,output.getvalue()[-500:])
        self.assertTrue((self.out/'middle-files'/'investigations'/'manifest.json').exists())
        self.assertTrue((self.out/'middle-files'/'workflow'/'call_audit.jsonl').exists())
        self.assertTrue((self.out/'system_knowledge_report.md').exists())
        self.assertTrue(any(x['kind']=='investigation' for x in gather_evidence(self.repo,self.out)['records']))
        self.assertTrue((self.out/'investigations'/'INV-001'/'result.md').exists())


if __name__=='__main__':unittest.main()
