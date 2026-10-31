"""Inspect V5 filename candidate ranking using an existing benchmark SQLite index.

Offline; no Ollama, no source writes, no benchmark gold data in the ranker.
Gold labels here are used solely to calculate diagnostics after retrieval.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from benchmark import run
from codebase import Repo
from code_intelligence import search_file_candidates



def summarize_candidate_results(results):
    """Compute micro/macro candidate recall, with unscorable cases excluded."""
    scorable=[case for case in results if case['gold_files']>0]
    total_gold=sum(case['gold_files'] for case in scorable)
    summary={
        'cases':len(results),
        'scorable_cases':len(scorable),
        'gold_files':total_gold,
    }
    for k in (8,20):
        hits=sum(case[f'candidate_gold_hits_at_{k}'] for case in scorable)
        summary[f'gold_hits_at_{k}']=hits
        summary[f'micro_recall_at_{k}']=round(hits/total_gold,4) if total_gold else None
        summary[f'macro_recall_at_{k}']=round(
            sum(case[f'candidate_recall_at_{k}'] for case in scorable)/len(scorable),4
        ) if scorable else None
        summary[f'zero_hit_case_ids_at_{k}']=[
            case['id'] for case in scorable if case[f'candidate_gold_hits_at_{k}']==0
        ]
    return summary




def evaluate_case(repo, case, *, strategy='v59', limit=20):
    ranked=search_file_candidates(
        repo,case['question'],limit=max(20,limit),strategy=strategy)
    gold={span['path'] for span in case['gold_spans']}
    result={'id':case['id'],'gold_files':len(gold)}
    for k in (8,20):
        paths={item['path'] for item in ranked[:k]}
        hits=sorted(paths & gold)
        result[f'candidate_gold_hits_at_{k}']=len(hits)
        result[f'candidate_recall_at_{k}']=round(len(hits)/len(gold),4) if gold else None
    result['top_candidates']=[{'path':r['path'],'score':r['path_score'],
                               'content_terms':r.get('content_terms',[]),
                               'kb_fts_terms':r.get('kb_fts_terms',[]),
                               'kb_symbol_terms':r.get('kb_symbol_terms',[]),
                               'graph_neighbors':r.get('graph_neighbors',[])}
                              for r in ranked[:max(1,min(20,limit))]]
    return result


def compare_candidate_results(baseline, modified):
    """Paired A/B analysis on the SAME case IDs and frozen source index."""
    left={x['id']:x for x in baseline}
    right={x['id']:x for x in modified}
    if set(left)!=set(right):
        raise ValueError("A/B must use the same set of cases")
    for cid in left:
        if left[cid]['gold_files']!=right[cid]['gold_files']:
            raise ValueError("A/B gold-file count differs for "+cid)
    a=summarize_candidate_results(baseline)
    b=summarize_candidate_results(modified)
    deltas={f'micro_recall_at_{k}':round(
        b[f'micro_recall_at_{k}']-a[f'micro_recall_at_{k}'],4)
        if b[f'micro_recall_at_{k}'] is not None
        and a[f'micro_recall_at_{k}'] is not None else None
        for k in (8,20)}
    changes={}
    for k in (8,20):
        gained=[];lost=[]
        for cid in sorted(left):
            before=left[cid][f'candidate_gold_hits_at_{k}']
            after=right[cid][f'candidate_gold_hits_at_{k}']
            if after>before:gained.append({'id':cid,'before':before,'after':after})
            if after<before:lost.append({'id':cid,'before':before,'after':after})
        changes[f'at_{k}']={'improved_cases':gained,'regressed_cases':lost}
    return {'baseline':a,'v59':b,'delta':deltas,'case_changes':changes}



def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-run',required=True,
                        help='Existing benchmark run with prepared SQLite index')
    parser.add_argument('--suite',choices=['repocontextbench','stackrepoqa'],
                        default='repocontextbench')
    parser.add_argument('--case-id',action='append',default=[])
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--compare',action='store_true',
                        help='Paired baseline vs V5.9 retrieval on the same cached index')
    parser.add_argument('--summary-only',action='store_true',
                        help='Print only aggregate recalls across the selected cases')
    args=parser.parse_args(argv)
    run_id=run.check_run_id(args.from_run)
    suite=args.suite
    checkout=run.CACHES / run.REPOS[suite][2]
    index=(run.RESULTS / run_id / '_prepared_indexes' / suite /
           'middle-files' / 'code_intelligence.sqlite')
    if not checkout.is_dir() or not index.is_file():
        parser.error('Missing frozen repository or prepared index: '+str(index))
    if run.git('rev-parse','HEAD',cwd=checkout)!=run.REPOS[suite][1]:
        parser.error('Checkout commit is not the frozen benchmark commit')
    selected=[c for c in run.read_cases() if c['suite']==suite]
    wanted=set(args.case_id)
    unknown=wanted-{c['id'] for c in selected}
    if unknown:parser.error('Unknown case-id(s): '+', '.join(sorted(unknown)))
    if wanted:selected=[c for c in selected if c['id'] in wanted]
    repo=Repo(checkout)
    repo.intelligence_db=index
    results=[evaluate_case(repo,case,limit=args.limit) for case in selected]
    aggregate=summarize_candidate_results(results)
    report={'suite':suite,'run_id':run_id,'strategy':'v59','summary':aggregate}
    if args.compare:
        baseline=[evaluate_case(repo,case,strategy='baseline',limit=args.limit)
                  for case in selected]
        report['comparison']=compare_candidate_results(baseline,results)
        if not args.summary_only:
            report['baseline_cases']=baseline
    if not args.summary_only:
        report['cases']=results
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
