"""Report per-case gold evidence changes from a saved P1.7 A/B result.

Input: benchmark/context_budget_ablation.py JSON output. The tool compares
reported source-reference overlap and context accounting without reranking.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MODES = ('baseline', 'adaptive_0', 'adaptive_1', 'adaptive_2')
COMPARISONS = (
    ('adaptive_0', 'baseline'),
    ('adaptive_1', 'baseline'),
    ('adaptive_2', 'baseline'),
    ('adaptive_1', 'adaptive_0'),
    ('adaptive_2', 'adaptive_1'),
)


def _checked_mode(row, name, case_id):
    obj = (row.get('modes') or {}).get(name)
    if not isinstance(obj, dict):
        raise ValueError(f'Missing {name} for {case_id}')
    ids = obj.get('gold_citable_ids')
    visible = obj.get('gold_visible_ids')
    if (not isinstance(ids, list) or not isinstance(visible, list)
            or any(not isinstance(x, str) for x in ids + visible)
            or len(ids) != len(set(ids)) or len(visible) != len(set(visible))
            or not set(ids).issubset(visible)):
        raise ValueError(f'Invalid visible/citable span IDs in {case_id}:{name}')
    for field in ('serialized_chars', 'displayed_source_lines', 'selected_dense_alternates'):
        if type(obj.get(field)) is not int or obj[field] < 0:
            raise ValueError(f'Invalid {field} in {case_id}:{name}')
    if obj.get('gold_spans_citable') != len(ids):
        raise ValueError(f'Inconsistent citable gold span count in {case_id}:{name}')
    return obj


def diagnose(report):
    """Compare saved selections; no decisions are made from benchmark labels."""
    rows = report.get('cases')
    header = report.get('summary') or {}
    if not isinstance(rows, list) or not rows:
        raise ValueError('Missing saved case records')
    budget = header.get('max_chars_per_case')
    if type(budget) is not int or budget < 1:
        raise ValueError('Missing per-case character budget')
    seen = set()
    checked = []
    for row in rows:
        case_id = row.get('id')
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError('Missing or duplicate case ID')
        seen.add(case_id)
        modes = {name: _checked_mode(row, name, case_id) for name in MODES}
        if any(obj['serialized_chars'] > budget for obj in modes.values()):
            raise ValueError(f'Character budget exceeded in {case_id}')
        checked.append((case_id, modes))

    if header.get('case_count') != len(checked):
        raise ValueError('Case count differs from saved summary')
    for name in MODES:
        saved_summary = (header.get('modes') or {}).get(name) or {}
        for field in ('gold_spans_citable', 'serialized_chars',
                      'displayed_source_lines', 'selected_dense_alternates'):
            if sum(modes[name][field] for _, modes in checked) != saved_summary.get(field):
                raise ValueError(f'Summary differs from cases for {name}.{field}')

    comparisons = {}
    changed_cases = []
    changes_by_case = {}
    for target, source in COMPARISONS:
        label = f'{target}_vs_{source}'
        counts = {
            'gross_gold_span_gains': 0,
            'gross_gold_span_losses': 0,
            'cases_gaining_gold': 0,
            'cases_losing_gold': 0,
            'delta_serialized_chars': 0,
            'delta_displayed_source_lines': 0,
            'delta_dense_alternates': 0,
        }
        for case_id, modes in checked:
            new = modes[target]
            old = modes[source]
            gained = sorted(set(new['gold_citable_ids']) - set(old['gold_citable_ids']))
            lost = sorted(set(old['gold_citable_ids']) - set(new['gold_citable_ids']))
            counts['gross_gold_span_gains'] += len(gained)
            counts['gross_gold_span_losses'] += len(lost)
            counts['cases_gaining_gold'] += bool(gained)
            counts['cases_losing_gold'] += bool(lost)
            counts['delta_serialized_chars'] += new['serialized_chars'] - old['serialized_chars']
            counts['delta_displayed_source_lines'] += (
                new['displayed_source_lines'] - old['displayed_source_lines'])
            counts['delta_dense_alternates'] += (
                new['selected_dense_alternates'] - old['selected_dense_alternates'])
            if gained or lost:
                changes_by_case.setdefault(case_id, {})[label] = {
                    'gained_gold_span_ids': gained,
                    'lost_gold_span_ids': lost,
                    'delta_chars': new['serialized_chars'] - old['serialized_chars'],
                    'delta_source_lines': (
                        new['displayed_source_lines'] - old['displayed_source_lines']),
                    'old_dense_windows': old['selected_dense_alternates'],
                    'new_dense_windows': new['selected_dense_alternates'],
                }
        counts['net_gold_span_change'] = (
            counts['gross_gold_span_gains'] - counts['gross_gold_span_losses'])
        comparisons[label] = counts

    for case_id, _ in checked:
        if case_id in changes_by_case:
            changed_cases.append({'id': case_id, 'comparisons': changes_by_case[case_id]})
    return {
        'summary': {
            'case_count': len(checked),
            'max_chars_per_case': budget,
            'comparisons': comparisons,
            'changed_case_count': len(changed_cases),
            'changed_case_ids': [case['id'] for case in changed_cases],
        },
        'changed_cases': changed_cases,
        'notes': [
            'Compares previously recorded prefetch source-reference overlap.',
            'Per-case gains and losses are not final answer correctness.',
            'No new evidence selection or source reading is performed.',
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--from-report', required=True, type=Path)
    p.add_argument('--out', type=Path)
    p.add_argument('--summary-only', action='store_true')
    args = p.parse_args(argv)
    if not args.from_report.is_file():
        p.error('P1.7 A/B report missing: ' + str(args.from_report))
    report = json.loads(args.from_report.read_text(encoding='utf-8'))
    result = diagnose(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8')
    display = {'summary': result['summary']}
    if not args.summary_only:
        display['changed_cases'] = result['changed_cases']
    display['report'] = str(args.out) if args.out else None
    print(json.dumps(display, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
