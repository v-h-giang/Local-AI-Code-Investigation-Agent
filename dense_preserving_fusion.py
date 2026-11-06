"""Experimental read-only hybrid-head + dense-tail candidate fusion.

Keep the top-eight Hybrid candidates (and their existing source windows)
unchanged, then fill deeper candidate slots from Dense before the remaining
Hybrid tail. This is an ablation of ranking allocation, not a new model or
evidence selection algorithm. It does NOT guarantee higher top-20 recall.
Gold labels and the source repository are never read by this module.
"""
from __future__ import annotations


def hybrid_head_dense_tail(hybrid_rows, dense_rows, *, limit=30, head=8):
    """Deterministic, path-deduplicated candidate fusion.

    Hybrid top head are always kept first. Dense tail candidates preserve
    their source-chunk windows. Hybrid-only tail candidates are kept only if
    the remaining capacity permits. A candidate is never a citation.
    """
    limit = max(1, min(50, int(limit)))
    head = max(0, min(limit, int(head)))
    output = []
    seen = set()

    def append(item, *, dense_tail=False):
        if not isinstance(item, dict):
            return
        path = item.get('path')
        if not isinstance(path, str) or not path or path in seen:
            return
        row = dict(item)
        if dense_tail:
            start, end = row.get('start_line'), row.get('end_line')
            if isinstance(start, int) and isinstance(end, int) and start > 0 and end >= start:
                row['line_start'] = start
                row['line_end'] = end
                row.setdefault('line_hint', start + (end - start) // 2)
                row['line_hint_source'] = 'dense'
            row['candidate_origin'] = 'qwen3-dense-tail'
            row['kind'] = 'semantic-file-candidate'
            row['file_role'] = 'implementation'
            row['retrieval_views'] = ['dense']
            row['fusion_role'] = 'dense-tail'
        else:
            row['fusion_role'] = 'hybrid-head' if len(output) < head else 'hybrid-tail'
        row['citation'] = False
        seen.add(path)
        output.append(row)

    for row in hybrid_rows[:head]:
        if len(output) >= limit:
            break
        append(row)

    for row in dense_rows:
        if len(output) >= limit:
            break
        append(row, dense_tail=True)

    for row in hybrid_rows[head:]:
        if len(output) >= limit:
            break
        append(row)

    return output


def _tail_row(item, *, origin):
    """Copy one candidate without upgrading it to source evidence."""
    row = dict(item)
    if origin == 'dense':
        start, end = row.get('start_line'), row.get('end_line')
        if isinstance(start, int) and isinstance(end, int) and start > 0 and end >= start:
            row['line_start'] = start
            row['line_end'] = end
            row.setdefault('line_hint', start + (end - start) // 2)
            row['line_hint_source'] = 'dense'
        row['candidate_origin'] = 'qwen3-dense-tail'
        row['retrieval_views'] = ['dense']
        row['file_role'] = 'implementation'
    row['fusion_role'] = origin + '-tail'
    row['citation'] = False
    return row


def hybrid_head_interleaved_tail(hybrid_rows, dense_rows, *, limit=30, head=8):
    """Keep Hybrid head; then alternate distinct Dense and Hybrid tail paths.

    This fixed, gold-blind 1:1 allocation prevents either view monopolizing
    the first twenty slots. Exhausted lists fall back to the other view.
    """
    limit = max(1, min(50, int(limit)))
    head = max(0, min(limit, int(head)))
    output = []
    seen = set()

    def add(item, origin):
        if not isinstance(item, dict):
            return False
        path = item.get('path')
        if not isinstance(path, str) or not path or path in seen:
            return False
        row = _tail_row(item, origin=origin)
        if origin == 'hybrid-head':
            row['fusion_role'] = 'hybrid-head'
        output.append(row)
        seen.add(path)
        return True

    for item in hybrid_rows[:head]:
        if len(output) >= limit:
            break
        add(item, 'hybrid-head')

    dense_iter = iter(dense_rows)
    hybrid_iter = iter(hybrid_rows[head:])
    exhausted = {'dense': False, 'hybrid': False}
    turn = 'dense'
    while len(output) < limit and not all(exhausted.values()):
        stream = dense_iter if turn == 'dense' else hybrid_iter
        found = False
        for item in stream:
            if add(item, turn):
                found = True
                break
        if not found:
            exhausted[turn] = True
        turn = 'hybrid' if turn == 'dense' else 'dense'
    return output


def hybrid_head_rrf_tail(hybrid_rows, dense_rows, *, limit=30, head=8,
                         rrf_k=40):
    """Keep Hybrid head; reciprocal-rank fuse the remaining path inventory.

    Both tail views have fixed weight 1.0. Paths seen in both views receive
    evidence-free ranking boosts; a Dense chunk window is preferred for
    tail paths that have a valid Dense source window.
    """
    limit = max(1, min(50, int(limit)))
    head = max(0, min(limit, int(head)))
    rrf_k = max(1, int(rrf_k))
    output = []
    seen = set()
    for item in hybrid_rows[:head]:
        if not isinstance(item, dict):
            continue
        path = item.get('path')
        if isinstance(path, str) and path and path not in seen:
            output.append(_tail_row(item, origin='hybrid-head'))
            output[-1]['fusion_role'] = 'hybrid-head'
            seen.add(path)
        if len(output) >= limit:
            return output

    scores = {}
    hybrid_by_path = {}
    dense_by_path = {}
    for origin, stream, table in (
            ('hybrid', hybrid_rows[head:], hybrid_by_path),
            ('dense', dense_rows, dense_by_path)):
        for position, item in enumerate(stream, 1):
            if not isinstance(item, dict):
                continue
            path = item.get('path')
            if not isinstance(path, str) or not path or path in seen:
                continue
            if path in table:
                continue
            table[path] = item
            scores[path] = scores.get(path, 0.0) + 1.0 / (rrf_k + position)

    for path in sorted(scores, key=lambda p: (-scores[p], p)):
        if len(output) >= limit:
            break
        # Keep the original Dense window for the same path if available.
        item = dense_by_path.get(path) or hybrid_by_path[path]
        origin = 'dense' if path in dense_by_path else 'hybrid'
        row = _tail_row(item, origin=origin)
        row['fusion_role'] = 'rrf-tail'
        row['tail_rrf_score'] = round(scores[path], 8)
        row['tail_views'] = [
            key for key, mapping in (
                ('hybrid', hybrid_by_path), ('dense', dense_by_path))
            if path in mapping]
        output.append(row)
        seen.add(path)
    return output
