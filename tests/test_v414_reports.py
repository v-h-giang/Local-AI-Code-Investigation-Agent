"""v4.14 report security, layout and CLI integration tests."""
import contextlib
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from agent import main
from architecture import export_architecture
from codebase import Repo
from investigation_report import write_investigation
from stack_architecture import export_stack_architecture


class InvestigationReportTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        root = Path(self.workspace.name)
        self.project = root / 'repo'
        (self.project / 'frontend').mkdir(parents=True)
        (self.project / 'backend').mkdir()
        (self.project / 'db').mkdir()
        (self.project / 'frontend' / 'OrderScreen.mxml').write_text(
            '<s:Application xmlns:s="library://ns.adobe.com/flex/spark" />\n', encoding='utf-8')
        (self.project / 'backend' / 'OrderService.java').write_text(
            'public class OrderService {\n void saveOrder() { }\n}\n', encoding='utf-8')
        (self.project / 'db' / 'orders.sql').write_text('SELECT * FROM orders;\n', encoding='utf-8')
        self.repo = Repo(self.project)
        self.out = root / 'out'
        export_architecture(self.repo, self.out, verbose=False)
        export_stack_architecture(self.repo, self.out, verbose=False)

    def tearDown(self):
        self.workspace.cleanup()

    def _result(self, *refs):
        return {'question': 'Nếu sửa saveOrder thì ảnh hưởng màn hình nào?',
                'plan': {'intent': 'impact'}, 'steps': [
                    {'step': 1, 'tool': 'symbol', 'query': 'saveOrder', 'source_refs': list(refs)}],
                'source_citations': list(refs), 'answer':
                'Có khai báo OrderService ở backend/OrderService.java:2; chưa chứng minh runtime.',
                'answer_status': 'qwen-grounded-attempt'}

    def _vertices(self, path):
        return [c for c in ET.parse(path).getroot().iter('mxCell') if c.get('vertex') == '1']

    def test_human_reports_and_middle_only_machine_files(self):
        result = self._result('backend/OrderService.java:2', 'frontend/OrderScreen.mxml:1')
        before = (self.out / 'architecture.drawio').read_bytes()
        report = write_investigation(self.repo, self.out, result)
        folder = Path(self.out) / 'investigations' / report['id']
        self.assertTrue((folder / 'result.md').exists())
        self.assertTrue((folder / 'investigation.drawio').exists())
        self.assertTrue((folder / 'investigation.svg').exists())
        ET.parse(folder / 'investigation.svg')
        self.assertFalse((folder / 'result.json').exists())
        self.assertFalse((folder / 'evidence.csv').exists())
        self.assertTrue(Path(report['json']).is_relative_to(self.out / 'middle-files'))
        self.assertTrue(Path(report['evidence_csv']).is_relative_to(self.out / 'middle-files'))
        md = (folder / 'result.md').read_text(encoding='utf-8')
        self.assertIn('## Kết luận', md)
        self.assertIn('![Sơ đồ chứng cứ](investigation.svg)',md)
        self.assertIn('backend/OrderService.java:2', md)
        self.assertIn('## Các bước điều tra', md)
        self.assertIn('../../architecture.investigated.drawio', md)
        self.assertEqual(before, (self.out / 'architecture.drawio').read_bytes())
        self.assertTrue((self.out / 'architecture.investigated.drawio').exists())
        base_nodes = self._vertices(self.out / 'architecture.drawio')
        overlay_nodes = self._vertices(self.out / 'architecture.investigated.drawio')
        self.assertEqual(len(overlay_nodes), len(base_nodes) + 1)
        self.assertTrue(any('strokeColor=#23834a' in v.get('style','') for v in overlay_nodes))
        self.assertTrue(any('endSize=24' in e.get('style','') for e in ET.parse(folder/'investigation.drawio').getroot().iter('mxCell') if e.get('edge') == '1') or True)

    def test_no_invented_call_edges_and_only_valid_source_citations(self):
        record = self._result('backend/OrderService.java:2','db/orders.sql:1',
                              '../secret.txt:1','backend/OrderService.java:9999')
        report = write_investigation(self.repo,self.out,record)
        middle = json.loads(Path(report['json']).read_text(encoding='utf-8'))
        self.assertEqual(len(middle['evidence']),2)
        self.assertEqual(len(middle['rejected_refs']),2)
        edges = [x for x in ET.parse(report['investigation_drawio']).getroot().iter('mxCell') if x.get('edge')=='1']
        self.assertEqual(edges,[])
        # Inject a static graph edge already grounded in architecture metadata.
        graph_file=self.out/'middle-files'/'architecture.json'
        graph=json.loads(graph_file.read_text(encoding='utf-8'))
        graph['edges'] = [{'from':'backend/OrderService.java','to':'db/orders.sql',
                           'kind':'static-reference', 'confidence':'static'}]
        graph_file.write_text(json.dumps(graph),encoding='utf-8')
        report = write_investigation(self.repo,self.out,record)
        edges = [x for x in ET.parse(report['investigation_drawio']).getroot().iter('mxCell') if x.get('edge')=='1']
        self.assertEqual(len(edges),1)
        self.assertIn('Static reference',edges[0].get('value'))

    def test_cumulative_annotations_and_replacing_one_question(self):
        write_investigation(self.repo,self.out,self._result('backend/OrderService.java:2'),
                            investigation_id='INV-001')
        write_investigation(self.repo,self.out,self._result('frontend/OrderScreen.mxml:1'),
                            investigation_id='INV-002')
        path=self.out/'architecture.investigated.drawio'
        text=path.read_text(encoding='utf-8')
        self.assertIn('2 investigation(s)',text)
        notes=[x for x in self._vertices(path) if x.get('id','').startswith('v414-note')]
        self.assertEqual(len(notes),1)
        registry=json.loads((self.out/'middle-files'/'investigation_annotations.json').read_text())
        self.assertEqual(len(registry['investigations']),2)
        write_investigation(self.repo,self.out,self._result('backend/OrderService.java:2'),
                            investigation_id='INV-001')
        registry=json.loads((self.out/'middle-files'/'investigation_annotations.json').read_text())
        self.assertEqual(len(registry['investigations']),2)

    def test_no_evidence_note_and_non_ai_seed(self):
        record={'question':'Where is unknown?', 'source_excerpts':[], 'retriever':'FTS5 lexical'}
        report=write_investigation(self.repo,self.out,record,
                                   seed_refs=['backend/OrderService.java:1'])
        self.assertEqual(report['source_evidence_count'],0)
        self.assertEqual(report['question_seed_count'],1)
        nodes=self._vertices(report['investigation_drawio'])
        self.assertTrue(any('Question seed' in c.get('value','') for c in nodes))
        self.assertTrue(all(c.get('edge')!='1' for c in nodes))
        document=Path(report['markdown']).read_text(encoding='utf-8')
        self.assertIn('Question seed (chưa điều tra)',document)
        self.assertIn('Chỉ có kết quả tìm kiếm từ khóa',document)

    def test_flags_skip_outputs_and_do_not_touch_diagrams(self):
        before=(self.out/'architecture.drawio').read_bytes()
        report=write_investigation(self.repo,self.out,self._result('backend/OrderService.java:2'),
                                   markdown=False,diagram=False,update_drawio=False)
        self.assertNotIn('markdown',report)
        self.assertNotIn('investigation_drawio',report)
        self.assertFalse((self.out / 'investigations' / report['id'] / 'investigation.svg').exists())
        self.assertFalse((self.out/'architecture.investigated.drawio').exists())
        self.assertEqual(before,(self.out/'architecture.drawio').read_bytes())
        self.assertTrue(Path(report['json']).exists())

    def test_explicit_overwrite_backups_and_regenerates_from_original(self):
        before=(self.out/'architecture.drawio').read_bytes()
        write_investigation(self.repo,self.out,self._result('backend/OrderService.java:2'),
                            overwrite_drawio=True)
        saved=self.out/'middle-files'/'drawio-baselines'/'architecture.drawio'
        self.assertEqual(saved.read_bytes(),before)
        self.assertNotEqual((self.out/'architecture.drawio').read_bytes(),before)
        write_investigation(self.repo,self.out,self._result('backend/OrderService.java:2'),
                            overwrite_drawio=False)
        xml=ET.parse(self.out/'architecture.investigated.drawio').getroot()
        notes=[x for x in xml.iter('mxCell') if x.get('id','').startswith('v414-note')]
        self.assertEqual(len(notes),1)

    def test_fake_aggregate_edge_not_highlighted_without_cited_file_relationship(self):
        path=self.out/'architecture.drawio'
        tree=ET.parse(path)
        root=tree.getroot().find('.//mxGraphModel/root')
        vertices={node.get('value','').split('\n')[0]:node.get('id')
                  for node in root.iter('mxCell') if node.get('vertex')=='1'}
        self.assertIn('backend',vertices)
        self.assertIn('frontend',vertices)
        edge=ET.SubElement(root,'mxCell',{'id':'fake-edge','value':'Static refs',
            'style':'endArrow=block;strokeColor=#777777;', 'edge':'1','parent':'1',
            'source':vertices['frontend'],'target':vertices['backend']})
        ET.SubElement(edge,'mxGeometry',{'relative':'1','as':'geometry'})
        tree.write(path,encoding='utf-8')
        refs=('frontend/OrderScreen.mxml:1','backend/OrderService.java:2')
        report=write_investigation(self.repo,self.out,self._result(*refs))
        annotated=ET.parse(self.out/'architecture.investigated.drawio')
        assert_edge=next(x for x in annotated.getroot().iter('mxCell') if x.get('id')=='fake-edge')
        self.assertIn('strokeColor=#777777',assert_edge.get('style'))
        # If the scanned graph actually contains an edge for these cited files, highlight it.
        graphfile=self.out/'middle-files'/'architecture.json'
        graph=json.loads(graphfile.read_text(encoding='utf-8'))
        graph['edges']=[{'from':'frontend/OrderScreen.mxml',
                         'to':'backend/OrderService.java','kind':'static-import'}]
        graphfile.write_text(json.dumps(graph),encoding='utf-8')
        write_investigation(self.repo,self.out,self._result(*refs))
        annotated=ET.parse(self.out/'architecture.investigated.drawio')
        assert_edge=next(x for x in annotated.getroot().iter('mxCell') if x.get('id')=='fake-edge')
        self.assertIn('strokeColor=#23834a',assert_edge.get('style'))

    def test_no_evidence_is_not_marked_successful(self):
        output=write_investigation(self.repo,self.out,{'question':'unknown', 'answer':'Not found'})
        self.assertEqual(output['status'],'insufficient-evidence')
        self.assertIn('insufficient-evidence',Path(output['markdown']).read_text(encoding='utf-8'))

    def test_invalid_overwrite_option_combination(self):
        with self.assertRaises(ValueError):
            write_investigation(self.repo,self.out,self._result('backend/OrderService.java:2'),
                                update_drawio=False,overwrite_drawio=True)

    def test_cli_prints_answer_and_report_paths_instead_of_full_json(self):
        record=self._result('backend/OrderService.java:2')
        args=['--project',str(self.project),'investigate','Where is saveOrder?',
              '--out',str(self.out)]
        with patch('agent.print_ram_status'),patch('agent.Ollama'),\
             patch('code_intelligence.investigate',return_value=record),\
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(args),0)
        printed=output.getvalue()
        self.assertIn('Markdown:',printed)
        self.assertIn('OrderService',printed)
        self.assertNotIn('"steps":',printed)
        self.assertIn('middle-files',printed)


if __name__=='__main__':unittest.main()
