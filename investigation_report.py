"""v4.14: human-readable, source-grounded reports and Draw.io investigation overlays.

Source evidence is validated against the local project before visualization.
Only existing static dependency edges may become arrows. Everything machine-readable
(JSON, evidence CSV, overlay registry and optional pristine diagram backups) lives
under output/middle-files/. Scanned project files are never modified.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from architecture import _module

DIAGRAMS = (
    'architecture.drawio',
    'frontend_architecture.drawio',
    'backend_architecture.drawio',
    'fe_be_architecture.drawio',
    'frontend_reference.drawio',
    'backend_reference.drawio',
)
LAYERS = ('FE', 'BE', 'DB', 'SHARED')
COLORS = {
    'FE': ('#fff0dc', '#ae670d'),
    'BE': ('#e4f0ff', '#326aac'),
    'DB': ('#e2f3e7', '#348653'),
    'SHARED': ('#eef0f3', '#647184'),
}
REFERENCE = re.compile(r'^(.*?):([1-9][0-9]*)(?:-[1-9][0-9]*)?$')


def _id(question, investigation_id=None):
    if investigation_id is None:
        return 'INV-Q-' + hashlib.sha256(question.encode('utf-8')).hexdigest()[:10].upper()
    if not re.fullmatch(r'INV-[A-Za-z0-9_-]{1,50}', investigation_id):
        raise ValueError('Invalid investigation ID')
    return investigation_id


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (ValueError, OSError):
        return {}


def _raw_citations(result):
    """References come from tool evidence, not citations invented in Qwen prose."""
    refs = list(result.get('source_citations') or [])
    for step in (result.get('steps') or [])[:6]:
        if isinstance(step, dict):
            refs.extend(step.get('source_refs') or [])
    for excerpt in (result.get('source_excerpts') or [])[:32]:
        if isinstance(excerpt, str):
            m = re.match(r'^([^\s:][^:]*?):(\d+)(?::|\s|$)', excerpt)
            if m:
                refs.append(f'{m.group(1)}:{m.group(2)}')
    return list(dict.fromkeys(x for x in refs if isinstance(x, str)))[:80]


def _source_evidence(repo, result, seed_refs=None, cap=55):
    """Check citations against real, allowlisted source paths and actual lines."""
    evidence = []
    rejected = []
    cache = {}
    raw = [(r, 'investigation') for r in _raw_citations(result)]
    raw += [(r, 'question-seed') for r in (seed_refs or [])[:12] if r not in {x[0] for x in raw}]
    for text, provenance in raw:
        if len(evidence) >= cap:
            break
        m = REFERENCE.fullmatch(text.strip()) if isinstance(text, str) else None
        if not m:
            rejected.append(str(text)[:150])
            continue
        path, line = m.group(1).replace('\\', '/'), int(m.group(2))
        try:
            actual_path = repo._safe(path)
            if path not in cache:
                cache[path] = repo._read(actual_path).splitlines()
            lines = cache[path]
            if line > len(lines):
                raise ValueError('line exceeds file length')
        except (ValueError, OSError) as exc:
            rejected.append(f'{text[:130]} ({str(exc)[:80]})')
            continue
        if any(e['path'] == path and e['line'] == line for e in evidence):
            continue
        evidence.append({'path': path, 'line': line, 'ref': f'{path}:{line}',
                         'excerpt': lines[line - 1].strip()[:250], 'provenance': provenance})
    return evidence, rejected[:30]


def _classify(path, stack):
    lookup = stack.get('_object_lookup')
    if lookup is None:
        lookup = {obj.get('file'): obj for obj in stack.get('objects', [])
                  if isinstance(obj, dict) and isinstance(obj.get('file'), str)}
        stack['_object_lookup'] = lookup
    obj = lookup.get(path)
    if obj:
        layer = obj.get('layer', 'SHARED')
        return ('FE' if str(layer).startswith('FE') else 'BE' if str(layer).startswith('BE')
                else 'DB' if layer in ('DB', 'DB/BE') else 'SHARED'), obj.get('roles') or []
    lower = path.lower()
    if lower.endswith(('.mxml', '.as', '.jsx', '.tsx', '.vue', '.js', '.ts')):
        return 'FE', []
    if lower.endswith(('.java', '.kt')):
        return 'BE', []
    if lower.endswith('.sql') or 'mapper' in lower and lower.endswith('.xml'):
        return 'DB', []
    return 'SHARED', []


def _valid_edges(architecture, paths):
    """Only reuse explicit architecture-graph dependencies between cited files."""
    allowed = set(paths)
    found = []
    for edge in (architecture.get('edges') or [])[:150000]:
        if not isinstance(edge, dict):
            continue
        src, dst = edge.get('from'), edge.get('to')
        if src != dst and src in allowed and dst in allowed:
            pair = (src, dst)
            if pair not in found:
                found.append(pair)
        if len(found) >= 120:
            break
    return found


def _diagram_type(question, response, requested):
    if requested != 'auto':
        return requested
    intent = str((response.get('plan') or {}).get('intent', '')).lower()
    txt = question.casefold()
    if intent == 'impact' or any(t in txt for t in ('ảnh hưởng', 'impact', 'change', 'sửa ', 'thay đổi')):
        return 'impact'
    if intent in ('trace', 'data_flow') or any(t in txt for t in ('luồng', 'flow', 'trace', 'đến sql')):
        return 'flow'
    return 'symbol'


def _make_diagram(output, question, evidence, stack, architecture, kind):
    """One node per evidence-backed file; draw only observed static graph edges."""
    grouped = defaultdict(list)
    for item in evidence:
        if item['provenance'] != 'investigation':
            continue
        grouped[item['path']].append(item['line'])
    # Source-backed seeds can be displayed, clearly marked, without inferring flows.
    if not grouped:
        for item in evidence:
            grouped[item['path']].append(item['line'])
    records = []
    for path, lines in sorted(grouped.items())[:36]:
        layer, _ = _classify(path, stack)
        records.append((path, layer, sorted(set(lines))))
    root = ET.Element('mxfile', {'host': 'app.diagrams.net', 'type': 'device'})
    diagram = ET.SubElement(root, 'diagram', {'id': 'investigation', 'name': f'Investigation {kind}'})
    lane_order = tuple(reversed(LAYERS)) if kind == 'impact' else LAYERS
    columns = [layer for layer in lane_order if any(x[1] == layer for x in records)]
    columns = columns or ['SHARED']
    by_layer = defaultdict(list)
    for record in records:
        by_layer[record[1]].append(record)
    largest = max(1, *(len(by_layer[l]) for l in columns))
    page_w = max(1500, 120 + len(columns) * 590)
    page_h = max(1050, 210 + largest * 150)
    model = ET.SubElement(diagram, 'mxGraphModel', {'page': '1', 'grid': '1',
                               'pageWidth': str(page_w), 'pageHeight': str(page_h)})
    container = ET.SubElement(model, 'root')
    ET.SubElement(container, 'mxCell', {'id': '0'})
    ET.SubElement(container, 'mxCell', {'id': '1', 'parent': '0'})
    heading = ET.SubElement(container, 'mxCell', {'id': 'inv-heading',
        'value': question[:230] + '\nOnly source-backed static edges. NO runtime call is proven.',
        'style': 'rounded=1;whiteSpace=wrap;html=0;fillColor=#f4f4f4;strokeColor=#888888;'
                 'fontSize=15;fontStyle=1;align=left;verticalAlign=middle;spacing=12;',
        'vertex': '1', 'parent': '1'})
    ET.SubElement(heading, 'mxGeometry', {'x': '50', 'y': '20', 'width': str(page_w - 130),
                                         'height': '75', 'as': 'geometry'})
    ids = {}
    for col, layer in enumerate(columns):
        x = 55 + col * 590
        fill, stroke = COLORS[layer]
        label = ET.SubElement(container, 'mxCell', {'id': f'lane-{layer}', 'value': layer,
            'style': f'rounded=1;html=0;fillColor={fill};strokeColor={stroke};fontSize=18;fontStyle=1;'
                     'align=center;verticalAlign=middle;', 'vertex': '1', 'parent': '1'})
        ET.SubElement(label, 'mxGeometry', {'x': str(x), 'y': '115', 'width': '490',
                                           'height': '45', 'as': 'geometry'})
        for row, (path, _, lines) in enumerate(by_layer[layer]):
            ident = 'src-' + str(len(ids) + 1)
            ids[path] = ident
            is_seed = not any(e['path'] == path and e['provenance'] == 'investigation' for e in evidence)
            desc = 'Question seed (not independently investigated)' if is_seed else 'Source evidence'
            text = f'{path}\nLines: {", ".join(map(str, lines[:6]))}\n{desc}'
            cell = ET.SubElement(container, 'mxCell', {'id': ident, 'value': text,
                'style': f'rounded=1;whiteSpace=wrap;html=0;fillColor={fill};strokeColor={stroke};'
                         'fontSize=13;align=center;verticalAlign=middle;spacing=7;strokeWidth=2;'
                         + ('dashed=1;' if is_seed else ''),
                'vertex': '1', 'parent': '1'})
            ET.SubElement(cell, 'mxGeometry', {'x': str(x), 'y': str(180 + row * 150),
                                              'width': '490', 'height': '115', 'as': 'geometry'})
    edges = _valid_edges(architecture, ids)
    for i, (src, dst) in enumerate(edges):
        cell = ET.SubElement(container, 'mxCell', {'id': f'dep-{i}',
            'value': 'Static reference (not runtime)',
            'style': 'edgeStyle=orthogonalEdgeStyle;rounded=0;html=0;endArrow=block;'
                     'endFill=1;endSize=24;strokeWidth=3;strokeColor=#63758a;'
                     'fontSize=12;labelBackgroundColor=#ffffff;',
            'source': ids[src], 'target': ids[dst], 'edge': '1', 'parent': '1'})
        ET.SubElement(cell, 'mxGeometry', {'relative': '1', 'as': 'geometry'})
    if not records:
        label = ET.SubElement(container, 'mxCell', {'id': 'no-evidence',
            'value': 'No verified source file:line evidence. Diagram contains no inferred execution flow.',
            'style': 'rounded=1;whiteSpace=wrap;html=0;fillColor=#fff4dd;strokeColor=#bc812e;'
                     'fontSize=15;align=center;', 'vertex': '1', 'parent': '1'})
        ET.SubElement(label, 'mxGeometry', {'x': '60', 'y': '205', 'width': '750',
                                           'height': '110', 'as': 'geometry'})
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)
    return len(records), len(edges)


def _make_svg(output, question, evidence, stack, architecture, kind):
    """Human-readable inline SVG preview from the *same verified evidence* as Draw.io."""
    grouped = defaultdict(list)
    valid = [x for x in evidence if x['provenance'] == 'investigation']
    for item in (valid if valid else evidence):
        grouped[item['path']].append(item['line'])
    grouped = dict(list(sorted(grouped.items()))[:24])
    meta = {path: _classify(path, stack)[0] for path in grouped}
    order = tuple(reversed(LAYERS)) if kind == 'impact' else LAYERS
    lanes = [layer for layer in order if layer in meta.values()] or ['SHARED']
    by_layer = defaultdict(list)
    for name, layer in meta.items():
        by_layer[layer].append(name)
    width = max(850, len(lanes) * 410 + 70)
    height = max(380, 195 + max(len(by_layer[layer]) for layer in lanes) * 124)
    svg = ET.Element('svg', {'xmlns': 'http://www.w3.org/2000/svg',
          'viewBox': f'0 0 {width} {height}', 'width': str(width), 'height': str(height),
          'role': 'img', 'aria-label': 'Static source evidence map, no runtime inference'})
    ET.SubElement(svg, 'rect', {'width': str(width), 'height': str(height), 'fill': '#ffffff'})
    title = ET.SubElement(svg, 'text', {'x': '35', 'y': '35', 'font-size': '21',
                                     'font-weight': 'bold', 'fill': '#17232f'})
    title.text = ('Source Investigation — ' + question.replace('\n', ' ')[:105])
    subtitle = ET.SubElement(svg, 'text', {'x': '35', 'y': '62', 'font-size': '13', 'fill': '#6b5c39'})
    subtitle.text = 'Arrows = indexed static file links, NOT verified runtime calls. Green = tool-backed evidence.'
    ET.SubElement(svg, 'defs')
    defs = svg.find('defs')
    marker = ET.SubElement(defs, 'marker', {'id': 'static-arrow', 'markerWidth': '10',
          'markerHeight': '10', 'refX': '8', 'refY': '5', 'orient': 'auto',
          'markerUnits': 'strokeWidth'})
    ET.SubElement(marker, 'path', {'d': 'M0,0 L10,5 L0,10 z', 'fill': '#69788b'})
    centers = {}
    for col, lane in enumerate(lanes):
        x = 35 + col * 410
        fill, stroke = COLORS[lane]
        ET.SubElement(svg, 'rect', {'x': str(x), 'y': '82', 'width': '370',
                'height': str(height - 120), 'rx': '11', 'fill': fill, 'fill-opacity': '.36',
                'stroke': stroke, 'stroke-opacity': '.33'})
        heading = ET.SubElement(svg, 'text', {'x': str(x + 17), 'y': '112',
              'font-size': '20', 'font-weight': 'bold', 'fill': stroke})
        heading.text = lane
        for row, path in enumerate(by_layer[lane]):
            y = 135 + row * 124
            seed = not any(e['path'] == path and e['provenance'] == 'investigation' for e in evidence)
            border = '#b68023' if seed else '#25834d'
            card = ET.SubElement(svg, 'rect', {'x': str(x + 12), 'y': str(y), 'width': '345',
                'height': '100', 'rx': '9', 'fill': '#ffffff', 'stroke': border,
                'stroke-width': '2.4', **({'stroke-dasharray': '7 4'} if seed else {})})
            short = (path[:53] + '...' if len(path) > 56 else path)
            txt = ET.SubElement(svg, 'text', {'x': str(x + 24), 'y': str(y + 28),
                'font-size': '14', 'font-weight': 'bold', 'fill': '#17232f'})
            txt.text = short
            filename = ET.SubElement(svg, 'text', {'x': str(x + 24), 'y': str(y + 53),
                'font-size': '12', 'fill': '#384b5d'})
            filename.text = 'Lines: ' + ', '.join(map(str, sorted(set(grouped[path]))[:7]))
            label = ET.SubElement(svg, 'text', {'x': str(x + 24), 'y': str(y + 78),
                'font-size': '12', 'fill': '#86621e' if seed else '#267a48'})
            label.text = 'Question seed (unverified)' if seed else 'Source evidence'
            centers[path] = (x + 12, y, x + 357, y + 100)
            ET.SubElement(card, 'title').text = path
    for source, target in _valid_edges(architecture, centers):
        sx1, sy1, sx2, sy2 = centers[source]
        tx1, ty1, tx2, ty2 = centers[target]
        # Keep arrow direction of the *actual* static dependency; do not invert for impact.
        if tx1 >= sx2:
            start, finish = (sx2, (sy1 + sy2)/2), (tx1, (ty1 + ty2)/2)
        else:
            start, finish = (sx1, (sy1 + sy2)/2), (tx2, (ty1 + ty2)/2)
        middle_x = (start[0] + finish[0]) / 2
        ET.SubElement(svg, 'path', {'d': f'M{start[0]},{start[1]} H{middle_x} V{finish[1]} H{finish[0]}',
            'fill': 'none', 'stroke': '#69788b', 'stroke-width': '2.4',
            'marker-end': 'url(#static-arrow)'})
    if not grouped:
        text = ET.SubElement(svg, 'text', {'x': '52', 'y': '188',
            'font-size': '16', 'fill': '#955e1c'})
        text.text = 'No verified source evidence. Do not infer an execution flow.'
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(svg).write(output, encoding='utf-8', xml_declaration=True)
    return {'svg_nodes': len(grouped), 'svg_static_edges': len(_valid_edges(architecture, centers))}


def _style_add(style, modifications):
    """Replace selected draw.io style keys while retaining all other styling."""
    parts = [chunk for chunk in style.split(';') if chunk]
    parts = [chunk for chunk in parts if chunk.split('=', 1)[0] not in modifications]
    return ';'.join(parts + [f'{k}={v}' for k, v in modifications.items()]) + ';'


def _match_vertex(label, diagram, files, stack):
    name = label.split('\n', 1)[0].strip()
    if not name:
        return False
    if diagram == 'architecture.drawio':
        return name in {_module(path) for path in files}
    if diagram == 'fe_be_architecture.drawio':
        return name in {_source_diagram_layer(p, stack) for p in files}
    if diagram in ('frontend_architecture.drawio', 'backend_architecture.drawio'):
        layer = 'FE' if diagram.startswith('frontend') else 'BE'
        for path in files:
            actual_layer, roles = _classify(path, stack)
            if actual_layer == layer and name in roles:
                return True
    if diagram in ('frontend_reference.drawio', 'backend_reference.drawio'):
        # Reference nodes explicitly show matched source paths; do not color by conceptual framework alone.
        return any(p in label for p in files)
    return False


def _annotate(input_file, output_file, diagram, records, stack, architecture):
    """Add a report note and highlight matching existing vertices/edges, no new dependencies."""
    tree = ET.parse(input_file)
    graph = tree.getroot().find('.//mxGraphModel')
    if graph is None:
        raise ValueError(f'Unsupported Draw.io XML: {input_file}')
    cells = graph.find('root')
    if cells is None:
        raise ValueError('Draw.io graph has no root')
    files = {p for record in records for p in record.get('files', [])}
    selected = set()
    bounds = 0
    for cell in cells.findall('mxCell'):
        if cell.get('vertex') != '1':
            continue
        geometry = cell.find('mxGeometry')
        if geometry is not None:
            try:
                bounds = max(bounds, float(geometry.get('x', '0')) + float(geometry.get('width', '0')))
            except (ValueError, TypeError):
                pass
        if _match_vertex(cell.get('value', ''), diagram, files, stack):
            selected.add(cell.get('id'))
            cell.set('style', _style_add(cell.get('style', ''), {
                'strokeColor': '#23834a', 'strokeWidth': '4', 'shadow': '1'}))
    edges_highlighted = 0
    # Only color an existing aggregate edge when an *actual cited file pair*
    # is also present in the indexed graph. Highlighting by module role alone
    # would imply a false connection between unrelated cited files.
    grounded_file_pairs = _valid_edges(architecture, files)
    shown = {c.get('id'): c.get('value','').split('\n',1)[0].strip()
             for c in cells.findall('mxCell') if c.get('vertex')=='1'}
    def grounded_connection(src_node, dst_node):
        source_name, target_name = shown.get(src_node), shown.get(dst_node)
        if not source_name or not target_name:
            return False
        for source_file, target_file in grounded_file_pairs:
            if diagram == 'architecture.drawio':
                if (_module(source_file), _module(target_file)) == (source_name, target_name):
                    return True
            elif diagram == 'fe_be_architecture.drawio':
                source_layer = _source_diagram_layer(source_file, stack)
                target_layer = _source_diagram_layer(target_file, stack)
                if (source_layer, target_layer) == (source_name, target_name):
                    return True
            else:
                _, source_roles = _classify(source_file, stack)
                _, target_roles = _classify(target_file, stack)
                if source_name in source_roles and target_name in target_roles:
                    return True
        return False
    # Color ONLY existing edges with an explicit source-file supporting pair.
    if not diagram.endswith('_reference.drawio'):
        for cell in cells.findall('mxCell'):
            if (cell.get('edge') == '1' and cell.get('source') in selected
                    and cell.get('target') in selected
                    and grounded_connection(cell.get('source'), cell.get('target'))):
                cell.set('style', _style_add(cell.get('style', ''),
                              {'strokeColor': '#23834a', 'strokeWidth': '4', 'endSize': '24'}))
                edges_highlighted += 1
    used_ids = {c.get('id') for c in cells.findall('mxCell')}
    note_id = 'v414-note'
    while note_id in used_ids:
        note_id += 'x'
    note_text = ('Investigation overlay (v4.14)\n'
                 + f'{len(records)} investigation(s); {len(files)} unique source files; '
                 + f'{len(selected)} matching diagram boxes\n'
                 + 'Green outline = evidence-related node; not confirmed runtime.\n'
                 + '\n'.join(f'{r["id"]}: {r["question"][:78]}' for r in records[-4:]))
    cell = ET.SubElement(cells, 'mxCell', {'id': note_id, 'value': note_text,
        'style': 'rounded=1;whiteSpace=wrap;html=0;fillColor=#eaf7ef;strokeColor=#23834a;'
                 'fontSize=13;align=left;verticalAlign=middle;spacing=12;',
        'vertex': '1', 'parent': '1'})
    ET.SubElement(cell, 'mxGeometry', {'x': str(int(bounds + 90)), 'y': '60',
                                      'width': '510', 'height': '210', 'as': 'geometry'})
    graph.set('pageWidth', str(max(int(graph.get('pageWidth', '0')), int(bounds + 670))))
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_file, encoding='utf-8', xml_declaration=True)
    return {'matched_nodes': len(selected), 'highlighted_existing_edges': edges_highlighted}


def _source_diagram_layer(path, stack):
    _classify(path, stack)  # lazily build O(1) lookup
    obj = stack.get('_object_lookup', {}).get(path)
    return str(obj.get('layer', 'SHARED/UNKNOWN')) if obj else _classify(path, stack)[0]


def _update_architecture(out, items, stack, architecture, overwrite=False):
    produced = []
    backups = out / 'middle-files' / 'drawio-baselines'
    for name in DIAGRAMS:
        original = out / name
        snapshot = backups / name
        # When explicitly overwriting, preserve a clean original for repeatable overlays.
        source = snapshot if snapshot.is_file() else original
        if not source.is_file():
            continue
        if overwrite and not snapshot.exists():
            backups.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, snapshot)
            source = snapshot
        target = out / name.replace('.drawio', '.investigated.drawio')
        try:
            matches = _annotate(source, target, name, items, stack, architecture)
        except (ET.ParseError, OSError, ValueError) as exc:
            produced.append({'diagram': name, 'status': 'skipped', 'reason': str(exc)[:200]})
            continue
        if overwrite:
            shutil.copy2(target, original)
        produced.append({'diagram': str(target), 'status': 'updated', **matches,
                         'original_modified': overwrite})
    return produced


def _save_markdown(dest, investigation_id, question, result, evidence, rejected,
                   artifacts, kind, status, error=None):
    answer = result.get('answer') or ''
    if not answer and isinstance(result.get('source_excerpts'), list):
        answer = ('Chỉ có kết quả tìm kiếm từ khóa (non-AI); chưa có kết luận nghiệp vụ. '
                  'Xem bằng chứng bên dưới.')
    if not answer:
        answer = 'Chưa có kết luận đáng tin cậy từ lần điều tra này.'
    coverage = result.get('answer_status', 'non-ai-retrieval' if 'retriever' in result else 'unknown')
    evidence_count = len([e for e in evidence if e['provenance'] == 'investigation'])
    lines = [f'# {investigation_id} — Kết quả điều tra', '', '## Câu hỏi', '', question, '',
             '## Kết luận', '', answer, '', '## Trạng thái và độ tin cậy', '',
             f'- Trạng thái thực hiện: **{status}**',
             f'- Kết quả AI/retrieval: `{coverage}`',
             f'- Chứng cứ `file:line` xác thực trong source: **{evidence_count}**',
             '- Quan hệ graph là **phân tích tĩnh/heuristic**; không xác nhận luồng chạy runtime.',
             '- Màu xanh trong sơ đồ biểu thị **liên quan đến bằng chứng**, không phải runtime verified.', '']
    if error:
        lines += ['### Lỗi điều tra', '', f'`{str(error)[:500]}`', '']
    unsupported = result.get('unsupported_citations') or []
    if unsupported:
        lines += ['### Citation do AI nêu chưa được tool hỗ trợ', '',
                  *[f'- `{x}`' for x in unsupported[:20]], '']
    lines += ['## Source evidence', '', '| File:line | Vai trò | Nội dung source |', '|---|---|---|']
    for item in evidence:
        snippet = item['excerpt'].replace('|', '\\|').replace('`', "'").replace('\n', ' ')
        role = 'Tool evidence' if item['provenance'] == 'investigation' else 'Question seed (chưa điều tra)'
        lines.append(f'| `{item["ref"]}` | {role} | `{snippet[:180]}` |')
    if not evidence:
        lines += ['| Không có bằng chứng được xác minh | — | — |']
    lines += ['', '## Các bước điều tra', '']
    for step in result.get('steps') or []:
        if not isinstance(step, dict):
            continue
        n = step.get('step', '?')
        tool = step.get('tool', 'unknown')
        query = str(step.get('query', '')).replace('`', "'")
        refs = ', '.join('`' + str(r) + '`' for r in (step.get('source_refs') or [])[:5]) or 'Không có citation'
        lines += [f'{n}. **{tool}** — `{query}`; evidence: {refs}']
        if step.get('error'):
            lines.append(f'   - Tool error: `{str(step["error"])[:180]}`')
    if not result.get('steps'):
        lines.append('Không có nhật ký tool (chế độ non-AI hoặc điều tra chưa hoàn tất).')
    lines += ['', '## Sơ đồ', '']
    if artifacts.get('investigation_svg'):
        lines += ['### Sơ đồ minh họa', '', '![Sơ đồ chứng cứ](investigation.svg)', '']
    if artifacts.get('investigation_drawio'):
        lines.append('- [Mở sơ đồ Draw.io có thể chỉnh sửa](investigation.drawio)')
    for artifact in artifacts.get('architecture_diagrams') or []:
        if artifact.get('status') == 'updated':
            target = Path(artifact['diagram'])
            lines.append(f'- [Kiến trúc đã chú thích: {target.name}](../../{target.name})')
    if not artifacts.get('investigation_drawio') and not artifacts.get('architecture_diagrams'):
        lines.append('Không xuất sơ đồ theo tùy chọn hoặc thiếu kiến trúc gốc.')
    lines += ['', f'- Loại sơ đồ: `{kind}`',
              '- Đường nối chỉ lấy từ graph tham chiếu tĩnh đã tồn tại, không tự vẽ luồng nghiệp vụ.', '']
    if rejected:
        lines += ['## References không hợp lệ / ngoài phạm vi', '',
                  *[f'- `{r}`' for r in rejected[:15]], '']
    lines += ['## Giới hạn cần xác minh tiếp', '',
              '- Kiểm tra cấu hình runtime, dependency injection, reflection và SQL động nếu cần.',
              '- Các source file chưa được index có thể chưa xuất hiện trong báo cáo.',
              '- JSON, CSV và nhật ký gộp được lưu dưới `middle-files/`.', '']
    dest.write_text('\n'.join(lines), encoding='utf-8')


def write_investigation(repo, out, result, *, investigation_id=None, question=None,
                        status='completed', error=None, seed_refs=None,
                        diagram_type='auto', markdown=True, diagram=True,
                        update_drawio=True, overwrite_drawio=False):
    """Save one investigation's human and machine reports; no mutation of scanned source."""
    if overwrite_drawio and not update_drawio:
        raise ValueError('--overwrite-drawio requires diagram updates')
    if diagram_type not in ('auto', 'flow', 'impact', 'symbol'):
        raise ValueError('diagram_type must be auto|flow|impact|symbol')
    out = Path(out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    question = str(question if question is not None else result.get('question', ''))
    investigation_id = _id(question, investigation_id)
    dest = out / 'investigations' / investigation_id
    middle = out / 'middle-files'
    state = middle / 'investigations'
    dest.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    evidence, rejected = _source_evidence(repo, result, seed_refs)
    if status == 'completed' and not any(e['provenance'] == 'investigation' for e in evidence):
        status = 'insufficient-evidence'
    kind = _diagram_type(question, result, diagram_type)
    stack = _read_json(middle / 'stack_architecture.json')
    graph = _read_json(middle / 'architecture.json')
    machine_record = {'id': investigation_id, 'question': question, 'status': status,
                      'error': str(error)[:500] if error else None, 'diagram_type': kind,
                      'evidence': evidence, 'rejected_refs': rejected,
                      'investigation': result}
    raw_path = state / f'{investigation_id}.json'
    raw_path.write_text(json.dumps(machine_record, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    csv_path = state / f'{investigation_id}.evidence.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['path', 'line', 'ref', 'excerpt', 'provenance'])
        writer.writeheader()
        writer.writerows(evidence)
    artifacts = {'json': str(raw_path), 'evidence_csv': str(csv_path)}
    if diagram:
        path = dest / 'investigation.drawio'
        nodes, edges = _make_diagram(path, question, evidence, stack, graph, kind)
        artifacts.update(investigation_drawio=str(path), diagram_nodes=nodes, diagram_static_edges=edges)
        preview = dest / 'investigation.svg'
        artifacts.update(investigation_svg=str(preview), **_make_svg(preview, question, evidence, stack, graph, kind))
    registry_path = middle / 'investigation_annotations.json'
    if update_drawio:
        registry = _read_json(registry_path)
        snapshot = hashlib.sha256(json.dumps(graph.get('source_inventory', []),
                      ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        existing = [x for x in (registry.get('investigations', [])
                    if registry.get('project') == str(repo.root)
                    and registry.get('source_fingerprint') == snapshot else [])
                    if isinstance(x, dict) and x.get('id') != investigation_id]
        existing.append({'id': investigation_id, 'question': question[:250],
                         'files': sorted({e['path'] for e in evidence if e['provenance'] == 'investigation'}),
                         'status': status})
        records = existing[-100:]
        registry_path.write_text(json.dumps({'schema_version': 1, 'project': str(repo.root),
                        'source_fingerprint': snapshot, 'investigations': records},
                            ensure_ascii=False, indent=2), encoding='utf-8')
        artifacts['architecture_diagrams'] = _update_architecture(out, records, stack, graph, overwrite_drawio)
    if not diagram:
        for obsolete in ('investigation.drawio', 'investigation.svg'):
            if (dest / obsolete).is_file():
                (dest / obsolete).unlink()
    if markdown:
        md = dest / 'result.md'
        _save_markdown(md, investigation_id, question, result, evidence, rejected,
                       artifacts, kind, status, error)
        artifacts['markdown'] = str(md)
    elif (dest / 'result.md').is_file():
        (dest / 'result.md').unlink()
    return {'id': investigation_id, 'status': status, 'source_evidence_count': len([e for e in evidence if e['provenance']=='investigation']),
            'question_seed_count': len([e for e in evidence if e['provenance']=='question-seed']),
            'machine_data_in_middle_files': True, **artifacts}
