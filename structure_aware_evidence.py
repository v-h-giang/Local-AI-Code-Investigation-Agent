"""P1.14 experimental contiguous-code evidence packing (no gold labels).

Reads only pinned candidate windows, preserves verbatim numbered source lines and
chooses bounded contiguous neighborhoods under the same JSON-character budget.
This module is not imported by the production agent.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict

_NUMBERED = re.compile(r'^\s*(\d+)\s+\|\s')
_CAMEL = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')
_DECL = re.compile(r'\b(?:def|class|function|subroutine|module|interface|program|'
                   r'public|private|struct|enum)\b', re.I)
_CONTROL = re.compile(r'\b(?:if|else|elif|while|for|try|catch|except|finally|'
                      r'return|yield|raise|throw|await|call)\b', re.I)
_STOP = set(('what where which when how does with from that this into about using '
             'would should could there these whose code source file the for and '
             'are can you its via why implementation implemented').split())


def _terms(value):
    words = []
    for word in re.findall(r'[A-Za-z][A-Za-z0-9_]*', value):
        for chunk in word.split('_'):
            words.extend(_CAMEL.sub(' ', chunk).split())
    return {word.casefold() for word in words
            if len(word) >= 3 and word.casefold() not in _STOP}


def _json_size(excerpts):
    return len(json.dumps(excerpts, ensure_ascii=False))


def _window(row):
    if not isinstance(row, dict):
        raise ValueError('Invalid candidate window')
    path = row.get('path')
    lo = row.get('line_start', row.get('start_line'))
    hi = row.get('line_end', row.get('end_line'))
    if (not isinstance(path, str) or not path or '\\' in path
            or path.startswith('/') or '..' in path.split('/')
            or type(lo) is not int or type(hi) is not int
            or lo < 1 or hi < lo):
        raise ValueError('Invalid candidate source coordinates')
    return path, lo, min(hi, lo + 47)


def _extra_lines(candidate, earlier):
    path, start, end = candidate
    seen = set()
    for old_path, a, b in earlier:
        if old_path == path:
            seen.update(range(max(start, a), min(end, b) + 1))
    return end - start + 1 - len(seen)


def _inputs(saved_case, max_alternates=1):
    head = (((saved_case.get('variants') or {}).get('hybrid') or {})
            .get('top8_diagnostics'))
    alternates = ((saved_case.get('multiwindow_diagnostics') or {})
                  .get('alternates'))
    if (not isinstance(head, list) or not 1 <= len(head) <= 8
            or not isinstance(alternates, list) or len(alternates) > 4
            or type(max_alternates) is not int
            or not 0 <= max_alternates <= 4):
        raise ValueError('Invalid candidate inventory')
    originals = [_window(row) for row in head]
    allowed = {item[0] for item in originals}
    history = list(originals)
    selected = [(i + 1, 'hybrid', row) for i, row in enumerate(head)]
    for row in alternates:
        part = _window(row)
        if part[0] not in allowed:
            raise ValueError('Dense alternate is outside Hybrid files')
        novelty = _extra_lines(part, history)
        if type(row.get('new_lines')) is not int or novelty < 8 or row['new_lines'] != novelty:
            raise ValueError('Dense alternate source novelty mismatch')
        history.append(part)
    rank = {item[0]: i + 1 for i, item in enumerate(originals)}
    selected.extend((rank[row['path']], 'dense', row)
                    for row in alternates[:max_alternates])
    return selected


def _read_window(repo, row):
    path, lo, hi = _window(row)
    try:
        raw = repo.read_file(path, lo, hi)
    except (OSError, ValueError, TypeError, KeyError):
        return None
    numbered = []
    for text in raw.splitlines():
        match = _NUMBERED.match(text)
        if match:
            n = int(match.group(1))
            if lo <= n <= hi:
                numbered.append((n, text))
    if not numbered:
        return None
    if len({n for n, _ in numbered}) != len(numbered):
        raise ValueError('Repeated source line in repository read')
    if any(b[0] != a[0] + 1 for a, b in zip(numbered, numbered[1:])):
        raise ValueError('Source reader returned a noncontiguous window')
    return path, numbered


def _line_strength(raw, terms):
    matched = _terms(raw) & terms
    return (5.0 * len(matched) +
            2.0 * bool(_DECL.search(raw)) +
            0.7 * bool(_CONTROL.search(raw)))


def _make_excerpt(path, lines, *, source_lines_considered):
    refs = [f'{path}:{number}' for number, _ in lines]
    return {
        'path': path,
        'content': '\n'.join(raw for _, raw in lines),
        'source_refs': refs,
        'visible_refs': refs,
        'compressed': True,
        'source_lines_considered': source_lines_considered,
    }


def _candidates(path, lines, question_terms, rank, origin, *, block_lengths):
    # Rank candidate centers by question overlap and structural code cues.
    ranked = sorted(range(len(lines)), key=lambda i:
                    (-_line_strength(lines[i][1], question_terms), i))
    found = {}
    for width in block_lengths:
        selected_centers = []
        for i in ranked:
            if any(abs(i - other) < max(2, width // 2)
                   for other in selected_centers):
                continue
            selected_centers.append(i)
            if len(selected_centers) == 4:
                break
        for center in selected_centers:
            # Declarations anchor the start; expressions retain context both sides.
            left = 0 if _DECL.search(lines[center][1]) else 2
            start = max(0, center - left)
            end = min(len(lines), start + width)
            start = max(0, end - width)
            chunk = lines[start:end]
            if not chunk:
                continue
            key = (path, chunk[0][0], chunk[-1][0])
            found.setdefault(key, (
                _make_excerpt(path, chunk, source_lines_considered=len(lines)),
                rank, origin))
    return list(found.values())


def _utility(snippet, rank, origin, chosen_terms, chosen_paths, question_terms):
    words = _terms(snippet['content']) & question_terms
    novel = words - chosen_terms
    structural = sum(bool(_DECL.search(s)) for s in snippet['content'].splitlines())
    control = sum(bool(_CONTROL.search(s)) for s in snippet['content'].splitlines())
    new_file = snippet['path'] not in chosen_paths
    return (1.0 + 5 * len(novel) + 1.6 * len(words) +
            1.8 * min(3, structural) + 0.7 * min(4, control) +
            2.0 / max(1, rank) + (1.5 if new_file else 0) +
            (0.25 if origin == 'hybrid' else 0))


def pack_contiguous_evidence(repo, saved_case, *, max_chars=3000, limit=6,
                             max_alternates=1, block_lengths=(8, 12)):
    """Gold-blind bounded greedy choice of intact contiguous code blocks.

    Two predefined block widths are tried, without selecting or tuning widths
    using benchmark labels. Each original file:line is displayed at most once.
    """
    if (type(max_chars) is not int or max_chars < 500
            or type(limit) is not int or not 1 <= limit <= 12
            or not isinstance(block_lengths, tuple) or not block_lengths
            or any(type(n) is not int or n < 2 or n > 24 for n in block_lengths)):
        raise ValueError('Invalid evidence packing configuration')
    question = saved_case.get('question')
    if not isinstance(question, str) or not question.strip():
        raise ValueError('Question is required')
    terms = _terms(question)
    choices = []
    observed = {}
    read_windows = 0
    for rank, origin, row in _inputs(saved_case, max_alternates):
        loaded = _read_window(repo, row)
        if loaded is None:
            continue
        read_windows += 1
        path, numbered = loaded
        for line, raw in numbered:
            key = (path, line)
            if key in observed and observed[key] != raw:
                raise ValueError('Inconsistent numbered source line')
            observed[key] = raw
        choices.extend(_candidates(path, numbered, terms, rank, origin,
                                   block_lengths=block_lengths))
    picked = []
    picked_refs = set()
    chosen_terms = set()
    chosen_paths = set()
    while len(picked) < limit:
        best = None
        for i, (excerpt, rank, origin) in enumerate(choices):
            refs = set(excerpt['source_refs'])
            # Keep every displayed excerpt contiguous; never silently remove
            # overlapping lines from the middle of an already built block.
            if not refs.isdisjoint(picked_refs):
                continue
            trial = picked + [excerpt]
            if _json_size(trial) > max_chars:
                continue
            increment = _json_size(trial) - _json_size(picked)
            value = _utility(excerpt, rank, origin, chosen_terms,
                             chosen_paths, terms) / math.sqrt(max(1, increment))
            if best is None or value > best[0]:
                best = (value, i, excerpt)
        if best is None:
            break
        _, _, chosen = best
        picked.append(chosen)
        picked_refs.update(chosen['source_refs'])
        chosen_terms.update(_terms(chosen['content']) & terms)
        chosen_paths.add(chosen['path'])
    return {
        'excerpts': picked,
        'serialized_chars': _json_size(picked),
        'read_candidate_windows': read_windows,
        'candidate_blocks': len(choices),
        'selected_blocks': len(picked),
        'selected_source_lines': len(picked_refs),
        'block_lengths': list(block_lengths),
    }
