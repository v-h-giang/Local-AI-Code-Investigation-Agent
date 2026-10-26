import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from stack_architecture import _draw


class DiagramLayoutTests(unittest.TestCase):
    def test_fe_be_db_lanes_and_arrows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'lanes.drawio'
            groups={'DB':1,'BE':3,'FE':2,'SHARED/UNKNOWN':1}
            _draw(path,'Observed layers',groups,Counter({('FE','BE'):2,('BE','DB'):3}),lane_mode=True)
            cells=list(ET.parse(path).getroot().iter('mxCell'))
            vertices={c.get('value'):c for c in cells if c.get('vertex')=='1'}
            def x(label):return float(vertices[label].find('mxGeometry').get('x'))
            self.assertLess(x('FE\n2 objects'),x('BE\n3 objects'))
            self.assertLess(x('BE\n3 objects'),x('DB\n1 objects'))
            self.assertIn('fillColor=#fff0dc',vertices['FE\n2 objects'].get('style'))
            self.assertIn('fillColor=#e4f0ff',vertices['BE\n3 objects'].get('style'))
            self.assertIn('fillColor=#e2f3e7',vertices['DB\n1 objects'].get('style'))
            edges=[c for c in cells if c.get('edge')=='1']
            self.assertEqual(len(edges),2)
            self.assertTrue(all('endSize=24' in e.get('style') and 'strokeWidth=3' in e.get('style') for e in edges))
            self.assertTrue(all('dashed=1' not in e.get('style') for e in edges))

    def test_reference_groups_by_framework_and_shows_real_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'reference.drawio'
            groups={
                'Spring MVC / Core: Controller / endpoint':{'count':1,'examples':['src/Controller.java']},
                'MyBatis: Mapper XML or annotation SQL':{'count':1,'examples':['src/Mapper.xml']},
                'Spring MVC / Core: Service / business rules':{'count':1,'examples':['src/Service.java']}
            }
            _draw(path,'Reference',groups,Counter({('Spring MVC / Core: Controller / endpoint',
                  'Spring MVC / Core: Service / business rules'):1}),reference=True)
            cells=list(ET.parse(path).getroot().iter('mxCell'))
            values=[c.get('value','') for c in cells]
            self.assertIn('Spring MVC / Core',values)
            self.assertIn('MyBatis',values)
            self.assertTrue(any('src/Controller.java' in val for val in values))
            self.assertTrue(any('src/Mapper.xml' in val for val in values))
            edges=[c for c in cells if c.get('edge')=='1']
            self.assertEqual(len(edges),1)
            self.assertIn('dashed=1',edges[0].get('style'))
            self.assertIn('endSize=24',edges[0].get('style'))


if __name__=='__main__':unittest.main()
