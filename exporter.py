"""Generate editable Draw.io graph from verified static file references, plus Markdown reports."""
from __future__ import annotations
import re
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
from codebase import Repo
from agent_core import Investigator, Ollama

SQL_TABLE_RE = re.compile(r'(?i)\b(?:from|join|update|into|table)\s+([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)?)')


def candidates(repo: Repo, topic: str, max_count: int = 35) -> list[str]:
    found = repo.files(limit=6000)
    # If a topic is given, prefer files whose name or content contains that literal.
    scored = []
    for sf in found:
        if sf.fullpath.suffix.lower() not in ('.java', '.sql', '.as', '.mxml', '.xml'):
            continue
        if sf.fullpath.suffix.lower() == '.xml' and any(a in sf.path.lower() for a in ('pom.xml','log4j','beans.xml')):
            continue
        try: body = repo._read(sf.fullpath)
        except (ValueError, OSError): continue
        count = body.lower().count(topic.lower()) if topic else 1
        file_score = 10 if topic and topic.lower() in sf.path.lower() else 0
        if count or file_score:
            scored.append((file_score + min(count, 8), sf.path, body))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [x[1] for x in scored[:max_count]]


def inferred_edges(repo: Repo, paths: list[str]) -> list[tuple[str,str,str]]:
    """Only exact table/class-name textual associations (no guessed runtime calls)."""
    contents = {}
    for path in paths:
        try: contents[path] = repo._read(repo._safe(path))
        except (ValueError, OSError): continue
    edges = set()
    # SQL table edges: include references from embedded MyBatis XML, Java string SQL and SQL files.
    all_tables = Counter()
    for path, content in contents.items():
        for table in SQL_TABLE_RE.findall(content):
            all_tables[table.lower()] += 1
    for path, content in contents.items():
        for table in all_tables:
            if re.search(r'(?i)(?<![\w])' + re.escape(table) + r'(?![\w])', content):
                edges.add((path, 'TABLE:' + table, 'SQL text reference'))
    # Inter-file naming references are heuristic literal references, not verified function calls.
    for path, content in contents.items():
        for target in paths:
            if target == path: continue
            stem = Path(target).stem
            if len(stem) < 5: continue
            if re.search(r'(?<![\w])' + re.escape(stem) + r'(?![\w])', content):
                edges.add((path, target, 'Name reference'))
    return sorted(edges)


def drawio(repo: Repo, paths: list[str], out: Path) -> dict:
    """Fully editable diagrams.net XML. Labels explicitly mark textual, not runtime links."""
    edges = inferred_edges(repo, paths)
    table_nodes = sorted({b for _,b,_ in edges if b.startswith('TABLE:')})
    nodes = paths + table_nodes
    root = ET.Element('mxfile', {'host':'app.diagrams.net','type':'device'})
    diagram = ET.SubElement(root, 'diagram', {'id':'source-map','name':'Static references'})
    model = ET.SubElement(diagram, 'mxGraphModel', {'dx':'1200','dy':'800','grid':'1','gridSize':'10','page':'1','pageScale':'1','pageWidth':'2000','pageHeight':'1400'})
    r = ET.SubElement(model, 'root')
    ET.SubElement(r, 'mxCell', {'id':'0'})
    ET.SubElement(r, 'mxCell', {'id':'1','parent':'0'})
    color = {'.java':('#e6f0ff','#3465a4'), '.as':('#fff0d8','#c27c0e'), '.mxml':('#fff0d8','#c27c0e'), '.sql':('#e7f5e8','#348741'), '.xml':('#f1eaff','#7755aa')}
    idmap = {}
    # Layout: AIR, Java, SQL/XML, DB tables in columns
    lane_count = Counter()
    for i, path in enumerate(nodes):
        ident = 'n' + str(i + 2)
        idmap[path] = ident
        if path.startswith('TABLE:'):
            lane, label = 3, path[6:]
            bg, border = '#fce8e6', '#b94235'
        else:
            suffix = Path(path).suffix.lower()
            lane = 0 if suffix in ('.as','.mxml') else (1 if suffix == '.java' else 2)
            label = path
            bg, border = color.get(suffix,('#eeeeee','#555555'))
        y = lane_count[lane]*95 + 80
        lane_count[lane] += 1
        cell = ET.SubElement(r,'mxCell', {'id':ident, 'value':label,
            'style':f'rounded=1;whiteSpace=wrap;html=0;fillColor={bg};strokeColor={border};fontSize=12;align=center;verticalAlign=middle;',
            'vertex':'1','parent':'1'})
        ET.SubElement(cell,'mxGeometry', {'x':str(60+lane*460),'y':str(y),'width':'390','height':'65','as':'geometry'})
    for i,(a,b,label) in enumerate(edges):
        if a not in idmap or b not in idmap: continue
        cell=ET.SubElement(r,'mxCell', {'id':'e'+str(i+2), 'value':label,
            'style':'edgeStyle=orthogonalEdgeStyle;rounded=1;html=0;endArrow=block;endFill=1;strokeColor=#7a7a7a;fontSize=10;',
            'edge':'1','parent':'1','source':idmap[a],'target':idmap[b]})
        ET.SubElement(cell,'mxGeometry',{'relative':'1','as':'geometry'})
    out.parent.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(root).write(out, encoding='utf-8', xml_declaration=True)
    return {'files':len(paths),'table_nodes':len(table_nodes),'reference_edges':len(edges),'diagram':str(out)}


