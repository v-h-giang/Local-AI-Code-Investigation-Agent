"""P1.9 offline source-evidence merge comparison at fixed character budget.

Generate baseline and adaptive_1 excerpts using existing prefetch functions,
then compare two incremental merge policies. Benchmark spans are scored after
source excerpt sets have been finalized.
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
from benchmark.evidence_window_ablation import acquire_prefetch_variants, _span_ids_from_refs
from codebase import Repo
from context_budget_selector import select_evidence
from incremental_evidence_merge import merge_evidence

_MODES = ('baseline', 'adaptive_1', 'merge_balanced', 'merge_anchored')


def evaluate_case(repo, saved, gold_case, *, max_chars=3000, limit=6,
                  max_block=3):
    if saved['id'] != gold_case['id'] or saved['question'] != gold_case['question']:
        raise ValueError('Saved and pinned case metadata differs')
    baseline = acquire_prefetch_variants(
        repo, saved, max_chars=max_chars, per_window_chars=500, limit=limit)['0']['excerpts']
    adaptive = select_evidence(
        repo, saved, max_chars=max_chars, max_alternates=1, limit=limit)['excerpts']
    balanced = merge_evidence(
        baseline, adaptive, saved['question'], policy='balanced',
        max_chars=max_chars, limit=limit, max_block=max_block)
    anchored = merge_evidence(
        baseline, adaptive, saved['question'], policy='anchored',
        max_chars=max_chars, limit=limit, max_block=max_block)
    outputs = {'baseline':baseline, 'adaptive_1':adaptive,
               'merge_balanced':balanced['excerpts'],
               'merge_anchored':anchored['excerpts']}
    for rows in outputs.values():
        _validate_display(rows)
        if len(rows)>limit or len(json.dumps(rows, ensure_ascii=False)) > max_chars:
            raise ValueError('Source evidence exceeds budget or excerpt count')
    # All source selections were finalized before benchmark-span evaluation.
    spans = gold_case.get('gold_spans') or []
    modes = {}
    for name, rows in outputs.items():
        visible = _span_ids_from_refs(spans, rows, 'visible_refs')
        citable = _span_ids_from_refs(spans, rows, 'source_refs')
        if visible != citable:
            raise ValueError('Source references differ from visible evidence')
        modes[name] = {
            'gold_visible_ids':visible,
            'gold_citable_ids':citable,
            'serialized_chars':len(json.dumps(rows,ensure_ascii=False)),
            'displayed_source_lines':sum(len(row['visible_refs']) for row in rows),
            'excerpt_count':len(rows),
        }
        if name.startswith('merge_'):
            info = balanced if name == 'merge_balanced' else anchored
            modes[name].update({key: info[key] for key in (
                'retained_baseline_source_lines', 'lost_baseline_source_lines',
                'added_adaptive_source_lines','selected_blocks')})
    upper_ids = sorted(set(modes['baseline']['gold_citable_ids']) |
                       set(modes['adaptive_1']['gold_citable_ids']))
    return {'id':saved['id'],'gold_spans':len(spans),
            'gold_union_ceiling_ids':upper_ids,'modes':modes}


def analyze(saved, cases, repo, *, max_chars=3000, limit=6, max_block=3):
    if not isinstance(saved.get('cases'), list) or not saved['cases']:
        raise ValueError('Missing source-window cases')
    sources = {c['id']:c for c in cases if c['suite']==saved['suite']}
    seen = set()
    records = []
    for item in saved['cases']:
        case_id = item['id']
        if case_id in seen or case_id not in sources:
            raise ValueError('Duplicate or unrecognized case')
        seen.add(case_id)
        records.append(evaluate_case(repo,item,sources[case_id],
            max_chars=max_chars,limit=limit,max_block=max_block))
    gold_count = sum(row['gold_spans'] for row in records)
    metrics = {}
    for name in _MODES:
        rows = [r['modes'][name] for r in records]
        gains, losses = [], []
        adaptive_gains, adaptive_losses = [], []
        for record, current in zip(records, rows):
            current_ids = set(current['gold_citable_ids'])
            baseline_ids = set(record['modes']['baseline']['gold_citable_ids'])
            adaptive_ids = set(record['modes']['adaptive_1']['gold_citable_ids'])
            gains.append(current_ids - baseline_ids)
            losses.append(baseline_ids - current_ids)
            adaptive_gains.append(current_ids - adaptive_ids)
            adaptive_losses.append(adaptive_ids - current_ids)
        hits = sum(len(row['gold_citable_ids']) for row in rows)
        metrics[name] = {
            'gold_spans_citable':hits,
            'coverage':round(hits/gold_count,4) if gold_count else None,
            'gross_gains_vs_baseline':sum(len(x) for x in gains),
            'gross_losses_vs_baseline':sum(len(x) for x in losses),
            'cases_gaining_vs_baseline':sum(bool(x) for x in gains),
            'cases_losing_vs_baseline':sum(bool(x) for x in losses),
            'gross_gains_vs_adaptive_1':sum(len(x) for x in adaptive_gains),
            'gross_losses_vs_adaptive_1':sum(len(x) for x in adaptive_losses),
            'cases_with_citable_gold':sum(bool(row['gold_citable_ids']) for row in rows),
            'serialized_chars':sum(row['serialized_chars'] for row in rows),
            'displayed_source_lines':sum(row['displayed_source_lines'] for row in rows),
        }
        if name.startswith('merge_'):
            metrics[name].update({key:sum(row[key] for row in rows) for key in (
                'retained_baseline_source_lines','lost_baseline_source_lines',
                'added_adaptive_source_lines','selected_blocks')})
    for case in records:
        baseline=set(case['modes']['baseline']['gold_citable_ids'])
        adaptive=set(case['modes']['adaptive_1']['gold_citable_ids'])
        case['changes']={mode:{
            'gained_vs_baseline':sorted(set(case['modes'][mode]['gold_citable_ids'])-baseline),
            'lost_vs_baseline':sorted(baseline-set(case['modes'][mode]['gold_citable_ids'])),
            'gained_vs_adaptive':sorted(set(case['modes'][mode]['gold_citable_ids'])-adaptive),
            'lost_vs_adaptive':sorted(adaptive-set(case['modes'][mode]['gold_citable_ids'])),
        } for mode in ('merge_balanced','merge_anchored')}
    return {
        'summary':{
            'case_count':len(records),
            'gold_spans_total':gold_count,
            'max_chars_per_case':max_chars,
            'max_excerpts_per_case':limit,
            'max_contiguous_source_lines_per_block':max_block,
            'unbudgeted_union_ceiling':sum(len(r['gold_union_ceiling_ids']) for r in records),
            'modes':metrics,
        },
        'cases':records,
        'limitations':[
            'Line-level merge depends on prefetch excerpts already extracted from pinned source.',
            'Source lines retain original numbered text, paths and references.',
            'Gold-span overlap is evaluated only after all candidate outputs are fixed.',
            'Unbudgeted union ceiling is a diagnostic, not an attainable guarantee.',
            'Character budget is serialized JSON, not model tokens.',
            'Evidence inclusion does not imply accurate agent final answers.',
            'Previously inspected cases are not held-out validation.',
        ],
    }


def verify_p18_control(previous, current):
    if previous.get('suite') != current.get('suite'):
        raise ValueError('Historical suite mismatch')
    prior = previous.get('cases') or []
    by_id = {r['id']:r for r in prior}
    if len(by_id) != len(prior) or len(prior) != len(current['cases']):
        raise ValueError('Mismatch or duplicate cases')
    for row in current['cases']:
        old = by_id.get(row['id'])
        if old is None:
            raise ValueError('Reference case absent')
        for mode in ('baseline','adaptive_1'):
            for key in ('gold_citable_ids','serialized_chars','displayed_source_lines'):
                if old['modes'][mode][key] != row['modes'][mode][key]:
                    raise ValueError('Historical control differs: '+row['id']+':'+mode+':'+key)
    return {'controls_identical_to_p18':True,'reproduced_cases':len(current['cases'])}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--from-report',type=Path,required=True)
    p.add_argument('--p18-report',type=Path,required=True)
    p.add_argument('--max-chars',type=int,default=3000)
    p.add_argument('--limit',type=int,default=6)
    p.add_argument('--max-block',type=int,default=3)
    p.add_argument('--out',type=Path)
    args = p.parse_args(argv)
    for fp in (args.from_report,args.p18_report):
        if not fp.is_file():
            p.error('Missing input report: '+str(fp))
    report = json.loads(args.from_report.read_text(encoding='utf-8'))
    suite = report.get('suite')
    if suite not in run.REPOS:
        p.error('Unsupported suite')
    if (report.get('method') or {}).get('frozen_source_commit') != run.REPOS[suite][1]:
        p.error('Pinned dataset source mismatch')
    checkout = run.CACHES / run.REPOS[suite][2]
    if not checkout.is_dir() or run.git('rev-parse','HEAD',cwd=checkout) != run.REPOS[suite][1]:
        p.error('Pinned checkout unavailable or modified')
    output = analyze(report,run.read_cases(),Repo(checkout),
                     max_chars=args.max_chars,limit=args.limit,max_block=args.max_block)
    output['suite']=suite
    output['from_report']=str(args.from_report)
    old = json.loads(args.p18_report.read_text(encoding='utf-8'))
    output['summary']['p18_control_verification']=verify_p18_control(old,output)
    result_path = args.out or (run.RESULTS / '_diagnostics' / 'p19_incremental_merge_ablation.json')
    result_path.parent.mkdir(parents=True,exist_ok=True)
    result_path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'summary':output['summary'],'report':str(result_path)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
