"""Regression checks for the v4.17 human-readable HTML and Draw.io port change."""
import contextlib
import io
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from agent import main
from drawio_ports import distribute_ports_in_root, spread_drawio_ports
from report_render import ReportSession, markdown_html, render_file


class HtmlPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.project=self.root/'src'
        self.project.mkdir()
        (self.project/'OrderService.java').write_text('public class OrderService { void saveOrder() {} }\n',encoding='utf-8')
        self.out=self.root/'out'

    def run_cli(self,command='architecture',*args):
        buffer=io.StringIO()
        with patch('agent.print_ram_status'),patch('agent.Ollama',side_effect=AssertionError('No Qwen required')),contextlib.redirect_stdout(buffer):
            status=main(['--project',str(self.project),command,*args,'--out',str(self.out)])
        return status,buffer.getvalue()

    def test_html_is_default_and_md_source_is_in_middle_files(self):
        status,log=self.run_cli()
        self.assertEqual(status,0,log)
        for name in ('architecture','module_summary','stack_architecture','suggested_investigations'):
            self.assertTrue((self.out/(name+'.html')).is_file(),name)
            self.assertFalse((self.out/(name+'.md')).exists(),name)
            self.assertTrue((self.out/'middle-files'/'report-sources'/(name+'.md')).is_file(),name)
        self.assertNotIn('Markdown:',log)
        self.assertIn('"report_format": "html"',log)
        contents=(self.out/'architecture.html').read_text(encoding='utf-8')
        self.assertIn('<!doctype html>',contents)
        self.assertIn('<aside>',contents)
        self.assertIn('No AI tokens spent on HTML layout',contents)

    def test_choose_md_or_both_and_switch_without_rescanning(self):
        self.assertEqual(self.run_cli()[0],0)
        status,log=self.run_cli('architecture','--report-format','md')
        self.assertEqual(status,0,log)
        self.assertTrue((self.out/'architecture.md').exists())
        self.assertFalse((self.out/'architecture.html').exists())
        self.assertIn('"reused_graph": true',log)
        status,log=self.run_cli('architecture','--report-format','both')
        self.assertEqual(status,0,log)
        self.assertTrue((self.out/'architecture.md').exists())
        self.assertTrue((self.out/'architecture.html').exists())
        status,log=self.run_cli()
        self.assertEqual(status,0,log)
        self.assertFalse((self.out/'architecture.md').exists())
        self.assertTrue((self.out/'architecture.html').exists())

    def test_template_escapes_untrusted_text_and_converts_report_links(self):
        md='# Evidence <script>alert(1)</script>\n\n[Result](INV-001/result.md)\n\n![Diagram](investigation.svg)\n\n| File | Finding |\n|---|---|\n| `Foo.java:9` | A \\| B |\n\n```java\n<script>\n```\n'
        source=self.root/'source.md';dest=self.root/'report.html'
        source.write_text(md,encoding='utf-8')
        render_file(source,dest)
        html=dest.read_text(encoding='utf-8')
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertIn('INV-001/result.html',html)
        self.assertIn('<table>',html)
        self.assertIn('investigation.svg',html)
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('href="#"',markdown_html('[bad](javascript:foo)')[0])

    def test_single_investigation_html_and_optional_markdown(self):
        from unittest.mock import patch
        answer={'question':'Where?', 'answer':'OrderService.java:1 is present; runtime unverified.',
                'answer_status':'qwen-grounded-attempt','source_citations':['OrderService.java:1']}
        for fmt,expected in [('html',('html',)),('md',('md',)),('both',('md','html'))]:
            with patch('agent.print_ram_status'),patch('agent.Ollama'),patch('code_intelligence.investigate',return_value=answer),contextlib.redirect_stdout(io.StringIO()):
                status=main(['--project',str(self.project),'investigate','Where?',
                    '--report-format',fmt,'--out',str(self.out)])
            self.assertEqual(status,0)
            dirs=list((self.out/'investigations').glob('INV-Q-*'))
            self.assertEqual(len(dirs),1)
            for ext in ('html','md'):
                self.assertEqual((dirs[0]/('result.'+ext)).exists(),ext in expected)

    def test_machine_manifest_links_to_html_after_publication(self):
        import json
        inv=self.out/'investigations'/'INV-001'
        inv.mkdir(parents=True)
        (inv/'result.md').write_text('# One',encoding='utf-8')
        manifest=self.out/'middle-files'/'investigations'/'manifest.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'results':[{'id':'INV-001','markdown':str(inv/'result.md')}]})+'\n',encoding='utf-8')
        ReportSession(self.out).finalize()
        item=json.loads(manifest.read_text())['results'][0]
        self.assertEqual(item['html'],str(inv/'result.html'))
        self.assertNotIn('markdown',item)

    def test_report_session_investigation_links(self):
        out=self.out
        investigation=out/'investigations'/'INV-001'
        investigation.mkdir(parents=True)
        (investigation/'result.md').write_text('# Finding\n\n![Graph](investigation.svg)',encoding='utf-8')
        (investigation.parent/'index.md').write_text('# Index\n\n[Read](INV-001/result.md)',encoding='utf-8')
        session=ReportSession(out)
        session.finalize()
        self.assertFalse((investigation/'result.md').exists())
        self.assertTrue((investigation/'result.html').exists())
        self.assertIn('INV-001/result.html',(investigation.parent/'index.html').read_text())
        self.assertTrue((out/'middle-files'/'report-sources'/'investigations'/'INV-001'/'result.md').exists())
        session.restore()
        self.assertTrue((investigation/'result.md').exists())


