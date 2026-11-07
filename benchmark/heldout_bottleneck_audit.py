"""P1.13 retrospective audit of pinned held-out retrieval versus evidence selection.

Reads previously generated windows, labels and P1.11 evaluation only. Never
runs Ollama, reads source code or changes selector decisions. Window hits are
navigation opportunities, NOT proof that a span could fit the evidence budget.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median

MODES = ('baseline', 'adaptive_1', 'merge_balanced_1', 'merge_anchored_1')
VIEWS = ('hybrid', 'hybrid_plus_dense_1', 'hybrid_plus_dense_all')


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(items, label):
    if not isinstance(items, list) or not items:
        raise ValueError('Missing ' + label)
    result = {}
    for row in items:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in result:
            raise ValueError('Duplicate or invalid ID in ' + label)
        result[row['id']] = row
    return result


def _window(row, *, dense):
    if not isinstance(row, dict) or not isinstance(row.get('path'), str) or not row['path']:
        raise ValueError('Invalid source window path')
    lo = row.get('start_line') if dense else row.get('line_start')
    hi = row.get('end_line') if dense else row.get('line_end')
    if type(lo) is not int or type(hi) is not int or lo < 1 or hi < lo:
        raise ValueError('Invalid source window range')
    return row['path'], lo, min(hi, lo + 47)


def _hit(span, windows, *, complete=False):
    intervals = [(lo, hi) for path, lo, hi in windows if path == span['path']]
    if complete:
        return all(any(lo <= n <= hi for lo, hi in intervals)
                   for n in range(span['start_line'], span['end_line'] + 1))
    return any(lo <= span['end_line'] and hi >= span['start_line']
               for lo, hi in intervals)


def diagnose(labels, saved, evaluation):
    label_map = _rows(labels, 'labels')
    window_map = _rows(saved.get('cases'), 'source windows')
    result_map = _rows(evaluation.get('cases'), 'evaluation cases')
    if set(label_map) != set(window_map) or set(label_map) != set(result_map):
        raise ValueError('Mismatched case IDs across inputs')
    repo, commit = evaluation.get('repository'), evaluation.get('source_commit')
    suite = evaluation.get('suite')
    if (repo != saved.get('repo') or commit != (saved.get('method') or {}).get('frozen_source_commit')
            or suite != saved.get('suite')):
        raise ValueError('Frozen repository/commit/suite metadata mismatch')
    detail = []
    span_sizes = []
    view_total = {name: {'any': 0, 'complete': 0} for name in VIEWS}
    mode_total = {name: {'any': 0, 'complete': 0, 'partial': 0,
                         'available_in_hybrid_but_missed': 0,
                         'available_in_all_windows_but_missed': 0}
                  for name in MODES}
    for case_id, label in label_map.items():
        saved_case, output_case = window_map[case_id], result_map[case_id]
        if (label.get('question') != saved_case.get('question') or
                (label.get('repo'), label.get('commit'), label.get('suite')) != (repo, commit, suite)):
            raise ValueError('Case metadata differs in ' + case_id)
        spans = label.get('gold_spans')
        if not isinstance(spans, list) or not spans or len(spans) != output_case.get('gold_span_count'):
            raise ValueError('Gold spans missing or different in ' + case_id)
        seen = set()
        for span in spans:
            if not isinstance(span, dict):
                raise ValueError('Invalid span')
            sid = span.get('id')
            lo, hi = span.get('start_line'), span.get('end_line')
            if (not isinstance(sid, str) or not sid or sid in seen or
                    not isinstance(span.get('path'), str) or not span['path'] or
                    type(lo) is not int or type(hi) is not int or lo < 1 or hi < lo):
                raise ValueError('Invalid gold span ' + case_id)
            seen.add(sid)
            span_sizes.append(hi-lo+1)
        head = (((saved_case.get('variants') or {}).get('hybrid') or {}).get('top8_diagnostics'))
        extra = ((saved_case.get('multiwindow_diagnostics') or {}).get('alternates'))
        if not isinstance(head, list) or not 1 <= len(head) <= 8 or not isinstance(extra, list) or len(extra) > 4:
            raise ValueError('Invalid candidate inventory in ' + case_id)
        hybrid = [_window(x, dense=False) for x in head]
        alt = [_window(x, dense=True) for x in extra]
        if any(path not in {item[0] for item in hybrid} for path, _, _ in alt):
            raise ValueError('Dense alternate outside Hybrid files in ' + case_id)
        views = {
            'hybrid': hybrid,
            'hybrid_plus_dense_1': hybrid + alt[:1],
            'hybrid_plus_dense_all': hybrid + alt,
        }
        view_ids = {name: {'any': {s['id'] for s in spans if _hit(s, windows)},
                           'complete': {s['id'] for s in spans if _hit(s, windows, complete=True)}}
                    for name, windows in views.items()}
        outputs = {}
        modes = output_case.get('modes') or {}
        for name in MODES:
            item = modes.get(name)
            if not isinstance(item, dict):
                raise ValueError('Missing selected evidence mode in ' + case_id)
            any_hits = item.get('gold_any_line_ids')
            complete_hits = item.get('gold_complete_span_ids')
            if (not isinstance(any_hits, list) or not isinstance(complete_hits, list) or
                    len(set(any_hits)) != len(any_hits) or len(set(complete_hits)) != len(complete_hits)):
                raise ValueError('Invalid scored IDs in ' + case_id + ':' + name)
            any_set, complete_set = set(any_hits), set(complete_hits)
            if not complete_set <= any_set or not any_set <= seen:
                raise ValueError('Scored IDs inconsistent with labels in ' + case_id)
            if not any_set <= view_ids['hybrid_plus_dense_all']['any']:
                raise ValueError('Selected evidence lies outside candidate windows in ' + case_id)
            outputs[name] = {'any': sorted(any_set), 'complete': sorted(complete_set),
                             'partial': sorted(any_set - complete_set),
                             'missed_in_hybrid': sorted(view_ids['hybrid']['any'] - any_set),
                             'missed_in_all': sorted(view_ids['hybrid_plus_dense_all']['any'] - any_set)}
            entry = mode_total[name]
            entry['any'] += len(any_set)
            entry['complete'] += len(complete_set)
            entry['partial'] += len(any_set - complete_set)
            entry['available_in_hybrid_but_missed'] += len(view_ids['hybrid']['any'] - any_set)
            entry['available_in_all_windows_but_missed'] += len(view_ids['hybrid_plus_dense_all']['any'] - any_set)
        for name in VIEWS:
            view_total[name]['any'] += len(view_ids[name]['any'])
            view_total[name]['complete'] += len(view_ids[name]['complete'])
        detail.append({'id': case_id,
                       'gold_spans': [{'id': span['id'], 'length': span['end_line']-span['start_line']+1}
                                      for span in spans],
                       'window_opportunity': {k: {'any': sorted(v['any']), 'complete': sorted(v['complete'])}
                                              for k, v in view_ids.items()},
                       'selected': outputs})
    summary = evaluation.get('summary') or {}
    if summary.get('case_count') != len(detail) or summary.get('gold_spans_total') != len(span_sizes):
        raise ValueError('P1.11 summary case/span count mismatch')
    for name in MODES:
        old = (summary.get('modes') or {}).get(name) or {}
        if (old.get('gold_spans_any_line') != mode_total[name]['any'] or
                old.get('gold_spans_complete') != mode_total[name]['complete']):
            raise ValueError('P1.11 mode totals mismatch: ' + name)
    return {'summary': {'case_count': len(detail), 'gold_spans_total': len(span_sizes),
                        'span_length': {'min': min(span_sizes), 'median': median(span_sizes),
                                        'max': max(span_sizes),
                                        'single_line': sum(n == 1 for n in span_sizes),
                                        'over_10_lines': sum(n > 10 for n in span_sizes)},
                        'candidate_window_opportunity': view_total,
                        'selection': mode_total},
            'cases': detail,
            'notes': [
                'Retrospective audit; labels are never used to select candidates.',
                'Window overlap is navigation opportunity, not guaranteed source evidence.',
                'Window full coverage does not imply the 3000-character budget can preserve a full span.',
                'Any-line gold coverage is not generated-answer correctness.',
                "Click questions are internally authored, not third-party benchmark labels.",
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels-jsonl', type=Path, required=True)
    parser.add_argument('--from-report', type=Path, required=True, help='P1.12 source-window report')
    parser.add_argument('--evaluation', type=Path, required=True, help='P1.11 evaluated report')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    for path in (args.labels_jsonl, args.from_report, args.evaluation):
        if not path.is_file():
            parser.error('Missing input file: ' + str(path))
    if args.out.exists():
        parser.error('Refusing to overwrite existing audit report: ' + str(args.out))
    evaluation = json.loads(args.evaluation.read_text(encoding='utf-8'))
    inputs = evaluation.get('input_sha256') or {}
    if (inputs.get('cases_jsonl') != _sha(args.labels_jsonl) or
            inputs.get('source_window_report') != _sha(args.from_report)):
        parser.error('P1.11 saved input hashes differ from provided files')
    labels = [json.loads(line) for line in args.labels_jsonl.read_text(encoding='utf-8').splitlines() if line.strip()]
    windows = json.loads(args.from_report.read_text(encoding='utf-8'))
    report = diagnose(labels, windows, evaluation)
    report['inputs_sha256'] = {'labels': _sha(args.labels_jsonl),
                                'windows': _sha(args.from_report),
                                'evaluation': _sha(args.evaluation)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'summary': report['summary'], 'report': str(args.out)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
