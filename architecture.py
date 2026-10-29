"""Fast, read-only repository architecture inventory; no LLM, index or network needed.

Edges distinguish exact symbol resolution from tentative filename-based links.
"""
from __future__ import annotations
import csv
import json
import os
import re
import xml.etree.ElementTree as ET
import math
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from codebase import EXCLUDE_DIRS, MAX_BYTES, Repo

CODE_EXTS = {'.java','.as','.mxml','.sql','.xml','.jsp','.jspx','.xhtml','.fxml','.hbm',
             '.properties','.yaml','.yml','.toml','.py','.pyi','.cs','.csx','.md'}
CONFIG_NAMES = {'pom.xml','build.gradle','build.gradle.kts','settings.gradle','settings.gradle.kts',
                'gradle.properties','libs.versions.toml','ivy.xml','build.xml','application.xml',
                'air-app.xml','settings.xml','MANIFEST.MF'}
IGNORE_PACKAGES = ('java.', 'javax.', 'jdk.', 'sun.', 'com.sun.', 'flash.', 'mx.', 'spark.', 'org.w3c.', 'org.xml.')
JAVA_IMPORT = re.compile(r'^\s*import\s+(?:static\s+)?([\w.]+)(?:\.\*)?\s*;', re.M)
AS_IMPORT = re.compile(r'^\s*import\s+([\w.]+)(?:\.\*)?\s*;', re.M)
JAVA_PACKAGE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.M)
AS_PACKAGE = re.compile(r'\bpackage\s+([\w.]*)\s*\{', re.M)
CLASS_DEF = re.compile(r'\b(?:class|interface|enum)\s+(\w+)')
AS_CLASS = re.compile(r'\b(?:class|interface)\s+(\w+)')
XML_MAPPER_NS = re.compile(r'<mapper\b[^>]*\bnamespace=["\']([^"\']+)', re.I)
XML_STATEMENT = re.compile(r'<(?:select|update|insert|delete)\b[^>]*\bid=["\']([^"\']+)',re.I)
SQL_TABLE = re.compile(r'\b(?:from|join|update|into|table)\s+([A-Za-z_][\w.$]*)',re.I)
XML_CLASS = re.compile(r'\b(?:class|type|resultType|parameterType|ofType|javaType|interface|service|implementation|extends|implements)\s*=\s*["\']([\w.$]+)["\']')
CITATION = re.compile(r'([\w./-]+):(\d+)')


def _scan(root: Path):
    """Include dependency manifests even if their extensions aren't code-supported."""
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS and not (Path(base)/d).is_symlink())
        for name in sorted(names):
            path = Path(base)/name
            if path.is_symlink() or (path.suffix.lower() not in CODE_EXTS and name not in CONFIG_NAMES):
                continue
            try:
                if path.stat().st_size > MAX_BYTES:
                    continue
                yield path.relative_to(root).as_posix(), path
            except OSError:
                continue


def _module(path):
    bits = path.split('/')
    return bits[0] if len(bits) > 1 else '(root)'


def _xml_text(element, local):
    return next((x.text.strip() for x in element if x.tag.rsplit('}',1)[-1]==local and x.text and x.text.strip()),'')


def _extract_deps(path: str, text: str):
    deps = []
    low = path.lower()
    if low.endswith('pom.xml'):
        try:
            root = ET.fromstring(text)
            for node in root.iter():
                if node.tag.rsplit('}',1)[-1] != 'dependency':
                    continue
                group, artifact = _xml_text(node,'groupId'),_xml_text(node,'artifactId')
                if group and artifact:
                    deps.append((group+':'+artifact, _xml_text(node,'version'),'Maven'))
        except ET.ParseError:
            pass
    elif low.endswith(('.gradle','.gradle.kts')):
        patt = re.compile(r'\b(?:implementation|api|compileOnly|runtimeOnly|testImplementation|compile|classpath)\s*\(?\s*["\']([^"\']+:[^"\']+)["\']')
        deps += [(m.group(1).rsplit(':',1)[0],m.group(1).rsplit(':',1)[-1],'Gradle') for m in patt.finditer(text)]
    elif low.endswith('libs.versions.toml'):
        patt = re.compile(r'\bmodule\s*=\s*["\']([^"\']+)["\']')
        deps += [(m.group(1),'version catalog','Gradle') for m in patt.finditer(text)]
    elif low.endswith('ivy.xml'):
        try:
            root = ET.fromstring(text)
            for node in root.iter():
                if node.tag.rsplit('}',1)[-1]=='dependency':
                    deps.append((node.get('org','')+':'+node.get('name',''),node.get('rev',''),'Ivy'))
        except ET.ParseError:
            pass
    elif low.endswith('build.xml'):
        for match in re.finditer(r'\b(?:classpath|location)\s*=\s*["\']([^"\']+\.jar)["\']', text,re.I):
            deps.append((match.group(1),'','Ant JAR reference'))
    return deps


