import json
import tempfile
import unittest
from pathlib import Path
from codebase import Repo
from code_intelligence import build_intelligence,investigate
from investigation_loop import _validate_action, parse_json


class ScriptedQwen:
    def __init__(self, decisions):
        self.decisions=list(decisions)
        self.calls=[]
    def call(self,messages,tools=False,num_predict=None,**kwargs):
        self.calls.append((num_predict,messages))
        if num_predict==220:
            return {'content':json.dumps({'intent':'impact','symbols':['saveOrder'],
                'queries':['OrderService','saveOrder'],'graph_depth':2})}
        if num_predict==180:
            d=self.decisions.pop(0) if self.decisions else {'action':'finish'}
            return {'content':json.dumps(d)}
        return {'content':'Có định nghĩa tại backend/OrderService.java:4; không có bằng chứng xác minh runtime.'}

class IterativeInvestigationTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        src=Path(t.name)/'src';(src/'backend').mkdir(parents=True)
        (src/'backend'/'OrderService.java').write_text('''package backend;
public class OrderService {
 public void processOrder() { saveOrder(); }
 private void saveOrder() { }
}
''',encoding='utf8')
        self.repo=Repo(src)
        self.repo.intelligence_db=Path(t.name)/'middle-files'/'code_intelligence.sqlite'
        build_intelligence(self.repo,Path(t.name),verbose=False)

    def test_followup_tool_selected_by_qwen(self):
        model=ScriptedQwen([{'action':'tool','tool':'impact','query':'saveOrder','depth':3},
                            {'action':'tool','tool':'search','query':'OrderService'},
                            {'action':'finish'}])
        result=investigate(self.repo,'What is affected by saveOrder?',model,budget=1200,max_steps=5)
        self.assertEqual(result['investigation_mode'],'iterative-qwen-tools')
        self.assertEqual([x['tool'] for x in result['steps']],['symbol','impact','search'])
        self.assertTrue(result['source_citations'])
        self.assertEqual(result['answer_status'],'qwen-grounded-attempt')
        self.assertLessEqual(result['estimated_tokens'],result['token_budget'])
        self.assertEqual(model.calls[0][0],220)
        self.assertEqual(model.calls[-1][0],340)

    def test_bounded_and_denies_code_execution(self):
        model=ScriptedQwen([{'action':'tool','tool':'shell','query':'rm -rf /'}]*6)
        result=investigate(self.repo,'Explain saveOrder',model,budget=500,max_steps=2)
        self.assertLessEqual(result['steps_used'],2)
        self.assertNotIn('shell',[v['tool'] for v in result['steps']])
        self.assertIsNone(_validate_action({'tool':'history','query':'../secrets'}))
        self.assertIsNone(_validate_action({'tool':'symbol','query':'service.execute()'}))
        self.assertEqual(parse_json('```json\n{"action":"finish"}\n```')['action'],'finish')

    def test_stop_on_no_evidence_without_synthesis(self):
        model=ScriptedQwen([{'action':'finish'}])
        # Planner fake returns a known symbol, so explicitly drive an unmatched plan.
        orig_call=model.call
        def no_matches(messages,tools=False,num_predict=None,**kwargs):
            if num_predict==220:
                model.calls.append((num_predict,messages))
                return {'content':json.dumps({'intent':'locate','symbols':['Unfound999'],
                    'queries':['NoSuchSymbol999'],'graph_depth':1})}
            return orig_call(messages,tools,num_predict,**kwargs)
        model.call=no_matches
        result=investigate(self.repo,'Unfound999',model,budget=900)
        self.assertEqual(result['answer_status'],'insufficient-evidence')
        self.assertFalse(any(n==340 for n,_ in model.calls))

if __name__=='__main__':unittest.main()
