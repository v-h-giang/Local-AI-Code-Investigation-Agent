import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from stack_architecture import _draw


class DiagramLayoutTests(unittest.TestCase):
    def _get_graph(self, path):
        root = ET.parse(path).getroot()
        cells = list(root.iter('mxCell'))
        return cells

    def test_lane_order_colors_and_big_arrows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'fe_be.drawio'
            groups = {'DB': {'count': 1}, 'BE': {'count': 3}, 'FE': {'count': 2},
                      'SHARED/UNKNOWN': {'count': 1}}
            links = Counter({('FE', 'BE'): 2, ('BE', 'DB'): 3})
            _draw(path, 'Observed', groups, links, lane_mode=True)
            cells = self._get_graph(path)
            by_value = {c.get('value'): c for c in cells if c.get('vertex') == '1'}
            def xpos(name):
                geometry = by_value[name].find('mxGeometry')
                return float(geometry.get('x'))
            self.assertLess(xpos('FE\n2 source objects'), xpos('BE\n3 source objects'))
            self.assertLess(xpos('BE\n3 source objects'), xpos('DB\n1 source objects'))
            self.assertIn('fillColor=#fff0dc', by_value['FE\n2 source objects'].get('style'))
            self.assertIn('fillColor=#e4f0ff', by_value['BE\n3 source objects'].get('style'))
            self.assertIn('fillColor=#e2f3e7', by_value['DB\n1 source objects'].get('style'))
            edges = [c for c in cells if c.get('edge') == '1']
            self.assertEqual(len(edges), 2)
            for edge in edges:
                style = edge.get('style')
                self.assertIn('endSize=24', style)
                self.assertIn('strokeWidth=3', style)
                self.assertNotIn('dashed=1', style)

    def test_reference_framework_columns_do_not_mix_edges(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'reference.drawio'
            groups = {
                'Spring MVC / Core: Controller / endpoint': {'count': 1, 'examples': ['src/Controller.java']},
                'MyBatis: Mapper XML or annotation SQL': {'count': 1, 'examples': ['src/Mapper.xml']},
                'Spring MVC / Core: Service / business rules': {'count': 1, 'examples': ['src/Service.java']},
            }
            links = Counter({('Spring MVC / Core: Controller / endpoint',
                              'Spring MVC / Core: Service / business rules'): 1})
            _draw(path, 'Reference', groups, links, reference=True)
            cells = self._get_graph(path)
            vertices = [c for c in cells if c.get('vertex') == '1']
            headers = [c for c in vertices if c.get('value') in ('Spring MVC / Core', 'MyBatis')]
            self.assertEqual(len(headers), 2)
            edges = [c for c in cells if c.get('edge') == '1']
            self.assertEqual(len(edges), 1)
            self.assertIn('dashed=1', edges[0].get('style'))
            self.assertIn('endSize=24', edges[0].get('style'))
            labels = [c.get('value', '') for c in vertices]
            self.assertTrue(any('src/Controller.java' in v for v in labels))
            self.assertTrue(any('src/Mapper.xml' in v for v in labels))


if __name__ == '__main__':
    unittest.main()
