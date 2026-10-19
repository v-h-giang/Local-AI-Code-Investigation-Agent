import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codebase import Repo
from agent_core import Investigator
from exporter import export_static, toc, export_design

SAMPLE = Path(__file__).resolve().parents[1] / 'sample_project'

class FakeLLM:
    def __init__(self): self.n = 0
    def call(self,messages,tools=True,**kwargs):
        self.n += 1
        if tools and self.n == 1:
            return {'role':'assistant','content':'','tool_calls':[{'type':'function','function':{'name':'search_code','arguments':{'query':'order_header'}}}]}
        return {'role':'assistant','content':'Trong backend/OrderMapper.xml:4 có truy vấn bảng order_header.'}

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repo(SAMPLE, Path(self.tmp.name)/'index.sqlite')

    def test_read_search_cross_language(self):
        self.assertIn('OrderService.java:5',self.repo.search_code('selectOrders'))
        self.assertIn('OrderScreen.mxml:5',self.repo.search_code('loadOrders'))
        self.assertIn('db/schema.sql:1',self.repo.sql_usage('order_header'))
        self.assertIn('selectOrders',self.repo.outline_file('backend/OrderMapper.xml'))
        self.assertIn('  5 |',self.repo.read_file('backend/OrderService.java',5,5))

    def test_restrict_external_files(self):
        with self.assertRaises(ValueError): self.repo.read_file('../agent.py')
        with self.assertRaises(ValueError): self.repo.read_file('C:/Windows/win.ini')
        with self.assertRaises(ValueError): self.repo.read_file('/etc/passwd')

    def test_index_persists_and_retrieves(self):
        details=self.repo.index()
        self.assertGreater(details['chunks'],0)
        self.assertTrue(Path(details['database']).is_file())
        self.assertIn('OrderMapper.xml',self.repo.semantic_search('selectOrders'))
        self.assertIn('OrderMapper.xml',Repo(SAMPLE,self.repo.db_path).semantic_search('selectOrders'))

    def test_investigator_tool_loop(self):
        inv = Investigator(self.repo,FakeLLM(),verbose=False)
        result=inv.ask('order_header?')
        self.assertIn('OrderMapper.xml:4',result)
        self.assertEqual(inv.calls_log[0]['tool'],'search_code')
        self.assertIn('order_header',inv.calls_log[0]['output'])
        self.assertEqual(inv.execute_tool('run_shell',{}),'Tool not allowed.')

    def test_output_valid_drawio_and_toc(self):
        import xml.etree.ElementTree as ET
        output=Path(self.tmp.name)/'out'
        meta=export_static(self.repo, 'Order', output)
        root=ET.parse(output/'source_references.drawio').getroot()
        self.assertEqual(root.tag, 'mxfile')
        self.assertGreater(meta['reference_edges'],0)
        self.assertTrue(any(e.get('value')=='order_header' for e in root.iter('mxCell')))
        readme=(output/'source_inventory.md').read_text('utf-8')
        self.assertIn('](#',readme)
        self.assertIn('Báo cáo phân tích source code',readme)

    def test_design_with_mock_model(self):
        output=Path(self.tmp.name)/'out'
        data=export_design(self.repo, FakeLLM(),'Order',output,verbose=False)
        self.assertTrue(Path(data['design']).exists())
        self.assertIn('## Mục lục',(output/'design.md').read_text('utf-8'))
        self.assertEqual(data['tool_calls'],1)

if __name__ == '__main__': unittest.main()
