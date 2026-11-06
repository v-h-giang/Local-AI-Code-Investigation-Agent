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
