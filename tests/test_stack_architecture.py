import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from architecture import export_architecture
from stack_architecture import export_stack_architecture
from codebase import Repo

class StackArchitectureTests(unittest.TestCase):
    def test_flex_spring_mybatis_postgres_and_diagrams(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'repo'
            (src/'ui').mkdir(parents=True);(src/'server').mkdir()
            (src/'pom.xml').write_text('''<project><dependencies>
            <dependency><groupId>org.springframework</groupId><artifactId>spring-webmvc</artifactId><version>5.3</version></dependency>
            <dependency><groupId>org.mybatis</groupId><artifactId>mybatis</artifactId><version>3</version></dependency>
            <dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId><version>42</version></dependency>
            </dependencies></project>''',encoding='utf8')
            (src/'ui'/'OrderScreen.mxml').write_text('<s:Application xmlns:s="library://ns.adobe.com/flex/spark"><s:Button label="Go"/></s:Application>',encoding='utf8')
            (src/'ui'/'OrderProxy.as').write_text('package ui { import mx.rpc.remoting.RemoteObject; public class OrderProxy {} }',encoding='utf8')
            (src/'server'/'OrderController.java').write_text('package server;\nimport org.springframework.web.bind.annotation.RestController;\n@RestController public class OrderController {}',encoding='utf8')
            (src/'server'/'OrderService.java').write_text('package server;\nimport server.OrderController;\n@org.springframework.stereotype.Service public class OrderService {}',encoding='utf8')
            (src/'server'/'OrderMapper.xml').write_text('<mapper namespace="server.OrderMapper"><select id="all">select * from orders</select></mapper>',encoding='utf8')
            (src/'server'/'OrderMapper.java').write_text('package server;\npublic interface OrderMapper {}',encoding='utf8')
            (src/'server'/'application.properties').write_text('spring.datasource.url=jdbc:postgresql://localhost/test',encoding='utf8')
            out=Path(tmp)/'out';repo=Repo(src)
            export_architecture(repo,out,verbose=False)
            result=export_stack_architecture(repo,out,verbose=False)
            self.assertIn('Apache Flex',result['frameworks_detected'])
            self.assertIn('Spring MVC / Core',result['frameworks_detected'])
            self.assertIn('MyBatis',result['frameworks_detected'])
            self.assertIn('PostgreSQL',result['databases_detected'])
            data=json.loads((out/'middle-files/stack_architecture.json').read_text('utf8'))
            self.assertEqual(data['layers']['FE'],2)
            self.assertGreaterEqual(data['layers']['BE'],3)
            self.assertEqual(data['frameworks']['Spring MVC / Core']['confidence'],'source-signature')
            self.assertEqual(data['databases']['PostgreSQL']['confidence'],'connection-string-or-driver')
            for key in ['fe_diagram','be_diagram','fe_reference','be_reference','fe_be_diagram']:
                self.assertEqual(ET.parse(result[key]).getroot().tag,'mxfile')
            self.assertIn('Objects', (out/'stack_architecture.md').read_text('utf8'))

    def test_no_invented_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'repo';src.mkdir()
            (src/'query.sql').write_text('select * from orders;',encoding='utf8')
            repo=Repo(src);out=Path(tmp)/'out'
            export_architecture(repo,out,verbose=False)
            data=export_stack_architecture(repo,out,verbose=False)
            self.assertEqual(data['databases_detected'],[])

if __name__=='__main__':unittest.main()
