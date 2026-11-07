"""P1.14 offline contiguous-source packing diagnostic on a frozen report.

Reruns ONLY the experimental gold-blind source packer. Reuses exact baseline,
adaptive_1 and merge_anchored_1 metrics from an existing P1.11 report, with
SHA, source-commit and case-level control checks. No Ollama or new embeddings.
The Click cases have already been inspected: results are developmental, NOT a
new held-out estimate of generalization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from structure_aware_evidence import pack_contiguous_evidence

MODE = 'structure_contiguous_8_12'
CONTROLS = ('baseline', 'adaptive_1', 'merge_balanced_1', 'merge_anchored_1')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _verified_inputs(labels_path, windows_path, prior_path, repository, commit):
    from benchmark import heldout_evidence_eval as ev

    labels = ev._read_jsonl(labels_path)
    windows = json.loads(Path(windows_path).read_text(encoding='utf-8'))
    prior = json.loads(Path(prior_path).read_text(encoding='utf-8'))
    if (prior.get('repository') != repository or prior.get('source_commit') != commit
            or prior.get('suite') != windows.get('suite')):
        raise ValueError('P1.11 historical report is from another source/suite')
    if (prior.get('input_sha256') or {}).get('cases_jsonl') != _sha(labels_path):
        raise ValueError('Held-out labels were modified after P1.11')
    if (prior.get('input_sha256') or {}).get('source_window_report') != _sha(windows_path):
        raise ValueError('Candidate windows were modified after P1.11')
    frozen = (prior.get('summary') or {}).get('fixed_config') or {}
    if frozen != {'max_chars_per_case': 3000, 'max_excerpts_per_case': 6,
                  'dense_alternates': 1, 'merge_max_block': 1}:
        raise ValueError('Historical P1.11 configuration is not frozen defaults')
    known = ev._read_jsonl(ROOT / 'benchmark' / 'datasets' / 'benchmark_30.jsonl')
    safe, by_id = ev._validate_inputs(labels, windows, known,
                                      repository=repository, commit=commit)
    old = prior.get('cases')
    if not isinstance(old, list) or len(old) != len(safe):
        raise ValueError('P1.11 historical case count mismatch')
    previous = {row['id']: row for row in old}
    if len(previous) != len(old) or set(previous) != {row['id'] for row in safe}:
        raise ValueError('P1.11 historical case IDs mismatch')
    return safe, by_id, prior, previous


def _ids(row, key):
    ids = row.get(key)
    if (not isinstance(ids, list) or any(not isinstance(x, str) for x in ids)
            or len(ids) != len(set(ids))):
        raise ValueError('Invalid historical gold-span IDs: ' + key)
    return set(ids)


def _aggregate(cases, prior):
    if not cases:
        raise ValueError('No evaluated cases')
    summary = (prior.get('summary') or {})
    controls = summary.get('modes') or {}
    if summary.get('case_count') != len(cases):
        raise ValueError('P1.11 summary case count mismatch')
    n_gold = sum(row['gold_span_count'] for row in cases)
    if summary.get('gold_spans_total') != n_gold or n_gold == 0:
        raise ValueError('P1.11 summary gold-span count mismatch')
    measures = {
        'gold_spans_any_line': 0,
        'gold_spans_complete': 0,
        'cases_with_gold': 0,
        'serialized_chars': 0,
        'displayed_source_lines': 0,
        'isolated_source_lines': 0,
        'selected_blocks': 0,
        'candidate_blocks': 0,
        'gross_gains_vs_baseline': 0,
        'gross_losses_vs_baseline': 0,
        'gross_gains_vs_anchored_1': 0,
        'gross_losses_vs_anchored_1': 0,
        'cases_gaining_vs_baseline': 0,
        'cases_losing_vs_baseline': 0,
    }
    control_totals = {name: 0 for name in CONTROLS}
    for row in cases:
        now = row['structure']
        hits = _ids(now, 'gold_any_line_ids')
        full = _ids(now, 'gold_complete_span_ids')
        if not full <= hits:
            raise ValueError('Complete-span hits must be a subset of any-line hits')
        for name in CONTROLS:
            control = row['controls'][name]
            oldhits = _ids(control, 'gold_any_line_ids')
            if not _ids(control, 'gold_complete_span_ids') <= oldhits:
                raise ValueError('Historical complete-span IDs inconsistent')
            control_totals[name] += len(oldhits)
        baseline = _ids(row['controls']['baseline'], 'gold_any_line_ids')
        anchored = _ids(row['controls']['merge_anchored_1'], 'gold_any_line_ids')
        gains, losses = hits - baseline, baseline - hits
        measures['gold_spans_any_line'] += len(hits)
        measures['gold_spans_complete'] += len(full)
        measures['cases_with_gold'] += bool(hits)
        for metric in ('serialized_chars', 'displayed_source_lines',
                       'isolated_source_lines', 'selected_blocks', 'candidate_blocks'):
            measures[metric] += now[metric]
        measures['gross_gains_vs_baseline'] += len(gains)
        measures['gross_losses_vs_baseline'] += len(losses)
        measures['gross_gains_vs_anchored_1'] += len(hits - anchored)
        measures['gross_losses_vs_anchored_1'] += len(anchored - hits)
        measures['cases_gaining_vs_baseline'] += bool(gains)
        measures['cases_losing_vs_baseline'] += bool(losses)
    for name in CONTROLS:
        if (controls.get(name) or {}).get('gold_spans_any_line') != control_totals[name]:
            raise ValueError('P1.11 reported control coverage differs from cases: ' + name)
    measures['coverage_any_line'] = round(measures['gold_spans_any_line'] / n_gold, 4)
    measures['coverage_complete'] = round(measures['gold_spans_complete'] / n_gold, 4)
    return {
        'case_count': len(cases), 'gold_spans_total': n_gold,
        'frozen_config': {'max_chars_per_case': 3000, 'max_excerpts_per_case': 6,
                          'dense_alternates': 1, 'block_lengths': [8, 12]},
        'controls': {name: controls[name] for name in CONTROLS},
        MODE: measures,
        'controls_identical_to_saved_p11': True,
    }


def evaluate(safe, labels_by_id, prior_by_id, repo):
    from benchmark import heldout_evidence_eval as ev

    records = []
    for row in safe:
        packed = pack_contiguous_evidence(repo, row, max_chars=3000, limit=6,
                                          max_alternates=1, block_lengths=(8, 12))
        excerpts = packed['excerpts']
        # Verify exact displayed line references before reading gold labels.
        measured = ev._source_metrics(excerpts)
        if packed['serialized_chars'] != measured['serialized_chars']:
            raise ValueError('Inconsistent evidence size accounting')
        spans = labels_by_id[row['id']]['gold_spans']
        any_hit, full_hit = ev._score(spans, excerpts)
        measured.update({
            'gold_any_line_ids': any_hit,
            'gold_complete_span_ids': full_hit,
            'selected_blocks': packed['selected_blocks'],
            'candidate_blocks': packed['candidate_blocks'],
            'read_candidate_windows': packed['read_candidate_windows'],
            'selected_windows': [{
                'path': e['path'],
                'line_start': int(e['source_refs'][0].rpartition(':')[2]),
                'line_end': int(e['source_refs'][-1].rpartition(':')[2]),
                'source_lines': len(e['source_refs']),
            } for e in excerpts],
        })
        original = prior_by_id[row['id']]
        if original.get('gold_span_count') != len(spans):
            raise ValueError('P1.11 original gold-span count mismatch')
        control_rows = {}
        for name in CONTROLS:
            original_mode = (original.get('modes') or {}).get(name)
            if not isinstance(original_mode, dict):
                raise ValueError('Missing P1.11 historical control: ' + name)
            control_rows[name] = original_mode
        records.append({'id': row['id'], 'gold_span_count': len(spans),
                        'structure': measured, 'controls': control_rows})
    return records


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--labels-jsonl', type=Path, required=True)
    p.add_argument('--from-report', type=Path, required=True)
    p.add_argument('--evaluation', type=Path, required=True)
    p.add_argument('--checkout', type=Path, required=True)
    p.add_argument('--repository', required=True)
    p.add_argument('--commit', required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    for path in (args.labels_jsonl, args.from_report, args.evaluation):
        if not path.is_file():
            p.error('Missing input file: ' + str(path))
    if args.out.exists():
        p.error('Refusing to overwrite existing P1.14 report: ' + str(args.out))
    safe, labels, old, previous = _verified_inputs(
        args.labels_jsonl, args.from_report, args.evaluation,
        args.repository, args.commit)
    from codebase import Repo
    from benchmark.heldout_evidence_eval import _validate_checkout
    root = _validate_checkout(args.checkout, args.repository, args.commit)
    results = evaluate(safe, labels, previous, Repo(root))
    report = {
        'summary': _aggregate(results, old), 'cases': results,
        'repository': args.repository, 'source_commit': args.commit,
        'input_sha256': {
            'labels': _sha(args.labels_jsonl),
            'windows': _sha(args.from_report),
            'p11_evaluation': _sha(args.evaluation),
        },
        'notes': [
            'Previously inspected Click questions are developmental data, not held-out validation.',
            'The new selector never reads gold labels until source excerpts are chosen.',
            'Candidate windows are reused unchanged from the saved P1.12 report.',
            'No additional Qwen embedding or retrieval is performed.',
            'Any-line and complete-span metrics describe evidence, not answer correctness.',
            'No production runtime hooks were changed.',
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                        encoding='utf-8')
    print(json.dumps({'summary': report['summary'], 'report': str(args.out)},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
