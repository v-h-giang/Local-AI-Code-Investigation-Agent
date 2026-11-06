"""Experimental budget-based ranking of source excerpts.

Inputs are indexed file windows and a repository reader. The output contains
complete numbered source lines and their corresponding references. Selection
uses lexical match, novelty, source structure, and serialized character cost.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from context_compression import compress

_NUMBERED = re.compile(r'^\s*(\d+)\s+\|\s')
_CAMEL = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')
_DECL = re.compile(
    r'\b(?:def|class|subroutine|function|module|interface|program|'
    r'return|call|await|async|public|private|try|except|throw)\b', re.I)
_STOP = frozenset({
    'what', 'where', 'which', 'when', 'how', 'does', 'with', 'from',
    'that', 'this', 'into', 'about', 'using', 'would', 'should', 'could',
    'there', 'these', 'whose', 'code', 'source', 'file', 'implementation',
    'implemented', 'the', 'for', 'and', 'are', 'all', 'can', 'you',
    'its', 'via', 'who', 'why',
})


def _tokens(text: str) -> set[str]:
    parts = []
    for word in re.findall(r'[A-Za-z][A-Za-z0-9_]*', text):
        for piece in word.split('_'):
            parts.extend(_CAMEL.sub(' ', piece).split())
    return {part.casefold() for part in parts
            if len(part) >= 3 and part.casefold() not in _STOP}


def _size(excerpts: list[dict[str, Any]]) -> int:
    return len(json.dumps(excerpts, ensure_ascii=False))


def _window(row: dict[str, Any]) -> tuple[str, int, int] | None:
    path = row.get('path')
    start = row.get('line_start')
    end = row.get('line_end')
    if start is None:
        start = row.get('start_line')
    if end is None:
        end = row.get('end_line')
    if (not isinstance(path, str) or not path or type(start) is not int
            or type(end) is not int or start < 1 or end < start):
        return None
    return path, start, min(end, start + 47)


def _new_lines(part: tuple[str, int, int], existing: list[tuple[str, int, int]]) -> int:
    path, start, end = part
    covered: set[int] = set()
    for existing_path, lo, hi in existing:
        if path == existing_path:
            covered.update(range(max(start, lo), min(end, hi) + 1))
    return end - start + 1 - len(covered)


def _inputs(saved_case: dict[str, Any], max_alternates: int):
    if type(max_alternates) is not int or max_alternates not in (0, 1, 2):
        raise ValueError('max_alternates must be 0, 1 or 2')
    head = (((saved_case.get('variants') or {}).get('hybrid') or {})
            .get('top8_diagnostics'))
    alternatives = ((saved_case.get('multiwindow_diagnostics') or {})
                    .get('alternates'))
    if not isinstance(head, list) or not 1 <= len(head) <= 8:
        raise ValueError('Missing Hybrid top-eight candidate windows')
    if not isinstance(alternatives, list) or len(alternatives) > 4:
        raise ValueError('Missing alternate Dense candidate windows')
    original = [_window(row) for row in head]
    if any(part is None for part in original):
        raise ValueError('Invalid Hybrid window coordinates')
    allowed = {part[0] for part in original}
    validated = list(original)
    for row in alternatives:
        part = _window(row)
        if part is None or part[0] not in allowed:
            raise ValueError('Dense window outside Hybrid top-eight file scope')
        gain = _new_lines(part, validated)
        if gain < 8 or gain != row.get('new_lines'):
            raise ValueError('Dense window does not match saved novel-line count')
        validated.append(part)
    ranks = {part[0]: i for i, part in enumerate(original, 1)}
    entries = [(i, 'hybrid', head[i-1]) for i in range(1, len(head) + 1)]
    entries.extend((ranks[row['path']], 'dense', row)
                   for row in alternatives[:max_alternates])
    return entries


def _read_numbered(repo, row: dict[str, Any]):
    part = _window(row)
    if part is None:
        return None
    path, start, end = part
    try:
        raw = repo.read_file(path, start, end)
    except (OSError, ValueError, TypeError, KeyError):
        return None
    numbered = []
    seen = set()
    for line in raw.splitlines():
        match = _NUMBERED.match(line)
        if match:
            number = int(match.group(1))
            if start <= number <= end and number not in seen:
                numbered.append((number, line))
                seen.add(number)
    return (path, numbered) if numbered else None


def _excerpt(path, numbered, question, cap):
    result = compress(path, numbered, question, max_chars=cap,
                      mode='structure_mmr', llm=None)
    if result is None:
        return None
    expected = {line: text for line, text in numbered}
    displayed = []
    text_lines = result.get('content')
    if not isinstance(text_lines, str):
        raise ValueError('Excerpt content must be a string')
    for text in text_lines.splitlines():
        match = _NUMBERED.match(text)
        if not match:
            raise ValueError('Excerpt contains a non-source line')
        number = int(match.group(1))
        if expected.get(number) != text:
            raise ValueError('Excerpt line differs from repository read')
        displayed.append(f'{path}:{number}')
    source_refs = result.get('source_refs')
    visible_refs = result.get('visible_refs')
    if (not displayed or not isinstance(source_refs, list)
            or not isinstance(visible_refs, list)
            or source_refs != displayed or visible_refs != displayed):
        raise ValueError('Excerpt refs differ from numbered displayed source')
    if len(json.dumps(result, ensure_ascii=False)) > cap:
        raise ValueError('Compressor exceeded per-window budget')
    return result


def _utility(snippet, query_terms, chosen, file_rank, origin):
    refs = set(snippet['source_refs'])
    used_refs: set[str] = set()
    covered_terms: set[str] = set()
    used_paths: set[str] = set()
    for previous in chosen:
        used_refs.update(previous['source_refs'])
        covered_terms.update(_tokens(previous['content']))
        used_paths.add(previous['path'])
    novel_refs = refs - used_refs
    if not novel_refs:
        return 0.0
    terms = _tokens(snippet['content'])
    matched = terms & query_terms
    newly_matched = matched - covered_terms
    declarations = sum(bool(_DECL.search(line))
                       for line in snippet['content'].splitlines())
    duplicate_fraction = 1 - len(novel_refs) / len(refs)
    value = (1.0 + 6.0 * len(newly_matched) + 1.5 * len(matched)
             + 0.7 * min(declarations, 5)
             + 0.25 * min(len(novel_refs), 8)
             + 1.0 / max(1, file_rank)
             + (0.8 if snippet['path'] not in used_paths else 0)
             + (0.3 if origin == 'hybrid' else 0))
    return value * (1.0 - 0.75 * duplicate_fraction)


def select_evidence(repo, saved_case, *, max_chars=3000,
                    max_alternates=2, limit=6, caps=(420, 600, 780)):
    """Build and rank full source extracts under one shared JSON-char budget.

    At most one excerpt is selected per candidate window. Cap alternatives
    compete using the same scoring function. Ranking has no reserved slots.
    """
    if (type(max_chars) is not int or max_chars < 1000
            or type(limit) is not int or not 1 <= limit <= 12):
        raise ValueError('Invalid character or excerpt budget')
    if (not isinstance(caps, tuple) or not caps or
            any(type(cap) is not int or cap < 200 or cap > 1200
                for cap in caps)):
        raise ValueError('Invalid per-excerpt caps')
    if not isinstance(saved_case.get('question'), str):
        raise ValueError('Question is required')
    entries = _inputs(saved_case, max_alternates)
    question = saved_case['question']
    query_terms = _tokens(question)
    choices = []
    attempted = 0
    for i, (rank, origin, row) in enumerate(entries):
        source = _read_numbered(repo, row)
        if source is None:
            continue
        attempted += 1
        path, numbered = source
        signatures = set()
        for cap in sorted(set(caps)):
            snippet = _excerpt(path, numbered, question, cap)
            if snippet is None:
                continue
            signature = tuple(snippet['source_refs'])
            if signature in signatures:
                continue
            signatures.add(signature)
            choices.append((i, rank, origin, snippet))
    output = []
    selected = set()
    origins = []
    while len(output) < limit:
        ranked = []
        for window_id, file_rank, origin, snippet in choices:
            if window_id in selected:
                continue
            candidate = output + [snippet]
            size = _size(candidate)
            if size > max_chars:
                continue
            novelty = _utility(snippet, query_terms, output, file_rank, origin)
            if novelty <= 0:
                continue
            incremental = size - _size(output)
            score = novelty / math.sqrt(max(incremental, 1))
            ranked.append((-score, file_rank,
                           0 if origin == 'hybrid' else 1,
                           window_id, incremental, snippet, origin))
        if not ranked:
            break
        ranked.sort(key=lambda x: x[:5])
        _, _, _, window_id, _, snippet, origin = ranked[0]
        output.append(snippet)
        origins.append(origin)
        selected.add(window_id)
    if _size(output) > max_chars:
        raise RuntimeError('Evidence allocation exceeds total budget')
    return {
        'excerpts': output,
        'serialized_chars': _size(output),
        'candidate_windows_read': attempted,
        'candidate_excerpt_options': len(choices),
        'selected_excerpts': len(output),
        'selected_dense_alternates': origins.count('dense'),
        'selected_hybrid_windows': origins.count('hybrid'),
        'displayed_source_lines': sum(len(item['visible_refs']) for item in output),
        'citable_source_lines': sum(len(item['source_refs']) for item in output),
        'selection_origins': origins,
    }
