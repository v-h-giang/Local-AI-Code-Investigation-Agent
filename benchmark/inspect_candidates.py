"""Inspect V5 filename candidate ranking using an existing benchmark SQLite index.

Offline; no Ollama, no source writes, no benchmark gold data in the ranker.
Gold labels here are used solely to calculate diagnostics after retrieval.
"""
import argparse
import json
import sys
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from benchmark import run
from codebase import Repo
from code_intelligence import search_file_candidates
from knowledge_base import query_knowledge, expand_query_terms
from knowledge_retrieval import safe_knowledge_terms, discover_concept_paths, related_source_paths



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




def evaluate_case(repo, case, *, strategy='v59', limit=20, ranked=None):
    if ranked is None:
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




def diagnose_case(repo, case, baseline_ranked, v59_ranked):
    """Post-retrieval diagnosis; gold labels NEVER enter production ranking.

    Check indexing separately from KB concept matching, independent concept
    discovery, graph reachability, and final ranking to localize recall loss.
    """
    question=case['question']
    gold={span['path'] for span in case['gold_spans']}
    concepts=query_knowledge(question,limit=8)
    raw_aliases=expand_query_terms(question,max_terms=6)
    aliases=safe_knowledge_terms(raw_aliases,re.findall(r'[A-Za-z0-9_]+',question.lower()))
    with closing(sqlite3.connect(repo.intelligence_db)) as conn:
        indexed=set()
        for path in gold:
            if conn.execute('SELECT 1 FROM files WHERE path=?',(path,)).fetchone():
                indexed.add(path)
        kb_paths=discover_concept_paths(conn,aliases) if aliases else {}
        graph_paths=related_source_paths(
            conn,[r['path'] for r in baseline_ranked[:12]])
    baseline_ranks={r['path']:idx+1 for idx,r in enumerate(baseline_ranked)}
    variant_ranks={r['path']:idx+1 for idx,r in enumerate(v59_ranked)}
    misses=gold-{r['path'] for r in v59_ranked[:20]}
    if not gold.issubset(indexed):
        obstacle='gold-not-indexed'
    elif not misses:
        obstacle='all-gold-top20'
    elif not concepts:
        obstacle='no-concept-matched'
    elif not aliases:
        obstacle='no-safe-alias'
    elif not kb_paths:
        obstacle='no-kb-discovered-files'
    elif not (gold & set(kb_paths)):
        obstacle='kb-discovery-missed-gold'
    elif misses & set(kb_paths):
        obstacle='kb-gold-found-but-outside-top20'
    else:
        obstacle='gold-missed-by-other-retrieval'
    return {
        'id':case['id'],
        'gold_files':len(gold),
        'gold_indexed':len(indexed),
        'gold_missing_from_index':sorted(gold-indexed),
        'concept_ids':[x['concept_id'] for x in concepts],
        'expanded_aliases':aliases,
        'kb_discovered_files':len(kb_paths),
        'kb_only_vs_baseline_top20':len(set(kb_paths)-set(baseline_ranks).intersection(
            {r['path'] for r in baseline_ranked[:20]})),
        'kb_gold_discovered':sorted(gold & set(kb_paths)),
        'graph_neighbor_files':len(graph_paths),
        'graph_gold_discovered':sorted(gold & set(graph_paths)),
        'new_v59_paths_at_20':len(
            {r['path'] for r in v59_ranked[:20]}-
            {r['path'] for r in baseline_ranked[:20]}),
        'missing_gold':[
            {'path':p,'baseline_rank_50':baseline_ranks.get(p),
             'v59_rank_50':variant_ranks.get(p),
             'kb_found':p in kb_paths,'graph_found':p in graph_paths}
            for p in sorted(misses)],
        'diagnostic_category':obstacle,
        'note':'Gold labels are used only after independent retrieval for diagnosis.'
    }


