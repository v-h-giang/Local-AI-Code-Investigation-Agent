import json
import tempfile
import unittest
from pathlib import Path
from codebase import Repo
from architecture import export_architecture

class ArchitectureTests(unittest.TestCase):
    def test_maven_and_import_mapper_edges_without_model(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'project'; (root/'api').mkdir(parents=True); (root/'data').mkdir()
            (root/'pom.xml').write_text('<project><dependencies><dependency><groupId>org.mybatis</groupId><artifactId>mybatis</artifactId><version>3.5</version></dependency></dependencies></project>',encoding='utf-8')
            (root/'api'/'OrderService.java').write_text('package example;\nimport example.OrderMapper;\npublic class OrderService { private OrderMapper mapper; }\n',encoding='utf-8')
            (root/'data'/'OrderMapper.java').write_text('package example;\npublic interface OrderMapper {}\n',encoding='utf-8')
            (root/'data'/'OrderMapper.xml').write_text('<mapper namespace="example.OrderMapper"><select id="list">select * from orders</select></mapper>',encoding='utf-8')
            out=Path(d)/'generated'; status=export_architecture(Repo(root),out,verbose=False)
            payload=json.loads((out/'architecture.json').read_text('utf-8'))
            self.assertEqual(status['files_scanned'],4)
            self.assertEqual(status['declared_dependencies'],1)
            self.assertTrue(any(x['kind']=='import' and x['confidence']=='exact' for x in payload['edges']))
            self.assertTrue(any(x['kind']=='mapper-namespace' and x['confidence']=='exact' for x in payload['edges']))
            self.assertTrue((out/'architecture.drawio').exists())
            self.assertIn('## Mục lục',(out/'architecture.md').read_text('utf-8'))

if __name__ == '__main__': unittest.main()