def toc(markdown: str) -> str:
    """Insert explicit stable anchors and a clickable table of contents, preserving body text."""
    used = {}
    lines = markdown.splitlines()
    transformed, links = [], []
    in_code = False
    for line in lines:
        if line.lstrip().startswith('```'):
            in_code = not in_code
        match = re.match(r'^(#{1,3})\s+(.+?)\s*$', line) if not in_code else None
        if match:
            title = match.group(2).strip()
            stem = re.sub(r'[^a-z0-9]+','-', title.lower()).strip('-') or 'section'
            used[stem] = used.get(stem,0)+1
            slug = stem if used[stem] == 1 else f'{stem}-{used[stem]}'
            transformed.append(f'<a id="{slug}"></a>')
            if match.group(1) != '#':
                links.append('  '*(len(match.group(1))-2)+f'- [{title}](#{slug})')
        transformed.append(line)
    if not links:
        return '\n'.join(transformed)+'\n'
    return '## Mục lục\n\n'+'\n'.join(links)+'\n\n---\n\n'+'\n'.join(transformed)+'\n'


def inventory_markdown(repo: Repo, topic: str, paths: list[str], meta: dict) -> str:
    kinds = Counter(Path(p).suffix.lower() for p in paths)
    edges = inferred_edges(repo, paths)
    out = ['# Báo cáo phân tích source code (tĩnh)', '',
           '> Đây là kết quả dò tham chiếu dạng text, KHÔNG phải call graph runtime đã được xác minh.', '',
           f'- Project: `{repo.root.name}`', f'- Chủ đề lọc: `{topic or "(all)"}`',
           f'- Ngày xuất: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
           f'- Phạm vi: {len(paths)} source files (giới hạn tối đa 35)', '',
           '## Danh sách source', '',
           '| Đường dẫn | Loại |', '|---|---|']
    for p in paths:
        out.append(f'| `{p.replace("|", " ")}` | `{Path(p).suffix}` |')
    out.extend(['','## Tham chiếu phát hiện được', '', '| Source | Target | Bằng chứng |','|---|---|---|'])
    for a,b,label in edges[:150]:
        out.append(f'| `{a}` | `{b}` | {label} (so khớp tên hoặc SQL) |')
    if not edges: out.append('| (Chưa tìm được) | | |')
    out += ['','## Giới hạn và cần xác minh','',
            '- Quan hệ tên gọi và SQL text là dấu hiệu tham chiếu, không đủ để kết luận thứ tự gọi hàm hoặc hành vi runtime.',
            '- SQL động, reflection, Dependency Injection, remoting AIR, mapper framework có thể không được phát hiện.',
            '- Sơ đồ Draw.io tương ứng là **editable**, các mũi tên thể hiện tham chiếu tĩnh, không chứng minh data flow.',
            '- Khi cần thiết kế chức năng chi tiết, dùng lệnh `design --topic ...` để AI điều tra và tạo bản thảo có dẫn chứng.']
    return toc('\n'.join(out))


def export_static(repo: Repo, topic: str, target_dir: str | Path) -> dict:
    out = Path(target_dir).expanduser().resolve()
    out.mkdir(parents=True,exist_ok=True)
    paths = candidates(repo, topic)
    diagram_meta = drawio(repo, paths, out/'source_references.drawio')
    (out/'source_inventory.md').write_text(inventory_markdown(repo,topic,paths,diagram_meta),encoding='utf-8')
    return {**diagram_meta, 'inventory':str(out/'source_inventory.md')}


def export_design(repo: Repo, model: Ollama, topic: str, target_dir: str | Path, verbose: bool = True) -> dict:
    if not topic.strip(): raise ValueError('Design topic cannot be empty')
    data = export_static(repo,topic,target_dir)
    inv = Investigator(repo, model, verbose=verbose)
    request = (f'Điều tra chức năng "{topic}" qua Java, Adobe AIR AS3/MXML và SQL/XML mapper. '
               'Hãy truy vết: UI event -> controller/service -> DAO/mapper -> SQL/table, '
               'chỉ nối các bước có bằng chứng, đọc đủ file liên quan, không phỏng đoán. '
               'Trả về: Tổng quan, entry points, bảng mapping UI/backend/SQL, chi tiết xử lý, dependencies, lỗi/rủi ro, '
               'test cases dự kiến, unknowns, kèm trích dẫn path:line cho mọi kết luận.')
    findings = inv.ask(request)
    notes = '''# Tài liệu thiết kế / Code Investigation

> Bản thảo AI từ source code tĩnh. Cần review trước khi dùng làm tài liệu đặc tả chính thức.

## Mục tiêu và phạm vi

'''+f'Chủ đề: **{topic}**. Project: `{repo.root.name}`.\n\n'+'''## Kết quả điều tra có dẫn chứng

'''+findings+'''

## Sơ đồ chỉnh sửa được

Mở `source_references.drawio` bằng https://app.diagrams.net hoặc extension Draw.io trong VS Code. Các cạnh chỉ thể hiện **text references**, chưa xác nhận lời gọi runtime.

## Hạn chế phân tích

- Xem lại từng path:line trước khi chốt kết luận.
- Các tham chiếu động, dependency injection, remoting, SQL sinh động và cấu hình môi trường chưa được kiểm chứng.
- Không kết nối database hoặc chạy code nghiệp vụ ở phiên bản này.
'''
    target = Path(target_dir).expanduser().resolve() / 'design.md'
    target.write_text(toc(notes),encoding='utf-8')
    # Bounded investigation provenance for reproducibility; can include snippets (keep output private).
    audit = [{'tool':r['tool'],'args':r['args']} for r in inv.calls_log]
    (target.parent/'investigation_log.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    return {**data, 'design':str(target),'tool_calls':len(inv.calls_log)}