def summarize_diagnostics(rows):
    categories=Counter(row['diagnostic_category'] for row in rows)
    return {
        'cases':len(rows),
        'categories':dict(sorted(categories.items())),
        'cases_with_matched_concepts':sum(bool(r['concept_ids']) for r in rows),
        'cases_with_safe_aliases':sum(bool(r['expanded_aliases']) for r in rows),
        'cases_with_kb_discovery':sum(r['kb_discovered_files']>0 for r in rows),
        'cases_where_kb_reaches_gold':sum(bool(r['kb_gold_discovered']) for r in rows),
        'cases_where_graph_reaches_gold':sum(bool(r['graph_gold_discovered']) for r in rows),
        'cases_with_new_v59_top20_paths':sum(
            r['new_v59_paths_at_20']>0 for r in rows),
        'gold_files_missing_from_index':sum(
            len(r['gold_missing_from_index']) for r in rows),
        'gold_missed_top20_but_visible_top50_v59':sum(
            sum(item['v59_rank_50'] is not None for item in r['missing_gold'])
            for r in rows),
        'gold_missed_top20_but_visible_top50_baseline':sum(
            sum(item['baseline_rank_50'] is not None for item in r['missing_gold'])
            for r in rows)
    }



def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-run',required=True,
                        help='Existing benchmark run with prepared SQLite index')
    parser.add_argument('--suite',choices=['repocontextbench','stackrepoqa'],
                        default='repocontextbench')
    parser.add_argument('--case-id',action='append',default=[])
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--fusion',action='store_true',
                        help='Evaluate experimental V5.10 fusion on the SAME frozen index')
    parser.add_argument('--diagnose',action='store_true',
                        help='Audit why KB, symbol or graph discovery missed gold (offline)')
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
    # Diagnostics use a wider evaluation window, never an LLM call. They
    # must not change the production top-8/top-20 retrieval budget.
    ranked_limit=50 if args.diagnose else max(20,args.limit)
    v59_ranked=[search_file_candidates(
        repo,case['question'],limit=ranked_limit,strategy='v59')
        for case in selected]
    results=[evaluate_case(repo,case,limit=args.limit,ranked=ranked)
             for case,ranked in zip(selected,v59_ranked)]
    aggregate=summarize_candidate_results(results)
    report={'suite':suite,'run_id':run_id,'strategy':'v59','summary':aggregate}
    baseline_ranked=[]
    if args.compare or args.diagnose or args.fusion:
        baseline_ranked=[search_file_candidates(
            repo,case['question'],limit=ranked_limit,strategy='baseline')
            for case in selected]
    if args.compare:
        baseline=[evaluate_case(repo,case,strategy='baseline',limit=args.limit,
                                ranked=ranked)
                  for case,ranked in zip(selected,baseline_ranked)]
        report['comparison']=compare_candidate_results(baseline,results)
        if not args.summary_only:
            report['baseline_cases']=baseline
    if args.fusion:
        # Opt-in offline comparison. Gold labels are scored only after
        # retrieval, never provided to the experimental ranker.
        fusion_ranked=[search_file_candidates(
            repo,case['question'],limit=ranked_limit,strategy='v510')
            for case in selected]
        fusion_cases=[evaluate_case(repo,case,limit=args.limit,ranked=ranked)
                      for case,ranked in zip(selected,fusion_ranked)]
        baseline_cases=[evaluate_case(repo,case,strategy='baseline',
                        limit=args.limit,ranked=ranked)
                        for case,ranked in zip(selected,baseline_ranked)]
        report['fusion_experiment']={
            'strategy':'v510',
            'comparison_vs_baseline':compare_candidate_results(
                baseline_cases,fusion_cases)
        }
        if not args.summary_only:
            report['fusion_experiment']['cases']=fusion_cases
    if args.diagnose:
        details=[diagnose_case(repo,case,base,variant)
                 for case,base,variant in zip(
                     selected,baseline_ranked,v59_ranked)]
        report['diagnostics']={
            'summary':summarize_diagnostics(details),
            # Show all problem cases even with --summary-only, so users can
            # identify what to fix without a huge top-candidates dump.
            'problem_cases':[d for d in details
                             if d['diagnostic_category']!='all-gold-top20']
        }
        if not args.summary_only:
            report['diagnostics']['all_cases']=details
    if not args.summary_only:
        report['cases']=results
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
