import json
import tempfile
import unittest
from pathlib import Path
from codebase import Repo
from code_intelligence import (build_intelligence, investigate, _normalize_plan,
                               _extract_plan_json)


class FakeQwen:
    model = 'qwen3:8b'
    num_ctx = 2048
    def __init__(self, plan=None):
        self.calls=[]
        self.plan=plan if plan is not None else {
            'intent':'locate','queries':['order service','processOrder'],
            'symbols':['OrderService','processOrder'],'graph_depth':2,
            'analysis_goals':['locate method']}
    def call(self,messages,tools=False,num_predict=None,**kwargs):
        self.calls.append({'messages':messages,'num_predict':num_predict})
        if len(self.calls)==1:
            return {'content':json.dumps(self.plan)} if isinstance(self.plan,dict) else {'content':self.plan}
        return {'content':'OrderService được tìm thấy tại backend/OrderService.java:2; cần xác minh runtime.'}


class AIInvestigationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)/'source'
        (root/'backend').mkdir(parents=True)
        (root/'backend'/'OrderService.java').write_text(
            'package backend;\npublic class OrderService {\n public void processOrder() { validateOrder(); }\n private void validateOrder() {}\n}\n',encoding='utf-8')
        self.repo=Repo(root)
        self.repo.intelligence_db=Path(self.temp.name)/'middle-files'/'code_intelligence.sqlite'
        build_intelligence(self.repo,Path(self.temp.name),verbose=False)
    def tearDown(self):
        self.temp.cleanup()

    def test_two_qwen_calls_and_source_evidence(self):
        llm=FakeQwen()
        answer=investigate(self.repo,'Chức năng xử lý đơn hàng nằm ở đâu?',llm,budget=900)
        self.assertGreaterEqual(len(llm.calls),2)
        self.assertEqual(answer['planning_method'],'qwen-json-plan')
        self.assertEqual(answer['plan']['intent'],'locate')
        self.assertTrue(any('backend/OrderService.java' in s for s in answer['source_citations']))
        self.assertTrue(any('backend/OrderService.java' in str(call['messages']) for call in llm.calls[1:]))
        self.assertEqual(answer['answer_status'],'qwen-grounded-attempt')
        self.assertLessEqual(answer['estimated_tokens'],900)
        self.assertEqual(llm.calls[0]['num_predict'],220)
        self.assertEqual(llm.calls[-1]['num_predict'],340)

    def test_non_ai_remains_one_stage_and_never_calls_model(self):
        result=investigate(self.repo,'OrderService',budget=600)
        self.assertNotIn('answer',result)
        self.assertIn('SQLite FTS5',result['retriever'])

    def test_malformed_planner_fallback(self):
        llm=FakeQwen('this is not json')
        answer=investigate(self.repo,'Where is OrderService?',llm,budget=900)
        self.assertEqual(answer['planning_method'],'lexical-fallback')
        self.assertTrue(answer['planning_error'])
        self.assertGreaterEqual(len(llm.calls),2)

    def test_planner_untrusted_and_bounded(self):
        normalized=_normalize_plan({'intent':'shell','queries':['rm -rf /','processOrder']*8,
            'symbols':['OrderService','../../secret','doNotExist'], 'graph_depth':9999},'find')
        self.assertEqual(normalized['intent'],'locate')
        self.assertNotIn('../../secret',normalized['symbols'])
        self.assertLessEqual(len(normalized['queries']),4)
        self.assertEqual(normalized['graph_depth'],3)
        self.assertEqual(_extract_plan_json('```json\n{"intent":"trace"}\n```')['intent'],'trace')

    def test_no_evidence_avoids_answer_call(self):
        llm=FakeQwen({'intent':'locate','queries':['zyxunknownthing987'],
                      'symbols':['zyxunknownthing987'],'graph_depth':2})
        result=investigate(self.repo,'zyxunknownthing987',llm,budget=900)
        self.assertEqual(result['answer_status'],'insufficient-evidence')
        self.assertGreaterEqual(len(llm.calls),1)
        self.assertFalse(any(call['num_predict']==340 for call in llm.calls[1:]))

if __name__=='__main__':unittest.main()