class DrawioPortTests(unittest.TestCase):
    def _graph(self,links=12,box_w=230,box_h=110):
        root=ET.Element('root')
        for ident,x,y in [('hub',360,130)]+[(f'n{i}',0,i*42) for i in range(links)]:
            n=ET.SubElement(root,'mxCell',{'id':ident,'vertex':'1','parent':'1'})
            ET.SubElement(n,'mxGeometry',{'as':'geometry','x':str(x),'y':str(y),'width':str(box_w),'height':str(box_h)})
        for i in range(links):
            e=ET.SubElement(root,'mxCell',{'id':f'e{i}','edge':'1','source':f'n{i}','target':'hub','style':'edgeStyle=orthogonalEdgeStyle;endArrow=block;'})
            ET.SubElement(e,'mxGeometry',{'relative':'1','as':'geometry'})
        return root

    def test_unique_entry_anchors_until_perimeter_capacity_exhausted(self):
        root=self._graph(20)
        self.assertEqual(distribute_ports_in_root(root),40)
        edges=[e for e in root.findall('mxCell') if e.get('edge')=='1']
        entries=[]
        for edge in edges:
            style=dict(s.split('=',1) for s in edge.get('style').strip(';').split(';') if '=' in s)
            self.assertIn('entryX',style)
            self.assertIn('entryY',style)
            self.assertIn('exitX',style)
            self.assertIn('exitY',style)
            entries.append((style['entryX'],style['entryY']))
        self.assertEqual(len(entries),len(set(entries)))
        self.assertEqual(distribute_ports_in_root(root),40)
        entries2=[]
        for edge in edges:
            style=dict(s.split('=',1) for s in edge.get('style').strip(';').split(';') if '=' in s)
            entries2.append((style['entryX'],style['entryY']))
        self.assertEqual(entries,entries2)

    def test_reuse_only_when_total_ports_full(self):
        # 44x44 boxes have two slots per side: 8 distinct points.
        root=self._graph(15,box_w=44,box_h=44)
        distribute_ports_in_root(root)
        edges=[e for e in root.findall('mxCell') if e.get('edge')=='1']
        pairs=[]
        for edge in edges:
            props=dict(s.split('=',1) for s in edge.get('style').strip(';').split(';') if '=' in s)
            pairs.append((props['entryX'],props['entryY']))
        self.assertEqual(len(set(pairs)),8)
        self.assertLess(len(set(pairs)),len(pairs))

    def test_actual_architecture_xml_has_separated_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'demo.drawio'
            root=ET.Element('mxfile');diag=ET.SubElement(root,'diagram')
            model=ET.SubElement(diag,'mxGraphModel');model.append(self._graph(9))
            ET.ElementTree(root).write(path,encoding='utf-8')
            self.assertEqual(spread_drawio_ports(path),18)
            content=path.read_text(encoding='utf-8')
            self.assertIn('entryX=',content)
            self.assertIn('exitY=',content)
            self.assertEqual(len(ET.parse(path).findall('.//mxCell[@edge="1"]')),9)


if __name__=='__main__': unittest.main()
