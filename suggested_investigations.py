"""Grounded, deterministic investigation suggestions from the local source index.

Only proposes questions backed by actual source locations. No invented classes,
endpoint mappings, runtime calls, or automatic Ollama use during suggestion generation.
"""
from __future__ import annotations
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from code_intelligence import build_intelligence, investigate

GROUPS = ('Business Flows', 'Technical Architecture')
INTERESTING = ('service', 'controller', 'action', 'facade', 'processor', 'handler', 'mapper', 'repository')


def _q(kind, subject, location, priority, group, reason, rank):
    question = {
        'source_flow': f'Truy vết luồng nghiệp vụ bắt đầu từ `{subject}` đến service, mapper và SQL. Xác minh từng bước.',
        'method': f'`{subject}` được triển khai ở đâu, được gọi từ đâu và các nhánh xử lý chính là gì?',
        'endpoint': f'Entrypoint `{subject}` kết nối đến những xử lý backend hoặc database nào? Kiểm tra cấu hình ánh xạ.',
        'sql': f'Các chức năng nào đọc/ghi bảng `{subject}` và luồng thực thi nào dẫn đến truy vấn đó?',
        'impact': f'Nếu thay đổi `{subject}`, những class, module và điểm gọi nào có thể bị ảnh hưởng?',
        'dependency': f'Quan hệ phụ thuộc từ `{subject}` đến các thành phần khác được khai báo ở đâu? Có dấu hiệu phụ thuộc vòng không?',
        'configuration': f'`{subject}` được cấu hình/khởi tạo ở đâu và những entrypoint nào sử dụng nó?',
        'module': f'Module `{subject}` chứa những trách nhiệm và dependency chính nào? Có sự phụ thuộc chéo cần điều tra không?',
    }[kind]
    return {'id': '', 'group': group, 'priority': priority, 'score': rank,
            'question': question, 'reason': reason, 'source_evidence': [location],
            'source_kind': kind, 'subject': subject,
            'confidence': 'source-backed-question; relationships-unverified'}


def suggest_investigations(repo, out='output/architecture', top=20):
    """Rank at most `top` distinct source-backed questions across two groups."""
    if not 1 <= top <= 100:
        raise ValueError('top must be between 1 and 100')
    dest = Path(out).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    index = build_intelligence(repo, dest, verbose=False)
    candidates = []
    seen = set()

    def add(kind, name, path, line, score, group, reason):
        if not name or not path or not isinstance(line, int) or line < 1:
            return
        if len(name) > 120 or len(path) > 420:
            return
        key = (kind, name.casefold(), path)
        if key in seen:
            return
        seen.add(key)
        priority = 'P0' if score >= 85 else 'P1' if score >= 65 else 'P2'
        candidates.append(_q(kind, name, f'{path}:{line}', priority, group, reason, score))

    with sqlite3.connect(index['index']) as conn:
        conn.row_factory = sqlite3.Row
        endpoints = conn.execute('SELECT path,line,protocol,value FROM endpoints ORDER BY path,line LIMIT 500').fetchall()
        for r in endpoints:
            detail = str(r['value']).strip()[:100]
            add('endpoint', detail or str(r['protocol']), r['path'], int(r['line']), 96,
                'Business Flows', f'Có endpoint/remote signature trong source ({r["protocol"]}); cần xác minh mapping.')
        sql = conn.execute('SELECT path,line,table_name FROM sql_tables ORDER BY path,line LIMIT 1500').fetchall()
        table_seen = set()
        for r in sql:
            key = str(r['table_name']).lower()
            if key in table_seen:
                continue
            table_seen.add(key)
            add('sql', str(r['table_name']), r['path'], int(r['line']), 86,
                'Business Flows', 'Có tham chiếu SQL đến bảng này; chưa chứng minh đường thực thi.')
        symbols = conn.execute('''SELECT path,line,name,kind,signature FROM symbols
            WHERE kind IN ('method','function','class','interface','sql-mapper','constructor')
            ORDER BY path,line LIMIT 12000''').fetchall()
        for r in symbols:
            name = str(r['name'])
            kind = str(r['kind'])
            meaningful = any(token in name.lower() for token in INTERESTING)
            if kind in ('method', 'function'):
                score = 88 if meaningful else 65
                add('method', name, r['path'], int(r['line']), score, 'Business Flows',
                    'Method/function được khai báo trong source; cần tìm entrypoint và caller.')
                if meaningful:
                    add('impact', name, r['path'], int(r['line']), 79, 'Technical Architecture',
                        'Method có tên gợi ý vai trò xử lý; cần phân tích impact trên graph tĩnh.')
            elif kind in ('class','interface'):
                add('configuration' if 'config' in name.lower() else 'impact', name,
                    r['path'], int(r['line']), 78 if meaningful else 62,
                    'Technical Architecture', 'Class/interface có khai báo thực tế; các quan hệ có thể chưa được resolve.')
            elif kind == 'sql-mapper':
                add('source_flow', name, r['path'], int(r['line']), 90,
                    'Business Flows', 'SQL mapper statement được khai báo; kiểm tra đường gọi và transaction.')
        relations = conn.execute('''SELECT path,line,kind,src,dst FROM relations
            WHERE path IS NOT NULL AND line > 0 ORDER BY path,line LIMIT 2500''').fetchall()
        for r in relations:
            src = str(r['src'])
            if src.startswith('file:'):
                src = Path(src[5:]).stem
            else:
                src = src.rsplit(':', 1)[-1][:100]
            add('dependency', src, r['path'], int(r['line']), 70,
                'Technical Architecture', f'Có quan hệ graph tĩnh ({r["kind"]}); phải kiểm tra độ tin cậy.')

    # Stable priority order, but give both categories a reasonable share of results.
    per_group = {group: sorted((x for x in candidates if x['group'] == group),
                               key=lambda x: (-x['score'], x['subject'].lower(), x['source_evidence'][0]))
                 for group in GROUPS}
    selected = []
    if all(per_group.values()):
        # Half of the 20-question budget for each group where there is evidence.
        quota = top // 2
        for group in GROUPS:
            selected.extend(per_group[group][:quota])
            per_group[group] = per_group[group][quota:]
    remainder = sorted((x for group in GROUPS for x in per_group[group]),
                       key=lambda x: (-x['score'], GROUPS.index(x['group']), x['subject'].lower()))
    selected.extend(remainder[:max(0, top - len(selected))])
    selected = selected[:top]
    selected.sort(key=lambda x: (-x['score'], GROUPS.index(x['group']), x['subject'].lower()))
    for i, item in enumerate(selected, 1):
        item['id'] = f'INV-{i:03d}'
    report = {'schema_version': 1, 'default_top': top, 'groups': list(GROUPS),
              'generated_count': len(selected), 'candidates': selected,
              'limitations': ['Questions are grounded in indexed source locations, not confirmed behavior.',
                              'No source evidence means no question. Max count is a cap, not a quota.',
                              'Heuristic call/flow relationships require verification.']}
    md = ['# Suggested Investigations', '',
          f'> Generated {len(selected)} / {top} questions from scanned source evidence.',
          '> No Qwen call is used for question generation. Cross-layer relationships are not assumed.', '']
    for group in GROUPS:
        md += [f'## {group}', '', '| ID | Priority | Investigation | Why | Evidence |',
               '|---|---|---|---|---|']
        for item in selected:
            if item['group'] != group: continue
            safe = lambda value: str(value).replace('|', '\\|').replace('\n',' ')
            md.append(f'| {item["id"]} | {item["priority"]} | {safe(item["question"])} | '
                      f'{safe(item["reason"])} | `{safe(item["source_evidence"][0])}` |')
        if not any(item['group'] == group for item in selected):
            md.append('| — | — | No indexed evidence for this group | — | — |')
        md.append('')
    md += ['## Usage', '',
           'Run `architecture --auto-investigate-top N` to execute the first N ranked questions using local Qwen.',
           'Without that option, no suggested investigation is executed.', '']
    json_path = dest / 'middle-files' / 'suggested_investigations.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    md_path = dest / 'suggested_investigations.md'
    md_path.write_text('\n'.join(md), encoding='utf-8')
    return {'suggestions': str(md_path), 'suggestions_json': str(json_path),
            'suggestions_count': len(selected), 'suggestion_groups': list(GROUPS),
            'candidates': selected}


