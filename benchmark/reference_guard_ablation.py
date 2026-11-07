"""P1.8 offline source-backed A/B of two baseline-reference guards.

Reads the frozen checkout and the saved candidate-window report. The guard
compares source excerpt references and query terms; benchmark gold spans
are consulted only after all candidate excerpt sets have been selected.
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
from benchmark.context_budget_ablation import _validate_display
from benchmark.evidence_window_ablation import (
    acquire_prefetch_variants, _span_ids_from_refs,
)
from codebase import Repo
from context_budget_selector import select_evidence
from reference_guard import choose_guarded

MODES = ('baseline', 'adaptive_1', 'guard_critical', 'guard_query')


def evaluate_case(repo, saved, source, *, max_chars=3000, limit=6):
    if saved['id'] != source['id'] or saved['question'] != source['question']:
        raise ValueError('Case metadata does not match')
    prior = acquire_prefetch_variants(repo, saved, max_chars=max_chars,
                                    per_window_chars=500, limit=limit)
    baseline = prior['0']['excerpts']
    adaptive = select_evidence(repo, saved, max_chars=max_chars,
                               max_alternates=1, limit=limit)['excerpts']
    guarded_critical = choose_guarded(
        baseline, adaptive, saved['question'], policy='critical',
        max_chars=max_chars)
    guarded_query = choose_guarded(
        baseline, adaptive, saved['question'], policy='query',
        max_chars=max_chars)
    selected = {
        'baseline': (baseline, 'baseline', None),
        'adaptive_1': (adaptive, 'adaptive_1', None),
        'guard_critical': (guarded_critical['excerpts'],
                           guarded_critical['choice'], guarded_critical),
        'guard_query': (guarded_query['excerpts'],
                        guarded_query['choice'], guarded_query),
    }
    for excerpts, _, _ in selected.values():
        _validate_display(excerpts)
        if len(json.dumps(excerpts, ensure_ascii=False)) > max_chars:
            raise ValueError('Evidence output exceeds shared budget')
    # Source-backed selections and guard decisions have been finalized.
    gold = source.get('gold_spans') or []
    modes = {}
    for name, (excerpts, origin, meta) in selected.items():
        ids = _span_ids_from_refs(gold, excerpts, 'source_refs')
        visible = _span_ids_from_refs(gold, excerpts, 'visible_refs')
        if set(ids) != set(visible):
            raise ValueError('Citable gold span not visible')
        modes[name] = {
            'gold_citable_ids': ids,
            'gold_visible_ids': visible,
            'serialized_chars': len(json.dumps(excerpts,ensure_ascii=False)),
            'displayed_source_lines': sum(len(x['visible_refs']) for x in excerpts),
            'choice': origin,
            'critical_refs_missing': (meta or {}).get(
                'critical_baseline_refs_missing_from_adaptive', 0),
            'baseline_ref_retained': (meta or {}).get(
                'retained_baseline_ref_count'),
            'baseline_ref_count': (meta or {}).get('baseline_ref_count'),
        }
    return {'id': source['id'], 'gold_spans': len(gold), 'modes': modes}


def analyze(saved, cases, repo, *, max_chars=3000, limit=6):
    if not isinstance(saved.get('cases'), list) or not saved['cases']:
        raise ValueError('Missing saved cases')
    sources = {row['id']:row for row in cases if row['suite'] == saved['suite']}
    observed = set()
    output = []
    for item in saved['cases']:
        if item['id'] in observed or item['id'] not in sources:
            raise ValueError('Duplicate or unknown case ID')
        observed.add(item['id'])
        output.append(evaluate_case(repo,item,sources[item['id']],
                                    max_chars=max_chars,limit=limit))
    n_gold = sum(x['gold_spans'] for x in output)
    stats = {}
    for mode in MODES:
        old = [set(c['modes']['baseline']['gold_citable_ids']) for c in output]
        current = [set(c['modes'][mode]['gold_citable_ids']) for c in output]
        gain = [b-a for a,b in zip(old,current)]
        loss = [a-b for a,b in zip(old,current)]
        m = [c['modes'][mode] for c in output]
        stats[mode] = {
            'gold_spans_citable': sum(len(v) for v in current),
            'coverage': round(sum(len(v) for v in current)/n_gold,4)
                        if n_gold else None,
            'gross_gains_vs_baseline': sum(map(len,gain)),
            'gross_losses_vs_baseline': sum(map(len,loss)),
            'cases_gaining_gold': sum(bool(v) for v in gain),
            'cases_losing_gold': sum(bool(v) for v in loss),
            'cases_with_citable_gold': sum(bool(v) for v in current),
            'serialized_chars': sum(x['serialized_chars'] for x in m),
            'displayed_source_lines': sum(x['displayed_source_lines'] for x in m),
            'baseline_fallback_cases': sum(x['choice']=='baseline' for x in m)
                                      if mode.startswith('guard_') else None,
        }
    return {'summary':{'case_count':len(output),
                       'gold_spans_total':n_gold,
                       'max_chars_per_case':max_chars,
                       'modes':stats},
            'cases':output,
            'limitations':[
                'Guard policies use source reference and query term signals.',
                'Gold labels are consulted after excerpt selection.',
                'This is prefetch source overlap, not agent final-answer accuracy.',
                'This inspected dataset is exploratory and not held-out.',
            ]}


def verify_p17(previous, current):
    if previous.get('suite') != current.get('suite'):
        raise ValueError('P1.7 suite mismatch')
    originals = {c['id']:c for c in previous.get('cases') or []}
    if len(originals) != len(previous.get('cases') or []):
        raise ValueError('Duplicate P1.7 case')
    for row in current['cases']:
        other = originals.get(row['id'])
        if other is None:
            raise ValueError('P1.7 case missing')
        for mode in ('baseline', 'adaptive_1'):
            for field in ('gold_citable_ids', 'serialized_chars'):
                if row['modes'][mode][field] != other['modes'][mode][field]:
                    raise ValueError(f'P1.7 control differs for {row["id"]}:{mode}.{field}')
    return {'controls_identical_to_p17': True,
            'reproduced_cases': len(current['cases'])}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--from-report',type=Path,required=True)
    p.add_argument('--p17-report',type=Path,required=True)
    p.add_argument('--max-chars',type=int,default=3000)
    p.add_argument('--limit',type=int,default=6)
    p.add_argument('--out',type=Path)
    args = p.parse_args(argv)
    for path in (args.from_report,args.p17_report):
        if not path.is_file():
            p.error('Required report missing: '+str(path))
    saved = json.loads(args.from_report.read_text(encoding='utf-8'))
    suite = saved.get('suite')
    if suite not in run.REPOS:
        p.error('Unknown benchmark suite')
    if ((saved.get('method') or {}).get('frozen_source_commit')
            != run.REPOS[suite][1]):
        p.error('Frozen source commit mismatch')
    checkout = run.CACHES / run.REPOS[suite][2]
    if not checkout.is_dir() or run.git('rev-parse','HEAD',cwd=checkout) != run.REPOS[suite][1]:
        p.error('Pinned checkout missing or not at frozen revision')
    report = analyze(saved,run.read_cases(),Repo(checkout),
                     max_chars=args.max_chars,limit=args.limit)
    report['suite'] = suite
    reference = json.loads(args.p17_report.read_text(encoding='utf-8'))
    report['summary']['p17_control_verification'] = verify_p17(reference,report)
    out = args.out or (run.RESULTS/'_diagnostics'/'p18_reference_guard_ablation.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'summary':report['summary'],'report':str(out)},
                     ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
