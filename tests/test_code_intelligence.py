import subprocess
import tempfile
import unittest
from pathlib import Path
from codebase import Repo
from code_intelligence import (build_intelligence, symbol_query, search_intelligence, trace,
                               impact, clusters, business_flows, retrieval_plan, git_history)

class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        src=Path(self.tmp.name)/'code'
        (src/'backend').mkdir(parents=True)
        (src/'frontend').mkdir()
        (src/'backend'/'OrderService.java').write_text('''package acme;
public class OrderService {
 public void processOrder() { saveOrder(); }
 private void saveOrder() { }
}
''',encoding='utf8')
        (src/'frontend'/'OrderView.as').write_text('''package ui { public class OrderView {
 public function processOrder():void { }
}}
''',encoding='utf8')
        (src/'backend'/'OrderMapper.xml').write_text('<mapper namespace="acme.OrderMapper">\n<select id="fetch">SELECT * FROM orders</select>\n</mapper>',encoding='utf8')
        self.repo=Repo(src,db_path=Path(self.tmp.name)/'index.sqlite')
        self.out=Path(self.tmp.name)/'results'

    def test_incremental_symbol_search_calls_impact_and_flow(self):
        first=build_intelligence(self.repo,self.out,verbose=False)
        self.assertEqual(first['changed_files'],3)
        self.assertGreater(first['symbols'],0)
        self.assertEqual(build_intelligence(self.repo,self.out,verbose=False)['changed_files'],0)
        self.assertEqual(len(symbol_query(self.repo,'saveOrder')['definitions']),1)
        search=search_intelligence(self.repo,'saveOrder')
        self.assertTrue(any(x['path'].endswith('OrderService.java') for x in search))
        graph=trace(self.repo,'processOrder')
        # The ActionScript declaration must not masquerade as a Java caller.
        self.assertTrue(any('calls-candidate' in str(p['evidence']) for p in graph['paths']))
        self.assertGreaterEqual(impact(self.repo,'saveOrder')['potentially_impacted_nodes'],1)
        self.assertIsInstance(clusters(self.repo),list)
        flow=business_flows(self.repo)
        self.assertFalse(flow['cross_layer_runtime_verified'])
        self.assertTrue(any(x['table_name']=='orders' for x in flow['sql_tables']))
        self.assertFalse(any(x.get('confidence')=='verified-runtime' for x in flow['flow_candidates']))
        plan=retrieval_plan(self.repo,'saveOrder',budget=300)
        self.assertLessEqual(plan['estimated_tokens'],300)
        target=self.repo.root/'backend'/'OrderService.java'
        target.write_text(target.read_text()+'\npublic class Dummy {}\n',encoding='utf8')
        self.assertEqual(build_intelligence(self.repo,self.out,verbose=False)['changed_files'],1)
        self.assertEqual(len(symbol_query(self.repo,'Dummy')['definitions']),1)
        target.unlink()
        self.assertEqual(build_intelligence(self.repo,self.out,verbose=False)['deleted_files'],1)
        self.assertEqual(symbol_query(self.repo,'Dummy')['definitions'],[])

    def test_git_history_offline(self):
        proc=subprocess.run(['git','init','-q',str(self.repo.root)],capture_output=True)
        if proc.returncode:self.skipTest('git not available')
        for key,value in [('user.email','local@example.com'),('user.name','Local Test')]:
            subprocess.run(['git','-C',str(self.repo.root),'config',key,value],check=True)
        subprocess.run(['git','-C',str(self.repo.root),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.repo.root),'commit','-qm','initial source'],check=True)
        items=git_history(self.repo,'backend/OrderService.java')
        self.assertTrue(items['commits'])
        self.assertEqual(items['commits'][0]['message'],'initial source')

if __name__=='__main__':unittest.main()