def _format_drawio(modules, edges, destination: Path, node_cap=100):
    """Draw.io top-level module graph with larger arrows and readable spacing."""
    top = sorted(modules.items(), key=lambda kv: (-kv[1]['count'], kv[0]))[:node_cap]
    names = [x[0] for x in top]
    identifiers = {name: f'm{i+2}' for i, name in enumerate(names)}
    graph = Counter()
    for edge in edges:
        a, b = _module(edge['from']), _module(edge['to'])
        if a != b and a in identifiers and b in identifiers:
            graph[a, b] += 1
    count = max(1, len(top))
    columns = 4 if count > 8 else (3 if count > 3 else 2)
    rows = max(1, math.ceil(count / columns))
    box_w, box_h = 470, 145
    gap_x, gap_y = 80, 75
    left, top_pad = 60, 80
    page_w = max(2200, left * 2 + columns * box_w + (columns - 1) * gap_x)
    page_h = max(1800, top_pad * 2 + rows * box_h + (rows - 1) * gap_y)
    root = ET.Element('mxfile', {'host': 'app.diagrams.net', 'type': 'device'})
    diagram = ET.SubElement(root, 'diagram', {'id': 'architecture', 'name': 'Static module dependencies'})
    model = ET.SubElement(diagram, 'mxGraphModel', {
        'dx': '1400', 'dy': '900', 'grid': '1', 'gridSize': '10', 'page': '1',
        'pageScale': '1', 'pageWidth': str(page_w), 'pageHeight': str(page_h)
    })
    group = ET.SubElement(model, 'root')
    ET.SubElement(group, 'mxCell', {'id': '0'})
    ET.SubElement(group, 'mxCell', {'id': '1', 'parent': '0'})
    for i, (name, info) in enumerate(top):
        c, r = i % columns, i // columns
        label = f'{name}\n{info["count"]} files\n' + ', '.join(k + ':' + str(v) for k, v in info['types'].most_common(3))
        cell = ET.SubElement(group, 'mxCell', {
            'id': identifiers[name], 'value': label,
            'style': 'rounded=1;whiteSpace=wrap;html=0;fillColor=#e8f0fb;strokeColor=#577398;'
                     'align=center;verticalAlign=middle;fontSize=14;fontStyle=1;spacing=8;'
                     'shadow=0;arcSize=10;',
            'vertex': '1', 'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(left + c * (box_w + gap_x)), 'y': str(top_pad + r * (box_h + gap_y)),
            'width': str(box_w), 'height': str(box_h), 'as': 'geometry'
        })
    for i, ((a, b), number) in enumerate(graph.most_common(250)):
        cell = ET.SubElement(group, 'mxCell', {
            'id': f'e{i+1000}', 'value': str(number),
            'style': 'edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=0;'
                     'endArrow=block;endFill=1;endSize=18;strokeWidth=2;strokeColor=#63758a;'
                     'fontSize=13;labelBackgroundColor=#ffffff;',
            'edge': '1', 'parent': '1', 'source': identifiers[a], 'target': identifiers[b]
        })
        ET.SubElement(cell, 'mxGeometry', {'relative': '1', 'as': 'geometry'})
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(destination, encoding='utf-8', xml_declaration=True)
    return len(graph), max(0, len(modules) - len(top))


def _source_inventory(root: Path):
    """Cheap tree fingerprint; checks path, size and nanosecond mtime, not file contents."""
    inventory=[]
    for rel, path in _scan(root):
        try:
            st=path.stat()
            inventory.append([rel,st.st_size,st.st_mtime_ns])
        except OSError:
            inventory.append([rel,-1,-1])
    return inventory


