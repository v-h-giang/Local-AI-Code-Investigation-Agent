"""Repository-wide, topic-free static discovery and optional grounded Ollama summary.

Never executes project code. Produces a full machine-readable inventory and a bounded
architecture *inventory* diagram (NOT a verified runtime call graph).
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
import math

from codebase import Repo, MAX_FILES
from exporter import toc, SQL_TABLE_RE
from agent_core import Investigator, Ollama

EXT_TECH = {'.java':'Java', '.as':'ActionScript', '.mxml':'MXML', '.sql':'SQL', '.xml':'XML', '.jsp':'JSP', '.jspx':'JSP', '.properties':'Config', '.gradle':'Build'}
# These are source-level entrypoint hints, never proof of actual runtime entry.
TOPIC_PATTERNS = (
    ('AIR handler', re.compile(r'\b(?:click|creationComplete|change|initialize)\s*=\s*[\"\']\s*([A-Za-z_]\w*)\s*\('), {'.mxml'}),
    ('AS3 function', re.compile(r'\bfunction\s+([A-Za-z_]\w*)\s*\('), {'.as'}),
    ('Java method', re.compile(r'\b(?:public|protected)\s+(?:static\s+)?[\w<>\[\],.?]+\s+([a-zA-Z_]\w*)\s*\('), {'.java'}),
    ('SQL mapper id', re.compile(r'<(?:select|insert|update|delete)\b[^>]*\bid\s*=\s*[\"\']([^\"\']+)',re.I), {'.xml'}),
)

SIGNALS = (
 ('Java main', re.compile(r'\bstatic\s+void\s+main\s*\('), {'.java'}),
 ('HTTP controller annotation', re.compile(r'@(?:RestController|Controller|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping)\b'), {'.java'}),
 ('Scheduled job annotation', re.compile(r'@Scheduled\s*\('), {'.java'}),
 ('AIR Application root', re.compile(r'<(?:mx|s):(?:WindowedApplication|Application)\b'), {'.mxml'}),
 ('AIR UI event binding', re.compile(r'\b(?:click|creationComplete|change|initialize)\s*=\s*["\']'), {'.mxml'}),
 ('ActionScript event listener', re.compile(r'\baddEventListener\s*\('), {'.as'}),
 ('SQL DML or schema', re.compile(r'\b(?:select|insert\s+into|update|delete\s+from|create\s+table)\b', re.I), {'.sql'}),
 ('SQL mapper statement', re.compile(r'<(?:select|insert|update|delete)\b', re.I), {'.xml'}),
)


def _module(path: str) -> str:
    parts = path.split('/')
    # Use the repository's structural root, not guessed feature names.
    return parts[0] if len(parts) > 1 else '(root)'


def _clip(s: str, size: int = 140) -> str:
    return s.replace('|', '¦').replace('\r',' ').replace('\n',' ').strip()[:size]


def survey(repo: Repo) -> dict:
    files = repo.files(limit=MAX_FILES)
    modules = defaultdict(lambda: {'files':0, 'technologies':Counter(), 'examples':[], 'signals':[], 'tables':Counter()})
    records, signals, tables, errors, discovered_topics = [], [], Counter(), [], []
    by_ext = Counter()
    for sf in files:
        mod = _module(sf.path)
        ext = sf.fullpath.suffix.lower()
        tech = EXT_TECH.get(ext, 'Other')
        item = {'path':sf.path,'module':mod,'technology':tech,'size_bytes':sf.fullpath.stat().st_size}
        records.append(item)
        by_ext[tech] += 1
        m = modules[mod]
        m['files'] += 1
        m['technologies'][tech] += 1
        if len(m['examples']) < 8:
            m['examples'].append(sf.path)
        try:
            lines = repo._read(sf.fullpath).splitlines()
        except (OSError, ValueError) as exc:
            errors.append({'path':sf.path,'error':str(exc)[:100]})
            continue
        for number, line in enumerate(lines, 1):
            for name, patt, exts in SIGNALS:
                if ext in exts and patt.search(line):
                    evidence = {'type':name,'source':f'{sf.path}:{number}','excerpt':_clip(line)}
                    signals.append(evidence)
                    if len(m['signals']) < 14:
                        m['signals'].append(evidence)
            for kind, patt, exts in TOPIC_PATTERNS:
                if ext in exts:
                    for match in patt.finditer(line):
                        discovered_topics.append({'kind':kind,'name':match.group(1), 'source':f'{sf.path}:{number}'})
            if ext in ('.sql', '.xml', '.java'):
                for table in SQL_TABLE_RE.findall(line):
                    key = table.lower()
                    tables[key] += 1
                    m['tables'][key] += 1
    modules_out = []
    for name, val in sorted(modules.items(), key=lambda x:(-x[1]['files'],x[0])):
        modules_out.append({'name':name,'files':val['files'],
                            'technologies':dict(val['technologies']),
                            'examples':val['examples'], 'signals':val['signals'],
                            'top_tables':val['tables'].most_common(15)})
    return {'project':repo.root.name, 'root':str(repo.root), 'generated_at':datetime.now().isoformat(timespec='seconds'),
            'scanned_files':len(files), 'at_file_limit':len(files)>=MAX_FILES,
            'coverage_note':f'Files with permitted extensions, each <=1 MB; repository scanning stops at {MAX_FILES} files. Skips excluded folders and symlinks.',
            'languages':dict(by_ext), 'modules':modules_out,
            'signals':signals, 'discovered_topics':discovered_topics, 'tables':tables.most_common(200), 'errors':errors, 'files':records}


def _draw_overview(data: dict, out: Path, max_nodes: int = 28) -> dict:
    """One editable node per top-level module, with clearer initial spacing."""
    groups = data['modules'][:max_nodes]
    count = max(1, len(groups))
    columns = 3 if count <= 9 else 4
    rows = max(1, math.ceil(count / columns))
    box_w, box_h = 500, 130
    gap_x, gap_y = 70, 55
    left, top_pad = 70, 85
    page_w = max(1750, left * 2 + columns * box_w + (columns - 1) * gap_x)
    page_h = max(1800, top_pad * 2 + rows * box_h + (rows - 1) * gap_y)
    root = ET.Element('mxfile', {'host': 'app.diagrams.net', 'type': 'device'})
    dia = ET.SubElement(root, 'diagram', {'id': 'overview', 'name': 'Repository modules (static)'})
    model = ET.SubElement(dia, 'mxGraphModel', {'dx': '1300', 'dy': '850', 'grid': '1', 'gridSize': '10', 'page': '1', 'pageWidth': str(page_w), 'pageHeight': str(page_h)})
    r = ET.SubElement(model, 'root')
    ET.SubElement(r, 'mxCell', {'id': '0'})
    ET.SubElement(r, 'mxCell', {'id': '1', 'parent': '0'})
    for i, mod in enumerate(groups):
        col, row = i % columns, i // columns
        label = f"{mod['name']} ({mod['files']} files)\n" + ', '.join(f'{k}:{v}' for k, v in sorted(mod['technologies'].items()))
        cell = ET.SubElement(r, 'mxCell', {'id': f'm{i+2}', 'value': label,
            'style': 'rounded=1;whiteSpace=wrap;html=0;fillColor=#eaf0ff;strokeColor=#42679f;fontSize=13;align=center;verticalAlign=middle;fontStyle=1;spacing=8;',
            'vertex': '1', 'parent': '1'})
        ET.SubElement(cell, 'mxGeometry', {'x': str(left + col * (box_w + gap_x)), 'y': str(top_pad + row * (box_h + gap_y)), 'width': str(box_w), 'height': str(box_h), 'as': 'geometry'})
    out.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(out, encoding='utf-8', xml_declaration=True)
    return {'diagram_modules': len(groups), 'diagram_omitted_modules': max(0, len(data['modules']) - len(groups))}


def _markdown(data: dict) -> str:
    lines = [
        '# Khảo sát tổng quan hệ thống từ source code', '',
        '> Tài liệu sinh tự động từ quét mã nguồn tĩnh. Không xác nhận hành vi runtime, không thay thế thiết kế gốc.', '',
        '## Phạm vi và mức độ bao phủ', '',
        f"- Repository: `{_clip(data['project'])}`",
        f"- Số file đã quét: **{data['scanned_files']}**", f"- Số nhóm thư mục cấp cao: **{len(data['modules'])}**",
        f"- Các loại mã: {', '.join(f'{k}: {v}' for k,v in sorted(data['languages'].items())) or '(none)'}",
        '- Không quét thư mục bị loại trừ, binary, symlink và file lớn hơn 1 MB.',
        f"- Đã chạm giới hạn quét: **{'Có — báo cáo có thể thiếu file' if data['at_file_limit'] else 'Không'}**",
        f"- Số lỗi đọc file: {len(data['errors'])}", '',
        '## Các module / thư mục nguồn', '',
        '| Nhóm nguồn | Số file | Công nghệ | Source minh họa |', '|---|---:|---|---|']
    for m in data['modules']:
        langs = ', '.join(f'{k} ({v})' for k,v in sorted(m['technologies'].items()))
        examples = ', '.join(f'`{_clip(p,90)}`' for p in m['examples'][:3])
        lines.append(f"| `{_clip(m['name'])}` | {m['files']} | {_clip(langs,250)} | {examples} |")
    lines.extend(['', '## Điểm khởi đầu và dấu hiệu xử lý được phát hiện', '',
                  'Các dòng sau là **dấu hiệu từ cú pháp** (pattern matches), chưa kết luận là entrypoint đang chạy.', '',
                  '| Dấu hiệu | Vị trí | Câu lệnh minh họa |','|---|---|---|'])
    for s in data['signals'][:180]:
        lines.append(f"| {_clip(s['type'])} | `{s['source']}` | `{_clip(s['excerpt'],120).replace('`', "'")}` |")
    if not data['signals']:lines.append('| Chưa phát hiện | | |')
    if len(data['signals'])>180:lines.append(f'\n*Bảng hiển thị 180/{len(data["signals"])} dấu hiệu; toàn bộ được lưu trong `repository_overview.json`.*')
    lines += ['', '## Bảng SQL được nhắc đến', '',
              '| Bảng (dò theo câu lệnh SQL) | Số lần xuất hiện |','|---|---:|']
    for name,count in data['tables'][:100]:
        lines.append(f'| `{_clip(name)}` | {count} |')
    if not data['tables']:lines.append('| Chưa phát hiện | 0 |')
    lines += ['', '## Danh sách chức năng / method có thể điều tra', '',
              'Các tên dưới đây được trích xuất từ cú pháp source, **chưa gộp thành chức năng nghiệp vụ**.', '',
              '| Nguồn phát hiện | Tên được khai báo | Vị trí |', '|---|---|---|']
    for item in data['discovered_topics'][:150]:
        lines.append(f"| {item['kind']} | `{_clip(item['name'])}` | `{item['source']}` |")
    if not data['discovered_topics']:lines.append('| Chưa phát hiện | | |')
    if len(data['discovered_topics']) > 150:
        lines.append(f'\n*Hiển thị 150/{len(data["discovered_topics"])} tên; danh mục đầy đủ nằm trong JSON.*')
    lines += ['', '## Hướng điều tra tiếp theo', '',
              '1. Mở `system_overview.drawio` để xem tất cả nhóm module **trong giới hạn sơ đồ**; không có mũi tên runtime suy đoán.',
              '2. Dùng `repository_files.csv` để duyệt toàn bộ các đường dẫn source đã quét.',
              '3. Chọn một module hoặc entrypoint trong báo cáo rồi dùng `chat` để truy vết UI → Java → mapper → SQL có `path:line`.',
              '4. Để tạo bản thảo diễn giải AI tự động, dùng `design` **không có `--topic`** hoặc `overview --ai`.', '',
              '## Giới hạn và độ tin cậy', '',
              '- Nhóm module được chia theo thư mục cấp cao; đây là quy ước cấu trúc, **không phải** kiến trúc thành phần được xác minh.',
              '- Pattern entrypoint và tên bảng chỉ là tín hiệu tĩnh; không chứng minh remote call, luồng thực thi, quan hệ khóa ngoại hoặc tác động nghiệp vụ.',
              '- Không đọc file nhị phân, bytecode, configuration bị loại trừ, SQL generated runtime hoặc nội dung từ database.',
              '- Các extension chưa hỗ trợ, file >1 MB, thư mục build bị loại trừ và giới hạn 25.000 file làm giảm phạm vi.',
              '- Nội dung từ source có thể không đáng tin cậy hoặc chứa thông tin nhạy cảm: kiểm tra và bảo quản output như source.']
    return toc('\n'.join(lines))


def export_overview(repo: Repo, target_dir: str | Path, *, llm: Ollama | None = None, verbose: bool = True, max_batches: int | None = None, files_per_batch: int = 1, resume: bool = True) -> dict:
    target = Path(target_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    data = survey(repo)
    (target/'repository_overview.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    with (target/'repository_files.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f,fieldnames=['path','module','technology','size_bytes'])
        writer.writeheader();writer.writerows(data['files'])
    diagram = _draw_overview(data,target/'system_overview.drawio')
    (target/'system_overview.md').write_text(_markdown(data),encoding='utf-8')
    result={'files_scanned':data['scanned_files'],'modules':len(data['modules']),
            'at_file_limit':data['at_file_limit'], 'signals':len(data['signals']), 'discovered_topics':len(data['discovered_topics']),
            'overview':str(target/'system_overview.md'),
            'diagram':str(target/'system_overview.drawio'),
            'inventory_csv':str(target/'repository_files.csv'),
            'inventory_json':str(target/'repository_overview.json'), **diagram}
    if llm is not None:
        from staged_design import analyze_in_batches
        result.update(analyze_in_batches(repo, llm, data, target, max_batches=max_batches,
                                         files_per_batch=files_per_batch, resume=resume,
                                         verbose=verbose))
    return result
