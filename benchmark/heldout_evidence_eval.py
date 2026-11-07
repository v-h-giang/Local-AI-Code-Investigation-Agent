"""Offline, provenance-checked evaluation on previously unseen labeled cases.

Evaluation inputs are a separate source-window report, a separate labeled JSONL,
and a pinned source checkout. Source selection receives only candidate coordinates
and question text; labels are used afterwards for scoring. No runtime hook changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codebase import Repo
from benchmark.context_budget_ablation import _validate_display
from benchmark.evidence_window_ablation import acquire_prefetch_variants
from context_budget_selector import select_evidence
from incremental_evidence_merge import merge_evidence

BUDGET = 3000
EXCERPT_LIMIT = 6
BLOCK_SIZE = 1
DENSE_ALTERNATES = 1
MODES = ('baseline', 'adaptive_1', 'merge_balanced_1', 'merge_anchored_1')
_COMMIT = re.compile(r'^[0-9a-f]{40}$')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _path(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Expected forward-slash relative source path')
    obj = PurePosixPath(value)
    if (obj.is_absolute() or obj.as_posix() != value
            or any(p in ('.', '..') for p in value.split('/'))):
        raise ValueError('Noncanonical source path: ' + repr(value))
    return value


def _question(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Missing question')
    return ' '.join(value.split()).casefold()


def _read_jsonl(path):
    items = []
    for index, raw in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if raw.strip():
            item = json.loads(raw)
            if not isinstance(item, dict):
                raise ValueError(f'Case at line {index} is not an object')
            items.append(item)
    return items


def _validate_inputs(labels, saved, historical, *, repository, commit):
    """Check independent identities and coordinates before source selection."""
    if not labels:
        raise ValueError('Holdout JSONL contains no labeled cases')
    if not _COMMIT.fullmatch(commit):
        raise ValueError('Commit must be a full 40-character SHA')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Expected repository owner/name')
    suite = labels[0].get('suite')
    if not isinstance(suite, str) or not suite or suite != saved.get('suite'):
        raise ValueError('Candidate report suite differs from labels')
    if (saved.get('method') or {}).get('frozen_source_commit') != commit:
        raise ValueError('Candidate report is not pinned to the requested SHA')
    if saved.get('repo') is not None and saved['repo'] != repository:
        raise ValueError('Candidate report repository differs from expected')
    old_ids, old_questions = set(), set()
    for row in historical:
        if isinstance(row.get('id'), str):
            old_ids.add(row['id'])
        if row.get('repo') and row.get('question'):
            old_questions.add((row['repo'].casefold(), _question(row['question'])))
    ids, questions = set(), set()
    by_id = {}
    for row in labels:
        case_id = row.get('id')
        if not isinstance(case_id, str) or not case_id:
            raise ValueError('Missing holdout case ID')
        question = _question(row.get('question'))
        pair = (repository.casefold(), question)
        if case_id in ids or pair in questions:
            raise ValueError('Duplicate holdout case ID or question')
        if case_id in old_ids or pair in old_questions:
            raise ValueError('Holdout overlaps existing benchmark cases')
        if (row.get('repo'), row.get('commit'), row.get('suite')) != (repository, commit, suite):
            raise ValueError('Holdout case repository, commit or suite mismatch')
        spans = row.get('gold_spans')
        if not isinstance(spans, list) or not spans:
            raise ValueError(f'Missing gold spans for held-out case {case_id}')
        span_ids = set()
        for span in spans:
            if not isinstance(span, dict) or not isinstance(span.get('id'), str) or not span['id']:
                raise ValueError('Invalid gold span ID')
            if span['id'] in span_ids:
                raise ValueError('Duplicate gold span ID')
            span_ids.add(span['id'])
            _path(span.get('path'))
            lo, hi = span.get('start_line'), span.get('end_line')
            if type(lo) is not int or type(hi) is not int or lo < 1 or hi < lo:
                raise ValueError('Invalid gold span coordinates')
        ids.add(case_id)
        questions.add(pair)
        by_id[case_id] = row
    entries = saved.get('cases')
    if not isinstance(entries, list) or len(entries) != len(labels):
        raise ValueError('Candidate report must contain exactly the held-out cases')
    seen = set()
    safe = []
    for item in entries:
        case_id = item.get('id')
        if case_id not in by_id or case_id in seen:
            raise ValueError('Unknown or duplicate candidate-report case')
        seen.add(case_id)
        if item.get('question') != by_id[case_id]['question']:
            raise ValueError('Candidate question differs from holdout case')
        head = (((item.get('variants') or {}).get('hybrid') or {}).get('top8_diagnostics'))
        alt = ((item.get('multiwindow_diagnostics') or {}).get('alternates'))
        if not isinstance(head, list) or not 1 <= len(head) <= 8:
            raise ValueError('Expected 1-8 Hybrid candidate windows')
        if not isinstance(alt, list) or len(alt) > 4:
            raise ValueError('Expected 0-4 Dense alternate windows')
        # Construct a minimal candidate-only record. Ignore gold and retrieval
        # scores/diagnostics that may be present in saved source reports.
        def project(row, dense=False):
            if not isinstance(row, dict):
                raise ValueError('Invalid source candidate')
            path = _path(row.get('path'))
            lo = row.get('start_line') if dense else row.get('line_start')
            hi = row.get('end_line') if dense else row.get('line_end')
            if type(lo) is not int or type(hi) is not int or lo < 1 or hi < lo:
                raise ValueError('Invalid candidate coordinates')
            if dense:
                novel = row.get('new_lines')
                if type(novel) is not int or novel < 8:
                    raise ValueError('Invalid Dense novelty metadata')
                return {'path': path, 'start_line': lo, 'end_line': hi,
                        'new_lines': novel}
            return {'path': path, 'line_start': lo, 'line_end': hi}
        safe.append({'id': case_id, 'question': item['question'],
                     'variants': {'hybrid': {'top8_diagnostics':
                                            [project(r) for r in head]}},
                     'multiwindow_diagnostics': {
                         'alternates': [project(r, dense=True) for r in alt]}})
    return safe, by_id


def _git(checkout, *args):
    result = subprocess.run(['git', '-C', str(checkout), *args],
                            capture_output=True, text=True, check=False,
                            encoding='utf-8', errors='replace', timeout=30)
    if result.returncode:
        raise ValueError('Unable to validate frozen checkout: git ' + ' '.join(args))
    return result.stdout.strip()


def _validate_checkout(checkout, repository, commit):
    checkout = Path(checkout).resolve()
    if not checkout.is_dir():
        raise ValueError('Checkout does not exist')
    if Path(_git(checkout, 'rev-parse', '--show-toplevel')).resolve() != checkout:
        raise ValueError('Checkout must be the repository root')
    if _git(checkout, 'rev-parse', 'HEAD') != commit:
        raise ValueError('Checkout HEAD differs from pinned source commit')
    if _git(checkout, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Tracked files in the pinned checkout are modified')
    remote = _git(checkout, 'remote', 'get-url', 'origin')
    # Permit standard GitHub HTTPS and SSH formats, avoiding credentials in output.
    match = re.match(r'^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^?#]+)$', remote)
    if not match or match.group(1).removesuffix('.git').casefold() != repository.casefold():
        raise ValueError('Checkout origin does not identify the requested GitHub repository')
    return checkout


def _source_metrics(excerpts):
    _validate_display(excerpts)
    size = len(json.dumps(excerpts, ensure_ascii=False))
    if size > BUDGET or len(excerpts) > EXCERPT_LIMIT:
        raise ValueError('Evidence exceeds frozen character/excerpt budgets')
    lines_by_path = {}
    for snippet in excerpts:
        path = snippet['path']
        lines = lines_by_path.setdefault(path, set())
        for ref in snippet['source_refs']:
            ref_path, _, number = ref.rpartition(':')
            if ref_path != path or not number.isdecimal():
                raise ValueError('Invalid displayed source reference')
            lines.add(int(number))
    unique_count = sum(len(v) for v in lines_by_path.values())
    isolated = sum(1 for lines in lines_by_path.values() for n in lines
                   if n-1 not in lines and n+1 not in lines)
    return {
        'serialized_chars': size,
        'displayed_source_lines': unique_count,
        'isolated_source_lines': isolated,
        'isolation_fraction': round(isolated / unique_count, 4) if unique_count else None,
        'source_file_count': len(lines_by_path),
        'excerpt_count': len(excerpts),
    }


def _score(spans, excerpts):
    refs = {ref for excerpt in excerpts for ref in excerpt['source_refs']}
    any_hit, full_hit = [], []
    for span in spans:
        covered = [f"{span['path']}:{n}" in refs
                   for n in range(span['start_line'], span['end_line']+1)]
        if any(covered):
            any_hit.append(span['id'])
        if all(covered):
            full_hit.append(span['id'])
    return sorted(any_hit), sorted(full_hit)


def evaluate(repo, safe, labels):
    """Score frozen selectors against held-out labels only after selection."""
    records = []
    for item in safe:
        baseline = acquire_prefetch_variants(
            repo, item, max_chars=BUDGET, per_window_chars=500,
            limit=EXCERPT_LIMIT)['0']['excerpts']
        adaptive = select_evidence(
            repo, item, max_chars=BUDGET,
            max_alternates=DENSE_ALTERNATES, limit=EXCERPT_LIMIT)['excerpts']
        balanced = merge_evidence(
            baseline, adaptive, item['question'], policy='balanced',
            max_chars=BUDGET, limit=EXCERPT_LIMIT, max_block=BLOCK_SIZE)['excerpts']
        anchored = merge_evidence(
            baseline, adaptive, item['question'], policy='anchored',
            max_chars=BUDGET, limit=EXCERPT_LIMIT, max_block=BLOCK_SIZE)['excerpts']
        selected = dict(zip(MODES, (baseline, adaptive, balanced, anchored)))
        measured = {mode: _source_metrics(excerpts) for mode, excerpts in selected.items()}
        # Gold labels are first read here, after each mode is finalized.
        gold = labels[item['id']]['gold_spans']
        for mode in MODES:
            any_hit, full_hit = _score(gold, selected[mode])
            measured[mode]['gold_any_line_ids'] = any_hit
            measured[mode]['gold_complete_span_ids'] = full_hit
        records.append({'id': item['id'], 'gold_span_count': len(gold), 'modes': measured})
    return records


def summarize(records):
    n_gold = sum(row['gold_span_count'] for row in records)
    modes = {}
    for name in MODES:
        rows = [c['modes'][name] for c in records]
        baseline = [set(c['modes']['baseline']['gold_any_line_ids']) for c in records]
        adaptive = [set(c['modes']['adaptive_1']['gold_any_line_ids']) for c in records]
        current = [set(row['gold_any_line_ids']) for row in rows]
        gains = [new-old for new, old in zip(current, baseline)]
        losses = [old-new for new, old in zip(current, baseline)]
        modes[name] = {
            'gold_spans_any_line': sum(map(len, current)),
            'gold_spans_complete': sum(len(r['gold_complete_span_ids']) for r in rows),
            'coverage_any_line': round(sum(map(len, current))/n_gold, 4),
            'gross_gains_vs_baseline': sum(map(len, gains)),
            'gross_losses_vs_baseline': sum(map(len, losses)),
            'gross_losses_vs_adaptive_1': sum(len(old-new) for old, new in zip(adaptive, current)),
            'cases_with_gold': sum(bool(ids) for ids in current),
            'serialized_chars': sum(row['serialized_chars'] for row in rows),
            'displayed_source_lines': sum(row['displayed_source_lines'] for row in rows),
            'isolated_source_lines': sum(row['isolated_source_lines'] for row in rows),
        }
    return {'case_count': len(records), 'gold_spans_total': n_gold,
            'fixed_config': {'max_chars_per_case': BUDGET,
                             'max_excerpts_per_case': EXCERPT_LIMIT,
                             'dense_alternates': DENSE_ALTERNATES,
                             'merge_max_block': BLOCK_SIZE}, 'modes': modes}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases-jsonl', type=Path, required=True)
    p.add_argument('--from-report', type=Path, required=True)
    p.add_argument('--checkout', type=Path, required=True)
    p.add_argument('--repository', required=True, help='Expected GitHub owner/name')
    p.add_argument('--commit', required=True, help='Pinned 40-hex source SHA')
    p.add_argument('--additional-known-cases', type=Path, action='append', default=[],
                   help='Extra previously inspected cases to exclude (JSONL); the built-in 30 cases are always excluded')
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    built_in_known = ROOT/'benchmark'/'datasets'/'benchmark_30.jsonl'
    for path in (args.cases_jsonl, args.from_report, built_in_known,
                 *args.additional_known_cases):
        if not path.is_file():
            p.error('Missing input file: ' + str(path))
    labels = _read_jsonl(args.cases_jsonl)
    saved = json.loads(args.from_report.read_text(encoding='utf-8'))
    known = _read_jsonl(built_in_known)
    for additional in args.additional_known_cases:
        known.extend(_read_jsonl(additional))
    safe, by_id = _validate_inputs(labels, saved, known,
                                   repository=args.repository, commit=args.commit)
    checkout = _validate_checkout(args.checkout, args.repository, args.commit)
    if args.out.exists():
        p.error('Refusing to overwrite an existing holdout result: ' + str(args.out))
    results = evaluate(Repo(checkout), safe, by_id)
    report = {
        'summary': summarize(results), 'suite': saved['suite'],
        'repository': args.repository, 'source_commit': args.commit,
        'input_sha256': {key: _sha(path) for key, path in (
            ('cases_jsonl', args.cases_jsonl),
            ('source_window_report', args.from_report),
            ('known_cases_jsonl', built_in_known))},
        'extra_known_sha256': [_sha(path) for path in args.additional_known_cases],
        'cases': results,
        'notes': [
            'Known case IDs and exactly matching questions are excluded.',
            'Overlap checks cannot prove semantic independence or absence of contamination.',
            'Gold labels are evaluated after selecting source excerpts.',
            'Any-line coverage is not final-answer correctness.',
            'Complete-span coverage is stricter than any-line coverage.',
            'Isolation fraction is a structural proxy, not semantic validation.',
            'Serialized JSON characters are not model tokens.',
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n',
                        encoding='utf-8')
    print(json.dumps({'summary':report['summary'], 'report': str(args.out)},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