def auto_investigate(repo, out, candidates, top, llm, budget=1200, max_steps=4,
                     *, markdown=True, diagram=True, update_drawio=True,
                     overwrite_drawio=False, diagram_type='auto'):
    """Run selected source-backed questions and export readable reports + diagrams."""
    if not 1 <= top <= 20:
        raise ValueError('--auto-investigate-top must be 1..20')
    from investigation_report import write_investigation
    output = Path(out).expanduser().resolve()
    dest = output / 'investigations'
    middle = output / 'middle-files' / 'investigations'
    dest.mkdir(parents=True,exist_ok=True)
    middle.mkdir(parents=True,exist_ok=True)
    results = []
    for item in candidates[:top]:
        status = 'completed'
        error = None
        try:
            response = investigate(repo, item['question'], llm, budget=budget, max_steps=max_steps)
            if response.get('answer_status') == 'insufficient-evidence':
                status = 'insufficient-evidence'
        except Exception as exc:
            status = 'failed'
            error = str(exc)[:300]
            response = {'question':item['question'], 'answer_status':'execution-failed',
                        'answer':'Không có kết luận do lần điều tra bị lỗi.', 'tool_errors':[error]}
        try:
            report = write_investigation(repo, output, response,
                investigation_id=item['id'], question=item['question'],
                status=status, error=error, seed_refs=item.get('source_evidence') or [],
                markdown=markdown, diagram=diagram, update_drawio=update_drawio,
                overwrite_drawio=overwrite_drawio, diagram_type=diagram_type)
            status = report['status']
        except Exception as exc:
            # Report failure itself must be visible; do not claim successful investigation.
            status = 'failed'
            error = 'Failed to write report: '+str(exc)[:250]
            report = {}
        results.append({'id':item['id'], 'status':status, 'question':item['question'],
                        'markdown':report.get('markdown'), 'diagram':report.get('investigation_drawio'),
                        'json':report.get('json'), 'error':error})
    manifest = {'requested':top, 'executed':len(results),
                'successful':sum(x['status']=='completed' for x in results), 'results':results}
    (middle/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    if markdown:
        lines=['# Auto Investigation Results', '',
               f'Completed: **{manifest["successful"]} / {manifest["executed"]}**', '',
               '| ID | Result | Question | Report | Diagram |',
               '|---|---|---|---|---|']
        for entry in results:
            report_link=f'[Đọc báo cáo]({entry["id"]}/result.md)' if entry.get('markdown') else '—'
            diagram_link=f'[Draw.io]({entry["id"]}/investigation.drawio)' if entry.get('diagram') else '—'
            question=entry['question'].replace('|','\\|').replace('\n',' ')
            lines.append(f'| {entry["id"]} | {entry["status"]} | {question} | {report_link} | {diagram_link} |')
        lines+=['','Raw JSON/CSV and machine manifest: `../middle-files/investigations/`.','']
        (dest/'index.md').write_text('\n'.join(lines),encoding='utf-8')
    elif (dest/'index.md').is_file():
        (dest/'index.md').unlink()
    return manifest
