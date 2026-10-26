import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from architecture import export_architecture
from codebase import Repo
from stack_architecture import export_stack_architecture

class ReferenceObjectTests(unittest.TestCase):
    def test_reference_nodes_have_real_file_objects_and_missing_roles_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'project'
            (src/'fe').mkdir(parents=True)
            (src/'be').mkdir()
            (src/'fe'/'OrderScreen.mxml').write_text('<s:Application xmlns:s="library://ns.adobe.com/flex/spark"/>',encoding='utf8')
            (src/'be'/'OrderController.java').write_text('import org.springframework.web.bind.annotation.RestController;\n@RestController public class OrderController {}',encoding='utf8')
            out=Path(tmp)/'out'
            repo=Repo(src)
            export_architecture(repo,out,verbose=False)
            results=export_stack_architecture(repo,out,verbose=False)
            graph=json.loads((out/'middle-files'/'stack_architecture.json').read_text(encoding='utf8'))
            found=[x for x in graph['reference_role_coverage'].values() if x['status']=='found']
            missing=[x for x in graph['reference_role_coverage'].values() if x['status']=='not_found']
            self.assertTrue(found)
            self.assertTrue(missing)
            for name in ('fe_reference','be_reference'):
                root=ET.parse(results[name]).getroot()
                cells=[c for c in root.iter('mxCell') if c.get('vertex')=='1']
                self.assertTrue(cells)
                self.assertTrue(all('0 source objects' not in c.get('value','') for c in cells))
            fe=ET.parse(results['fe_reference']).getroot()
            self.assertTrue(any('fe/OrderScreen.mxml' in c.get('value','') for c in fe.iter('mxCell')))
            md=(out/'stack_architecture.md').read_text(encoding='utf8')
            self.assertIn('Không tìm thấy trong source đã quét',md)

if __name__=='__main__':unittest.main()
