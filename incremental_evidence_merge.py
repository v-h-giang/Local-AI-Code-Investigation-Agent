"""Experimental incremental selection of numbered source evidence.

Candidates are existing baseline/adaptive excerpts. The selector deduplicates
source line references, groups adjacent lines, and allocates a shared JSON
character budget. Two policies vary whether baseline anchors are seeded.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict

_LINE = re.compile(r'^\s*(\d+)\s+\|\s')
_CAMEL = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')
_DECL = re.compile(r'\b(?:def|class|function|subroutine|module|interface|program|'
                   r'async|await|return|call|throw|if|try|except)\b', re.I)
_STOP = frozenset(('what where which when how does with from that this into '
                   'about using would should could there these whose code '
                   'source file the for and are can you its via why').split())


def _tokens(value):
    words = []
    for token in re.findall(r'[A-Za-z][A-Za-z0-9_]*', value):
        for word in token.split('_'):
            words.extend(_CAMEL.sub(' ', word).split())
    return {x.casefold() for x in words if len(x) >= 3 and x.casefold() not in _STOP}


def _size(rows):
    return len(json.dumps(rows, ensure_ascii=False))


def _pool(baseline, adaptive):
    """Provenance-verified union keyed by source path and exact line number."""
    if not isinstance(baseline, list) or not isinstance(adaptive, list):
        raise ValueError('Both evidence inputs must be lists')
    pool = {}
    sources = defaultdict(set)
    base_groups = []
    order = {}
    for origin, excerpts in (('baseline', baseline), ('adaptive', adaptive)):
        for index, excerpt in enumerate(excerpts):
            path = excerpt.get('path')
            content = excerpt.get('content')
            if not isinstance(path, str) or not path or not isinstance(content, str):
                raise ValueError('Invalid excerpt path/content')
            refs = []
            for raw in content.splitlines():
                m = _LINE.match(raw)
                if m is None:
                    raise ValueError('Unnumbered source text')
                num = int(m.group(1))
                ref = f'{path}:{num}'
                refs.append(ref)
                if ref in pool and pool[ref] != raw:
                    raise ValueError('Conflicting original source lines')
                pool[ref] = raw
                sources[ref].add(origin)
                if path not in order:
                    order[path] = len(order)
            if not refs or refs != excerpt.get('source_refs') or refs != excerpt.get('visible_refs'):
                raise ValueError('Source refs differ from displayed source')
            if origin == 'baseline':
                base_groups.append(tuple(refs))
    return pool, sources, base_groups, order


def _segments(pool, sources, order, max_block=3):
    grouped = defaultdict(list)
    for ref in pool:
        path, sep, raw_num = ref.rpartition(':')
        if not sep or not raw_num.isdecimal():
            raise ValueError('Invalid source reference')
        grouped[path].append((int(raw_num), ref))
    blocks = []
    for path in sorted(grouped, key=lambda p: order[p]):
        positions = sorted(grouped[path])
        cluster = []
        for n, ref in positions:
            if cluster and (n != cluster[-1][0] + 1 or len(cluster) == max_block):
                blocks.append(tuple(x[1] for x in cluster))
                cluster = []
            cluster.append((n, ref))
        if cluster:
            blocks.append(tuple(x[1] for x in cluster))
    return blocks


def _render(selected, pool, order):
    by_path = defaultdict(list)
    for ref in selected:
        path, _, n = ref.rpartition(':')
        by_path[path].append((int(n), ref))
    output = []
    for path in sorted(by_path, key=lambda p: order[p]):
        rows = sorted(by_path[path])
        refs = [ref for _, ref in rows]
        output.append({
            'path': path,
            'content': '\n'.join(pool[ref] for ref in refs),
            'source_refs': refs,
            'visible_refs': refs,
            'compressed': True,
            'source_lines_considered': sum(r.startswith(path+':') for r in pool),
        })
    return output


def _utility(block, pool, sources, question_terms, selected, policy):
    missing = [ref for ref in block if ref not in selected]
    if not missing:
        return 0.0
    covered = set().union(*(_tokens(pool[ref]) for ref in selected)) if selected else set()
    words = set().union(*(_tokens(pool[ref]) for ref in missing))
    matched = words & question_terms
    new_query = matched - covered
    declarations = sum(bool(_DECL.search(pool[ref])) for ref in missing)
    baseline_count = sum('baseline' in sources[ref] for ref in missing)
    adaptive_count = sum('adaptive' in sources[ref] for ref in missing)
    common = sum(len(sources[ref]) == 2 for ref in missing)
    # Baseline has a stronger prior in 'anchored' mode; both policies value
    # query-match novelty and structural code lines over raw line volume.
    base_bonus = (3.5 if policy == 'anchored' else 1.5) * baseline_count
    return (1 + 5 * len(new_query) + 2 * len(matched) +
            2 * declarations + base_bonus + 0.8 * adaptive_count +
            1.0 * common + 0.3 * len(missing))


def merge_evidence(baseline, adaptive, question, *, policy='balanced',
                   max_chars=3000, limit=6, max_block=3):
    """Choose numbered lines under one shared JSON-character budget.

    `balanced` globally ranks blocks. `anchored` first reserves one strongest
    source block per baseline excerpt when space permits, then ranks the rest.
    """
    if policy not in ('balanced', 'anchored'):
        raise ValueError('Unknown merge policy')
    if not isinstance(question, str) or not question.strip():
        raise ValueError('Question is required')
    if (type(max_chars) is not int or max_chars < 500 or
            type(limit) is not int or limit < 1 or limit > 12 or
            type(max_block) is not int or not 1 <= max_block <= 8):
        raise ValueError('Invalid budget, limit or grouping')
    pool, sources, base_groups, order = _pool(baseline, adaptive)
    blocks = _segments(pool, sources, order, max_block=max_block)
    question_terms = _tokens(question)
    selected = set()
    selected_blocks = []

    def candidate_info(block):
        missing = set(block) - selected
        if not missing:
            return None
        trial = selected | missing
        output = _render(trial, pool, order)
        if len(output) > limit or _size(output) > max_chars:
            return None
        incremental = _size(output) - _size(_render(selected, pool, order))
        score = _utility(block, pool, sources, question_terms, selected, policy) / math.sqrt(max(1, incremental))
        return score, trial

    if policy == 'anchored':
        # Ensure one baseline block survives from each original excerpt, when
        # feasible; a baseline excerpt may have multiple nonadjacent blocks.
        for original in base_groups:
            options = [(candidate_info(block), idx, block)
                       for idx, block in enumerate(blocks) if set(block) & set(original)]
            options = [(info, idx, block) for info, idx, block in options if info is not None]
            if options:
                options.sort(key=lambda x: (-x[0][0], x[1]))
                _, _, chosen = options[0]
                selected.update(chosen)
                selected_blocks.append(chosen)

    while True:
        candidates = []
        for idx, block in enumerate(blocks):
            info = candidate_info(block)
            if info is not None:
                candidates.append((-info[0], idx, block))
        if not candidates:
            break
        candidates.sort(key=lambda row: row[:2])
        choice = candidates[0][2]
        if not set(choice) - selected:
            break
        selected.update(choice)
        selected_blocks.append(choice)

    excerpts = _render(selected, pool, order)
    if _size(excerpts) > max_chars or len(excerpts) > limit:
        raise RuntimeError('Merge output violates budget')
    baseline_refs = {ref for ref in pool if 'baseline' in sources[ref]}
    adaptive_refs = {ref for ref in pool if 'adaptive' in sources[ref]}
    return {
        'excerpts': excerpts,
        'serialized_chars': _size(excerpts),
        'retained_baseline_source_lines': len(selected & baseline_refs),
        'lost_baseline_source_lines': len(baseline_refs - selected),
        'added_adaptive_source_lines': len(selected & (adaptive_refs - baseline_refs)),
        'selected_source_lines': len(selected),
        'selected_source_files': len(excerpts),
        'selected_blocks': len(selected_blocks),
        'policy': policy,
    }
