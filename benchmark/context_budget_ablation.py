"""P1.7 source-backed comparison of context allocation at equal budgets.

The comparison uses a saved candidate-window report and a pinned checkout.
Gold spans enter only the scoring phase after all excerpts are generated.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import run
from benchmark.evidence_window_ablation import (
    acquire_prefetch_variants, _span_ids_from_refs,
)
from codebase import Repo
from context_budget_selector import select_evidence

_MODES = ('baseline', 'fixed_1', 'fixed_2',
          'adaptive_0', 'adaptive_1', 'adaptive_2')


def _validate_display(excerpts):
    """Check that every ref corresponds to its exact displayed line text."""
    for part in excerpts:
        path = part.get('path')
        if not isinstance(path, str) or not path:
            raise ValueError('Invalid source path')
        content = part.get('content')
        if not isinstance(content, str):
            raise ValueError('Invalid excerpt content')
        lines = []
        for text in content.splitlines():
            prefix, sep, _ = text.partition('|')
            if not sep or not prefix.strip().isdecimal():
                raise ValueError('Evidence excerpt contains unnumbered content')
            lines.append(f'{path}:{int(prefix.strip())}')
        if not lines or part.get('visible_refs') != lines or part.get('source_refs') != lines:
            raise ValueError('Citable refs differ from displayed source line IDs')


def _evaluate_case(repo, saved_case, gold_case, *, max_chars=3000,
                   fixed_window_chars=500, limit=6):
    if (saved_case['id'] != gold_case['id'] or
            saved_case['question'] != gold_case['question']):
        raise ValueError('Pinned benchmark metadata mismatch')
    source_variants = acquire_prefetch_variants(
        repo, saved_case, max_chars=max_chars,
        per_window_chars=fixed_window_chars, limit=limit)
    output = {
        'baseline': source_variants['0'],
        'fixed_1': source_variants['1'],
        'fixed_2': source_variants['2'],
    }
    for n in (0, 1, 2):
        output[f'adaptive_{n}'] = select_evidence(
            repo, saved_case, max_chars=max_chars,
            max_alternates=n, limit=limit)

    # Source selection has finished for EVERY mode before accessing gold spans.
    spans = gold_case.get('gold_spans') or []
    assessed = {}
    for mode in _MODES:
        selection = output[mode]
        excerpts = selection['excerpts']
        _validate_display(excerpts)
        actual_chars = len(json.dumps(excerpts, ensure_ascii=False))
        if actual_chars > max_chars or actual_chars != selection['serialized_chars']:
            raise ValueError('Evidence JSON budget or accounting mismatch')
        visible = _span_ids_from_refs(spans, excerpts, 'visible_refs')
        citable = _span_ids_from_refs(spans, excerpts, 'source_refs')
        if not set(citable).issubset(visible):
            raise ValueError('Citable gold span is absent from displayed source')
        assessed[mode] = {
            'gold_visible_ids': visible,
            'gold_citable_ids': citable,
            'gold_spans_visible': len(visible),
            'gold_spans_citable': len(citable),
            'serialized_chars': actual_chars,
            'unused_chars': max_chars - actual_chars,
            'excerpt_count': len(excerpts),
            'displayed_source_lines': sum(len(x['visible_refs']) for x in excerpts),
            'citable_source_lines': sum(len(x['source_refs']) for x in excerpts),
            'selected_dense_alternates': (
                selection.get('selected_dense_alternates')
                if mode.startswith('adaptive') else
                selection.get('alternate_windows_emitted', 0)),
        }
    return {
        'id': saved_case['id'],
        'gold_span_count': len(spans),
        'modes': assessed,
    }


def analyze(saved, cases, repo, *, max_chars=3000,
            fixed_window_chars=500, limit=6):
    if not isinstance(saved.get('cases'), list) or not saved['cases']:
        raise ValueError('Saved multiwindow cases missing')
    expected = {row['id']: row for row in cases if row['suite'] == saved['suite']}
    records = []
    seen = set()
    for saved_case in saved['cases']:
        case_id = saved_case['id']
        if case_id in seen or case_id not in expected:
            raise ValueError('Duplicate or unknown saved case')
        seen.add(case_id)
        records.append(_evaluate_case(
            repo, saved_case, expected[case_id], max_chars=max_chars,
            fixed_window_chars=fixed_window_chars, limit=limit))
    for case in records:
        baseline_refs = set(case['modes']['baseline']['gold_citable_ids'])
        case['compared_to_baseline'] = {
            mode: {
                'new_gold_span_ids': sorted(
                    set(case['modes'][mode]['gold_citable_ids']) - baseline_refs),
                'lost_gold_span_ids': sorted(
                    baseline_refs - set(case['modes'][mode]['gold_citable_ids'])),
            }
            for mode in _MODES if mode != 'baseline'
        }
    total = sum(item['gold_span_count'] for item in records)
    aggregated = {}
    for mode in _MODES:
        rows = [case['modes'][mode] for case in records]
        gains = 0
        losses = 0
        gained_cases = 0
        lost_cases = 0
        for case, row in zip(records, rows):
            baseline = set(case['modes']['baseline']['gold_citable_ids'])
            current = set(row['gold_citable_ids'])
            gained = len(current - baseline)
            lost = len(baseline - current)
            gains += gained
            losses += lost
            gained_cases += bool(gained)
            lost_cases += bool(lost)
        hits = sum(row['gold_spans_citable'] for row in rows)
        aggregated[mode] = {
            'gold_spans_visible': sum(row['gold_spans_visible'] for row in rows),
            'gold_spans_citable': hits,
            'citable_span_coverage': round(hits / total, 4) if total else None,
            'cases_with_gold_evidence': sum(row['gold_spans_citable'] > 0 for row in rows),
            'gross_gold_span_gains': gains,
            'gross_gold_span_losses': losses,
            'cases_gaining_gold': gained_cases,
            'cases_losing_gold': lost_cases,
            'serialized_chars': sum(row['serialized_chars'] for row in rows),
            'unused_chars': sum(row['unused_chars'] for row in rows),
            'displayed_source_lines': sum(row['displayed_source_lines'] for row in rows),
            'citable_source_lines': sum(row['citable_source_lines'] for row in rows),
            'selected_dense_alternates': sum(row['selected_dense_alternates'] for row in rows),
        }
    baseline_count = aggregated['baseline']['gold_spans_citable']
    for row in aggregated.values():
        row['net_citable_vs_baseline'] = row['gold_spans_citable'] - baseline_count
    return {
        'summary': {
            'case_count': len(records),
            'gold_spans_total': total,
            'max_chars_per_case': max_chars,
            'fixed_window_char_cap': fixed_window_chars,
            'max_excerpts_per_case': limit,
            'modes': aggregated,
        },
        'cases': records,
        'notes': [
            'Extracts are from the pinned source checkout.',
            'Selection uses no benchmark gold labels.',
            'Serialized JSON characters are not model tokens.',
            'Citable means a line occurs in prefetch source_refs, not in a model answer.',
            'The twenty inspected cases are diagnostic, not held-out validation.',
        ],
    }


def verify_previous_ablation(previous, current):
    """Check that historical P1.6 controls reproduce at the same settings."""
    if previous.get('suite') != current.get('suite'):
        raise ValueError('P1.6 reference and P1.7 suite differ')
    reference = {row['id']: row for row in previous.get('cases') or []}
    if len(reference) != len(previous.get('cases') or []):
        raise ValueError('Duplicate case in historical P1.6 report')
    mapping = {'baseline':'0', 'fixed_1':'1', 'fixed_2':'2'}
    verified = 0
    for row in current['cases']:
        previous_case = reference.get(row['id'])
        if previous_case is None:
            raise ValueError('Case absent from historical P1.6 report')
        for current_mode, previous_mode in mapping.items():
            original = previous_case['variants'][previous_mode]
            now = row['modes'][current_mode]
            for field in ('gold_visible_ids', 'gold_citable_ids',
                          'serialized_chars'):
                if now[field] != original[field]:
                    raise ValueError(
                        f'P1.6 control changed: {row["id"]} '
                        f'{current_mode}.{field}')
        verified += 1
    return {'reproduced_p16_cases':verified,
            'control_modes_compared':list(mapping),
            'controls_identical_to_p16':True}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--from-report', type=Path, required=True)
    p.add_argument('--max-chars', type=int, default=3000)
    p.add_argument('--fixed-window-chars', type=int, default=500)
    p.add_argument('--limit', type=int, default=6)
    p.add_argument('--out', type=Path)
    p.add_argument('--p16-report', type=Path,
                   help='Optional report for control reproduction checks')
    args = p.parse_args(argv)
    if not args.from_report.is_file():
        p.error('Saved multiwindow report is missing')
    saved = json.loads(args.from_report.read_text(encoding='utf-8'))
    suite = saved.get('suite')
    if suite not in run.REPOS:
        p.error('Unsupported benchmark suite')
    if ((saved.get('method') or {}).get('frozen_source_commit')
            != run.REPOS[suite][1]):
        p.error('Pinned source revision mismatch')
    if not isinstance((saved.get('summary') or {}).get('multiwindow_diagnostics'), dict):
        p.error('Expected --collect-multiwindow report')
    checkout = run.CACHES / run.REPOS[suite][2]
    if not checkout.is_dir():
        p.error('Pinned checkout directory is missing')
    if run.git('rev-parse', 'HEAD', cwd=checkout) != run.REPOS[suite][1]:
        p.error('Pinned checkout commit differs from dataset')
    output = analyze(
        saved, run.read_cases(), Repo(checkout), max_chars=args.max_chars,
        fixed_window_chars=args.fixed_window_chars, limit=args.limit)
    output['suite'] = suite
    output['from_report'] = str(args.from_report)
    if args.p16_report:
        if not args.p16_report.is_file():
            p.error('Historical P1.6 report is missing')
        previous = json.loads(args.p16_report.read_text(encoding='utf-8'))
        output['summary']['p16_control_verification'] = (
            verify_previous_ablation(previous, output))
    target = (args.out or run.RESULTS / '_diagnostics' /
              'context_budget_p17_ablation.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n',
                      encoding='utf-8')
    print(json.dumps({'summary': output['summary'], 'report': str(target)},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
