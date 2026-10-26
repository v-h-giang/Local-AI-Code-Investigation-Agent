"""v4.3: reuse architecture graph as the source of module context."""
import json
import tempfile
import unittest
from pathlib import Path
from architecture import export_architecture, load_architecture
from module_summary import summarize_modules
from codebase import Repo

class SpyLLM:
    model='qwen3:8b'
    num_ctx=2048
    def __init__(self):self.prompts=[]
    def call(self,messages,**kwargs):
        self.prompts.append(messages[-1]['content'])
        return {'content':'Vai trò dựa trên source và graph; runtime chưa được xác minh.'}

class GraphSummaryTests(unittest.TestCase):
    def test_graph_dependencies_comments_caching_and_source_changes(self):
        with tempfile.TemporaryDirectory() as root:
            src=Path(root)/'project'
            for name in ['service','data']:(src/name).mkdir(parents=True)
            (src/'pom.xml').write_text('<project><dependencies><dependency><groupId>org.mybatis</groupId><artifactId>mybatis</artifactId><version>3.5</version></dependency></dependencies></project>',encoding='utf-8')
            (src/'service'/'OrderService.java').write_text('package demo;\n/** Handles order lifecycle processing. */\nimport demo.OrderMapper;\npublic class OrderService { private OrderMapper mapper; }',encoding='utf-8')
            (src/'data'/'OrderMapper.java').write_text('package demo;\npublic interface OrderMapper {}',encoding='utf-8')
            (src/'data'/'OrderMapper.xml').write_text('<mapper namespace="demo.OrderMapper"><select id="find">SELECT * FROM orders</select></mapper>',encoding='utf-8')
            repo=Repo(src)
            out=Path(root)/'out'
            first=export_architecture(repo,out,verbose=False)
            self.assertFalse(first['reused_graph'])
            second=export_architecture(repo,out,verbose=False)
            self.assertTrue(second['reused_graph'])
            llm=SpyLLM()
            result=summarize_modules(repo,out,llm=llm,verbose=False)
            self.assertTrue(result['graph_reused_for_summary'])
            self.assertEqual(len(llm.prompts),3)
            combined='\n'.join(llm.prompts)
            self.assertIn('service/OrderService.java:3 -> data/OrderMapper.java',combined)
            self.assertIn('mapper-namespace',combined)
            self.assertIn('library: org.mybatis:mybatis',combined)
            self.assertIn('repository-declared, module use unverified',combined)
            self.assertIn('service/OrderService.java:2',combined)
            self.assertIn('SQL table: orders',combined)
            evidence=json.loads((out/'middle-files'/'module_summary.json').read_text(encoding='utf-8'))
            self.assertEqual(evidence['modules']['service']['graph_context']['outgoing_total'],2)
            self.assertEqual(evidence['modules']['data']['graph_context']['incoming_total'],2)
            again=summarize_modules(repo,out,llm=llm,verbose=False)
            self.assertEqual(again['ai_cached'],3)
            self.assertEqual(len(llm.prompts),3)
            changed=src/'service'/'OrderService.java'
            changed.write_text(changed.read_text(encoding='utf-8')+'\n// new behavior documentation\n',encoding='utf-8')
            self.assertIsNone(load_architecture(repo,out))
            rebuilt=export_architecture(repo,out,verbose=False)
            self.assertFalse(rebuilt['reused_graph'])
            summarize_modules(repo,out,llm=llm,verbose=False)
            self.assertGreater(len(llm.prompts),3)

if __name__=='__main__':unittest.main()
