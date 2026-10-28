"""Local, token-free HTML publication of existing Markdown reports.

Existing stages can continue producing Markdown for evidence/synthesis and
checkpoint reads. HTML is rendered by Python using a fixed, bundled template.
In HTML-only mode Markdown intermediates live under middle-files/report-sources
and are restored before the next command. No LLM is called for formatting.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from string import Template
from urllib.parse import urlsplit, urlunsplit

_TEMPLATE = Path(__file__).with_name('templates') / 'report.html'
_ROOT_REPORTS = {
    'architecture.md', 'module_summary.md', 'stack_architecture.md',
    'suggested_investigations.md', 'system_knowledge_report.md',
}


def report_files(out):
    root = Path(out)
    for name in sorted(_ROOT_REPORTS):
        path = root / name
        if path.is_file():
            yield path
    index = root / 'investigations' / 'index.md'
    if index.is_file():
        yield index
    investigations = root / 'investigations'
    if investigations.is_dir():
        for path in sorted(investigations.glob('*/result.md')):
            if path.is_file():
                yield path


def _url(url):
    url = html.unescape(str(url)).strip()
    parts = urlsplit(url)
    if parts.scheme not in ('', 'http', 'https') or parts.netloc and not parts.scheme:
        return '#'
    if url.startswith('//') or '\\' in url:
        return '#'
    # Replace relative MD links only; links to versioned README are not reports.
    if parts.scheme == '' and parts.path.lower().endswith('.md'):
        url = urlunsplit(('', '', parts.path[:-3] + '.html', parts.query, parts.fragment))
    return html.escape(url, quote=True)


def _inline(value):
    """Safe constrained Markdown inline renderer: no raw HTML or active URLs."""
    pieces = []
    def store(chunk):
        key = f'\x01{len(pieces)}\x02'
        pieces.append(chunk)
        return key
    # Extract code before interpreting emphasis, links or markup.
    value = re.sub(r'`([^`\n]+)`',lambda m: store('<code>'+html.escape(m.group(1))+'</code>'), value)
    value = re.sub(r'!\[([^\]\n]*)\]\(([^\s)]+)\)',
                   lambda m: store('<img loading="lazy" alt="'+html.escape(m.group(1),quote=True)+'" src="'+_url(m.group(2))+'">'),value)
    value = re.sub(r'\[([^\]\n]+)\]\(([^\s)]+)\)',
                   lambda m: store('<a href="'+_url(m.group(2))+'">'+html.escape(m.group(1))+'</a>'),value)
    value = html.escape(value)
    value = re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',value)
    value = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)',r'<em>\1</em>',value)
    # Decode placeholders after escaping ordinary strings.
    return re.sub(r'\x01(\d+)\x02',lambda m:pieces[int(m.group(1))],value)


def _cells(row):
    return [part.strip().replace('\\|', '|') for part in re.split(r'(?<!\\)\|',row.strip().strip('|'))]


def markdown_html(markdown):
    """Convert the report Markdown subset to safe, standalone HTML fragments."""
    lines = markdown.splitlines()
    output, nav = [], []
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        code = re.match(r'^\s*```([\w+-]*)',raw)
        if code:
            lang = html.escape(code.group(1),quote=True)
            i += 1
            snippets = []
            while i < len(lines) and not lines[i].lstrip().startswith('```'):
                snippets.append(lines[i]); i += 1
            if i < len(lines):i += 1
            output.append(f'<pre><code class="language-{lang}">'+html.escape('\n'.join(snippets))+'</code></pre>')
            continue
        heading = re.match(r'^(#{1,6})\s+(.+)$',line)
        if heading:
            level, title = len(heading.group(1)),heading.group(2)
            hid = f'section-{len(nav)+1}'
            nav.append((hid, title, level))
            output.append(f'<h{level} id="{hid}">{_inline(title)}</h{level}>')
            i += 1;continue
        if re.match(r'^\|?\s*[:\-]+\s*\|',line) or line in ('---','***','___'):
            if line in ('---','***','___'):output.append('<hr>')
            i += 1;continue
        if line.startswith('|') and i + 1 < len(lines) and re.match(r'^\s*\|?\s*:?-+:?\s*\|',lines[i+1]):
            headers = _cells(line)
            output.append('<table><thead><tr>'+''.join('<th>'+_inline(c)+'</th>' for c in headers)+'</tr></thead><tbody>')
            i += 2
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = _cells(lines[i])
                output.append('<tr>'+''.join('<td>'+_inline(c)+'</td>' for c in cells)+'</tr>')
                i += 1
            output.append('</tbody></table>')
            continue
        if line.startswith('>'):
            quote=[]
            while i < len(lines) and lines[i].lstrip().startswith('>'):
                quote.append(lines[i].lstrip().lstrip('>').strip());i+=1
            output.append('<blockquote>'+''.join('<p>'+_inline(x)+'</p>' for x in quote)+'</blockquote>');continue
        if re.match(r'^[-*+]\s+',line) or re.match(r'^\d+[.)]\s+',line):
            ordered = bool(re.match(r'^\d+[.)]\s+',line))
            tag='ol' if ordered else 'ul'
            output.append('<'+tag+'>')
            while i < len(lines):
                item = lines[i].strip()
                m = re.match(r'^(?:[-*+]\s+|\d+[.)]\s+)(.*)$',item)
                if not m:break
                output.append('<li>'+_inline(m.group(1))+'</li>');i+=1
            output.append('</'+tag+'>')
            continue
        para=[line];i+=1
        while i < len(lines) and lines[i].strip() and not re.match(r'^\s*(?:#{1,6}\s|```|\||>|[-*+]\s|\d+[.)]\s)',lines[i]):
            para.append(lines[i].strip());i+=1
        output.append('<p>'+_inline(' '.join(para))+'</p>')
    return '\n'.join(output), nav


def render_file(source, output):
    markdown = Path(source).read_text(encoding='utf-8')
    body, nav = markdown_html(markdown)
    title = next((re.sub(r'[*`]', '',title) for _,title,_ in nav), Path(source).stem.replace('_',' ').title())
    navigation = '\n'.join('<a href="#'+hid+'" style="padding-left:'+str(min(4,level-1)*.5)+'rem">'+html.escape(title)+'</a>' for hid,title,level in nav)
    template = Template(_TEMPLATE.read_text(encoding='utf-8'))
    page = template.substitute(title=html.escape(title),content=body,navigation=navigation)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding='utf-8')
    return output


class ReportSession:
    """Restore Markdown evidence before the run, publish chosen outputs after."""
    def __init__(self, out, report_format='html'):
        if report_format not in ('html','md','both'):
            raise ValueError('Invalid --report-format')
        self.out=Path(out).expanduser().resolve()
        self.format=report_format
        self._finished=False
        self.sources=self.out/'middle-files'/'report-sources'

    def restore(self):
        if not self.sources.is_dir():return
        for source in sorted(self.sources.rglob('*.md')):
            relative=source.relative_to(self.sources)
            if self._supported(relative):
                target=self.out/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source,target)

    @staticmethod
    def _supported(rel):
        s=rel.as_posix()
        return s in _ROOT_REPORTS or s=='investigations/index.md' or bool(re.fullmatch(r'investigations/[^/]+/result\.md',s))

    def finalize(self):
        if self._finished:return
        from drawio_ports import spread_drawio_ports
        self.out.mkdir(parents=True,exist_ok=True)
        for source in list(report_files(self.out)):
            htmlpath=source.with_suffix('.html')
            if self.format in ('html','both'):
                render_file(source,htmlpath)
            elif htmlpath.is_file():
                htmlpath.unlink()
            if self.format=='html':
                stash=self.sources/source.relative_to(self.out)
                stash.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,stash)
                source.unlink()
        manifest=self.out/'middle-files'/'investigations'/'manifest.json'
        if manifest.is_file():
            try:
                data=json.loads(manifest.read_text(encoding='utf-8'))
                for entry in data.get('results',[]):
                    if not isinstance(entry,dict):continue
                    if self.format in ('html','both') and entry.get('markdown'):
                        entry['html']=str(Path(entry['markdown']).with_suffix('.html'))
                    if self.format=='html':
                        entry.pop('markdown',None)
                    elif self.format=='md':
                        entry.pop('html',None)
                manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            except (ValueError,OSError,TypeError):
                print('[Report] Existing investigation manifest could not be updated.',flush=True)
        # Existing Draw.io diagrams and overlays are updated by adding anchors,
        # without modifying edge sources/targets or adding inferred edges.
        diagrams=list(self.out.glob('*.drawio'))
        investigations=self.out/'investigations'
        if investigations.is_dir():diagrams += list(investigations.glob('*/investigation.drawio'))
        ports=0
        for path in diagrams:
            try:ports+=spread_drawio_ports(path)
            except Exception as exc:
                # A failed diagram must remain intact and independently editable.
                print(f'[Report] Draw.io port assignment skipped for {path.name}: {exc}',flush=True)
        self._finished=True
        if self.format!='md':
            print(f'[Report] HTML publication complete ({self.format}); Draw.io endpoints assigned: {ports}',flush=True)

    def report_paths(self,value):
        """Return paths for the public files, not their relocated Markdown source."""
        if isinstance(value,dict):
            result={}
            for key,entry in value.items():
                if key=='markdown' and self.format=='html' and isinstance(entry,str):
                    result['html']=entry[:-3]+'.html' if entry.endswith('.md') else entry
                else:
                    result[key]=self.report_paths(entry)
            return result
        if isinstance(value,list):return [self.report_paths(x) for x in value]
        if isinstance(value,str) and self.format=='html' and value.endswith('.md'):
            path=Path(value)
            try:rel=path.resolve().relative_to(self.out)
            except ValueError:return value
            if self._supported(rel):return str(path.with_suffix('.html'))
        return value