def _middle_dir(destination: Path) -> Path:
    """Store machine-readable intermediate files separately from final reports."""
    middle = destination / 'middle-files'
    middle.mkdir(parents=True, exist_ok=True)
    # Migrate v4.3 intermediates without discarding previously computed graph.
    for name in ('architecture.json', 'dependencies.csv', 'file_links.csv', 'module_summary.json'):
        legacy = destination / name
        updated = middle / name
        if legacy.is_file():
            if not updated.exists():
                legacy.replace(updated)
            else:
                legacy.unlink()
    old_cache = destination / '.module_summary_cache'
    new_cache = middle / '.module_summary_cache'
    if old_cache.is_dir() and not new_cache.exists():
        old_cache.replace(new_cache)
    elif old_cache.is_dir():
        # Merge existing caches without overwriting valid newer checkpoints.
        for file in old_cache.glob('*.json'):
            if not (new_cache / file.name).exists():
                file.replace(new_cache / file.name)
        try:
            old_cache.rmdir()
        except OSError:
            pass
    return middle


def load_architecture(repo: Repo, out: str | Path):
    """Return a previously generated graph only if same project/source metadata."""
    path=_middle_dir(Path(out).expanduser().resolve())/'architecture.json'
    if not path.is_file():
        return None
    try:
        graph=json.loads(path.read_text(encoding='utf-8'))
        if (graph.get('architecture_version') == 43 and
            graph.get('project') == str(repo.root) and
            graph.get('source_inventory') == _source_inventory(repo.root)):
            return graph
    except (OSError,ValueError,KeyError):
        pass
    return None


