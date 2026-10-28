"""Distribute independent incoming/outgoing edge anchors across Draw.io box perimeters.

No graph edges or vertex relationships are inferred or added. Only styles on
existing mxCells are updated. Port assignment is deterministic and idempotent.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

_MIN_SPACING = 22.0  # pixel distance between different ports on one side


def _geometry(cell):
    geo = cell.find('mxGeometry')
    if geo is None:
        return None
    try:
        x, y = float(geo.get('x', 0)), float(geo.get('y', 0))
        width, height = float(geo.get('width', 0)), float(geo.get('height', 0))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (x, y, width, height)


def _preferred_side(box, other):
    x, y, w, h = box
    ox, oy, ow, oh = other
    dx, dy = ox + ow / 2 - (x + w / 2), oy + oh / 2 - (y + h / 2)
    # Choose the side the edge actually travels toward, preserving
    # horizontal flow when the other node is mostly to the right/left.
    if abs(dx) >= abs(dy):
        return 'right' if dx >= 0 else 'left'
    return 'bottom' if dy >= 0 else 'top'


def _side_capacity(box, side):
    size = box[3] if side in ('left', 'right') else box[2]
    return max(1, int(size / _MIN_SPACING))


def _other_sides(side):
    # Keep preferred side when possible; use alternate adjacent sides before
    # sharing an anchor, and the opposite side as a last unique option.
    if side == 'left': return ('left', 'top', 'bottom', 'right')
    if side == 'right': return ('right', 'top', 'bottom', 'left')
    if side == 'top': return ('top', 'left', 'right', 'bottom')
    return ('bottom', 'left', 'right', 'top')


def _set_style(style, replacements):
    parts = [p for p in (style or '').split(';') if p]
    keys = set(replacements)
    parts = [p for p in parts if p.partition('=')[0] not in keys]
    return ';'.join(parts + [f'{k}={v}' for k, v in replacements.items()]) + ';'


def distribute_ports_in_root(root):
    """Assign distinct ports per vertex until its finite side slots overflow.

    Returns number of edge endpoints reanchored. Port spacing is bounded by
    the box's four side lengths; only beyond total unique slots is reuse used.
    """
    vertices = {}
    for cell in root.findall('.//mxCell'):
        if cell.get('vertex') == '1' and cell.get('id'):
            geom = _geometry(cell)
            if geom:
                vertices[cell.get('id')] = geom

    incident = defaultdict(list)
    for cell in root.findall('.//mxCell'):
        if cell.get('edge') != '1':
            continue
        src, dst = cell.get('source'), cell.get('target')
        if src not in vertices or dst not in vertices or src == dst:
            continue
        eid = cell.get('id', '')
        incident[src].append((cell, 'exit', _preferred_side(vertices[src], vertices[dst]), dst, eid))
        incident[dst].append((cell, 'entry', _preferred_side(vertices[dst], vertices[src]), src, eid))

    changed = 0
    for node_id, endpoints in incident.items():
        box = vertices[node_id]
        # Each endpoint, whether entry or exit, consumes a distinct slot.
        assigned = defaultdict(list)
        for item in sorted(endpoints, key=lambda e: (e[2], e[4], e[1])):
            side = item[2]
            for candidate in _other_sides(side):
                if len(assigned[candidate]) < _side_capacity(box, candidate):
                    assigned[candidate].append(item)
                    break
            else:
                # Every port in the perimeter is already occupied: reuse the
                # least loaded side. This is the only permitted overlap case.
                candidate = min(_other_sides(side), key=lambda s: len(assigned[s]) / _side_capacity(box, s))
                assigned[candidate].append(item)

        for side, edges in assigned.items():
            # Preserve geometric order of the other terminal, reducing crossings.
            if side in ('left', 'right'):
                edges.sort(key=lambda e: (vertices[e[3]][1] + vertices[e[3]][3]/2, e[4], e[1]))
            else:
                edges.sort(key=lambda e: (vertices[e[3]][0] + vertices[e[3]][2]/2, e[4], e[1]))
            capacity = _side_capacity(box, side)
            for i, (cell, prefix, _preferred, _other, _eid) in enumerate(edges):
                # For overflow, cycle through already allocated positions.
                index = i % capacity
                fraction = (index + 1) / (capacity + 1)
                coords = {
                    'left': ('0', fraction), 'right': ('1', fraction),
                    'top': (fraction, '0'), 'bottom': (fraction, '1'),
                }
                x, y = coords[side]
                cell.set('style', _set_style(cell.get('style', ''), {
                    prefix + 'X': f'{x:.6f}' if isinstance(x, float) else x,
                    prefix + 'Y': f'{y:.6f}' if isinstance(y, float) else y,
                    prefix + 'Perimeter': '1',
                }))
                changed += 1
    return changed


def spread_drawio_ports(path):
    """Rewrite existing Draw.io XML in-place (including multi-page Draw.io).

    Only uncompressed mxGraphModel XML is currently supported. Files which are
    not valid XML, or compressed diagrams, are untouched.
    """
    path = Path(path)
    tree = ET.parse(path)
    root = tree.getroot()
    count = 0
    for model in root.findall('.//mxGraphModel'):
        graph_root = model.find('root')
        if graph_root is not None:
            count += distribute_ports_in_root(graph_root)
    if count:
        tree.write(path, encoding='utf-8', xml_declaration=True)
    return count