def export_architecture(repo: Repo, out: str | Path='output/architecture', verbose=True,
                        reuse=True):
    """Build fast static architecture. No index build, no AI calls."""
    destination=Path(out).expanduser().resolve()
    destination.mkdir(parents=True,exist_ok=True)
    middle=_middle_dir(destination)
    if reuse:
        existing=load_architecture(repo,destination)
        if existing is not None and all((destination/name).is_file() for name in
                ('architecture.md','architecture.drawio')) and all((middle/name).is_file() for name in
                ('dependencies.csv','file_links.csv')):
            if verbose: print('[Architecture] Source unchanged; reusing architecture.json',flush=True)
            return {'files_scanned': existing['files_scanned'], 'modules':len(existing['modules']),
                'declared_dependencies':len(existing['dependencies']), 'file_links':len(existing['edges']),
                'architecture':str(destination/'architecture.md'),
                'drawio':str(destination/'architecture.drawio'),
                'json':str(middle/'architecture.json'),
                'links_csv':str(middle/'file_links.csv'),
                'dependencies_csv':str(middle/'dependencies.csv'), 'reused_graph':True}
    module_counts=defaultdict(lambda:{'count':0,'types':Counter()})
    records=[]; by_symbol=defaultdict(list); by_simple=defaultdict(list)
    raw_imports=[]; mapper_links=[]; xml_refs=[]; raw_type_refs=[]; dependencies=[]; tables=defaultdict(set)
    external_imports=Counter()
    read_errors=[]
    for idx,(rel,p) in enumerate(_scan(repo.root),1):
        if verbose and idx%1000==0:
            print(f'[Architecture] Scanned {idx} files...',flush=True)
        module_counts[_module(rel)]['count']+=1
        module_counts[_module(rel)]['types'][p.suffix.lower() or p.name]+=1
        records.append(rel)
        try:
            text=repo._read(p)
        except (OSError,ValueError) as exc:
            read_errors.append({'file':rel,'error':str(exc)[:160]})
            continue
        dependencies.extend({'library':lib,'version':ver,'ecosystem':eco,'declared_in':rel} for lib,ver,eco in _extract_deps(rel,text))
        suffix=p.suffix.lower()
        if suffix in ('.java','.as','.mxml'):
            pkgmatch = (JAVA_PACKAGE if suffix=='.java' else AS_PACKAGE).search(text)
            package=pkgmatch.group(1) if pkgmatch else ''
            simple=p.stem
            fullname=(package+'.' if package else '')+simple
            by_symbol[fullname].append(rel)
            by_simple[simple].append(rel)
            imports=(JAVA_IMPORT if suffix=='.java' else AS_IMPORT).finditer(text) if suffix!='.mxml' else []
            for match in imports:
                symbol=match.group(1)
                raw_imports.append((rel,symbol,text.count('\n',0,match.start())+1))
                parts=symbol.split('.')
                if len(parts)>1: external_imports['.'.join(parts[:min(3,len(parts)-1)])]+=1
        if suffix in ('.java','.as'):
            # Typed member/constructor declarations, without claiming a runtime call.
            for m in re.finditer(r'\b(?:new\s+)?([A-Z][A-Za-z0-9_]{3,})\s*(?:<[^;{}>]{0,120}>)?\s+[_a-zA-Z][\w]*\s*(?:[;=,(]|$)',text,re.M):
                raw_type_refs.append((rel,m.group(1),text.count('\n',0,m.start())+1))
        if suffix=='.xml':
            ns=XML_MAPPER_NS.search(text)
            if ns:
                mapper_links.append((rel,ns.group(1), text.count('\n',0,ns.start())+1))
            for match in XML_CLASS.finditer(text):
                xml_refs.append((rel,match.group(1),text.count('\n',0,match.start())+1))
        if suffix in CODE_EXTS:
            for match in SQL_TABLE.finditer(text):
                tables[match.group(1).lower()].add(rel)
    edges=[]; unresolved=Counter()
    def add(source,symbol,line,kind):
        targets=by_symbol.get(symbol,[])
        confidence='exact'
        if not targets:
            targets=by_simple.get(symbol.rsplit('.',1)[-1],[])
            confidence='candidate-name-only'
        if len(targets)==1 and targets[0]!=source:
            edges.append({'from':source,'to':targets[0],'kind':kind,'line':line,'symbol':symbol,'confidence':confidence})
        else:
            unresolved[(kind,symbol)] += 1
    for src,imp,line in raw_imports:
        add(src,imp,line,'import')
    for src,sym,line in mapper_links:
        add(src,sym,line,'mapper-namespace')
    for src,sym,line in xml_refs:
        if '.' in sym:
            add(src,sym,line,'xml-class-reference')
    for src,sym,line in raw_type_refs:
        # Restrict to names declared in this repository; avoid external types.
        if sym in by_simple:
            add(src,sym,line,'declared-type-reference')
    # De-duplicate edges, preserving a specific source position.
    distinct={(e['from'],e['to'],e['kind'],e['symbol'],e['line']):e for e in edges}
    edges=sorted(distinct.values(),key=lambda e:(e['from'],e['to'],e['line']))
    module_json={k:{'files':v['count'],'types':dict(v['types'])} for k,v in sorted(module_counts.items())}
    by_type=Counter(p.rsplit('.',1)[-1] if '.' in p else '(no extension)' for p in records)
    dep_unique={(x['library'],x['version'],x['ecosystem'],x['declared_in']):x for x in dependencies}
    dependencies=sorted(dep_unique.values(),key=lambda x:(x['ecosystem'],x['library'],x['declared_in']))
    diagram_count,omitted=_format_drawio(module_counts,edges,destination/'architecture.drawio')
    payload={'architecture_version':43,'project':str(repo.root),
             'source_inventory':_source_inventory(repo.root),
             'files_scanned':len(records),'modules':module_json,
             'dependencies':dependencies,'external_import_packages':external_imports.most_common(500),'edges':edges,
             'unresolved':[{'kind':k[0],'symbol':k[1],'count':n} for k,n in unresolved.most_common(500)],
             'sql_tables':[{'name':n,'files':sorted(paths)} for n,paths in sorted(tables.items())],
             'read_errors':read_errors,
             'note':'Static heuristic inventory only. Imports do not establish runtime execution, and name-based matches are tentative.'}
    (middle/'architecture.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    with (middle/'file_links.csv').open('w',encoding='utf-8-sig',newline='') as outcsv:
        wr=csv.DictWriter(outcsv,fieldnames=['from','to','kind','line','symbol','confidence']);wr.writeheader();wr.writerows(edges)
    with (middle/'dependencies.csv').open('w',encoding='utf-8-sig',newline='') as outcsv:
        wr=csv.DictWriter(outcsv,fieldnames=['library','version','ecosystem','declared_in']);wr.writeheader();wr.writerows(dependencies)
    lines=['# Tổng quan kiến trúc repository', '',
           '> Khảo sát tĩnh, không gọi AI. Liên kết import không chứng minh luồng thực thi.', '',
           '## Mục lục', '',
           '- [Thống kê](#thống-kê)', '- [Thư viện và dependencies](#thư-viện-và-dependencies)',
           '- [Các module](#các-module)', '- [Liên kết file](#liên-kết-file)',
           '- [Giới hạn](#giới-hạn)', '',
           '## Thống kê','',
           f'- Source/config files: **{len(records)}**',
           f'- Module cấp một: **{len(module_counts)}**',
           f'- Dependency khai báo: **{len(dependencies)}**',
           f'- Nhóm package import bên ngoài: **{len(external_imports)}**',
           f'- File links nhận diện: **{len(edges)}**',
           f'- Sơ đồ Draw.io: **{diagram_count}** cặp liên kết module',
           f'- Module không vẽ (quá 100): **{omitted}**', '',
           '## Thư viện và dependencies','',
           '| Thư viện | Phiên bản | Loại | File khai báo |','|---|---|---|---|']
    for d in dependencies[:500]:
        lines.append(f'| `{d["library"]}` | `{d["version"]}` | {d["ecosystem"]} | `{d["declared_in"]}` |')
    if not dependencies:lines.append('| Không tìm thấy khai báo hỗ trợ | | | |')
    lines+=['','### Các package import thường gặp (kể cả thư viện chưa được khai báo)','',
            '| Package | Số lần import |','|---|---:|']
    for pack,n in external_imports.most_common(60): lines.append(f'| `{pack}` | {n} |')
    if len(dependencies)>500:lines.append(f'\n*Hiển thị 500/{len(dependencies)}; xem middle-files/dependencies.csv để lấy đủ.*')
    lines+=['','## Các module','','| Module | Số file | Loại file |','|---|---:|---|']
    for name,v in sorted(module_counts.items(),key=lambda x:-x[1]['count']):
        summary=', '.join(f'{k}: {n}' for k,n in v['types'].most_common(7))
        lines.append(f'| `{name}` | {v["count"]} | {summary} |')
    lines+=['','## Liên kết file','','| File nguồn | File đích | Quan hệ | Độ tin cậy |','|---|---|---|---|']
    for edge in edges[:250]:
        lines.append(f'| `{edge["from"]}:{edge["line"]}` | `{edge["to"]}` | {edge["kind"]} | {edge["confidence"]} |')
    if len(edges)>250:lines.append(f'\n*Hiển thị 250/{len(edges)}; xem middle-files/file_links.csv và middle-files/architecture.json để lấy đủ.*')
    lines+=['','## Giới hạn','',
            '- Thu thập import Java/ActionScript, mapper namespace, class-reference XML và dependency được khai báo trong Maven/Gradle/Ivy/Ant (một phần).',
            '- MXML event binding, runtime reflection, dependency injection, SQL động và kết nối qua HTTP chưa được truy vết đầy đủ.',
            '- Quan hệ candidate-name-only chỉ là trùng tên class, **không phải** dependency đã xác minh.',
            '- Bỏ qua binary, thư mục build, symlink và file lớn hơn 1 MB; manifest chưa hỗ trợ đầy đủ mọi build system.',
            '- Sơ đồ thể hiện liên kết tĩnh giữa module, không phải flowchart runtime.',
            '- Để phân tích hành vi thực tế, dùng `chat` sau khi đã xem sơ đồ cấu trúc.']
    (destination/'architecture.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    result={'files_scanned':len(records),'modules':len(module_counts),'declared_dependencies':len(dependencies),
            'file_links':len(edges),'architecture':str(destination/'architecture.md'),
            'drawio':str(destination/'architecture.drawio'),'json':str(middle/'architecture.json'),
            'links_csv':str(middle/'file_links.csv'),'dependencies_csv':str(middle/'dependencies.csv'),
            'reused_graph':False}
    if verbose:print(f'[Architecture] Done: {len(records)} files, {len(dependencies)} dependencies, {len(edges)} file links.',flush=True)
    return result
