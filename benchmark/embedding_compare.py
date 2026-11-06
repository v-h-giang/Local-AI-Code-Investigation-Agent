"""Paired frozen-repo comparison of code retrieval; no generative LLM calls.

Run as: py -3 benchmark/embedding_compare.py --from-run RUN --embed-db PATH
Gold is read ONLY after retrieval to compute file/chunk metrics.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmark import run
from codebase import Repo
from code_intelligence import search_file_candidates
from semantic_retrieval import OllamaEmbedder,dense_search,symbol_candidates,_rrf
from scoped_symbol_resolution import scoped_symbol_resolve
from dense_preserving_fusion import hybrid_head_dense_tail
from code_intelligence import search_relevant_sources
from contextlib import closing
import sqlite3


def _indexed_symbol_names(repo, question, hits):
    """Attach real SQLite name/kind to each symbol hit for DIAGNOSTICS ONLY.

    The code uses symbol_candidates() unchanged for retrieval. The extra SQL
    lookup never alters rankings or admits benchmark gold labels.
    """
    import re
    terms = {token.casefold() for token in
             re.findall(r'\b[A-Za-z_][A-Za-z_0-9]{2,79}\b', question)}
    output = []
    with closing(sqlite3.connect(
            Path(repo.intelligence_db).resolve().as_uri() + '?mode=ro',
            uri=True)) as conn:
        for hit in hits:
            matching = conn.execute(
                'SELECT name,kind FROM symbols WHERE path=? AND line=?',
                (hit['path'],hit['line_hint'])).fetchall()
            names = sorted({name for name,kind in matching
                            if name.casefold() in terms})
            output.append({'path':hit['path'],'line':hit['line_hint'],
                           'names':names,
                           'kinds':sorted({kind for name,kind in matching
                                           if name.casefold() in terms})})
    return output


def _evaluate(rows,gold):
    paths = list(dict.fromkeys(r['path'] for r in rows))
    gold_files = {s['path'] for s in gold}
    top8=set(paths[:8])
    top20=set(paths[:20])
    span_ids = sorted(
        span.get('id',str(i))
        for i,span in enumerate(gold)
        if any(r['path']==span['path']
               and isinstance(r.get('start_line'),int)
               and isinstance(r.get('end_line'),int)
               and r['start_line']<=span['end_line']
               and r['end_line']>=span['start_line']
               for r in rows[:20]))
    return {
        'file_hits_at_8':len(top8 & gold_files),
        'file_hits_at_20':len(top20 & gold_files),
        'gold_files_at_8':sorted(top8 & gold_files),
        'gold_files_at_20':sorted(top20 & gold_files),
        'chunk_span_overlap_hits_at_20':len(span_ids),
        'chunk_span_overlap_ids_at_20':span_ids,
        'rank_of_first_gold':next((i for i,p in enumerate(paths,1)
                                   if p in gold_files),None),
        'top_files':paths[:8],
        'top8_diagnostics':[{
            'rank':i,'path':row['path'],
            'retrieval_views':row.get('retrieval_views') or
                (['dense'] if 'similarity' in row else []),
            'line_hint_source':row.get('line_hint_source','dense'),
            'line_start':row.get('line_start',row.get('start_line')),
            'line_end':row.get('line_end',row.get('end_line')),
            'is_gold_file':row['path'] in gold_files
        } for i,row in enumerate(rows[:8],1)]
    }


def compare(run_id,suite,db,embedder,case_ids=(),intelligence_index=None):
    """Evaluate identical cached retrieval views; no generative LLM calls.

    Gold labels are first read after ALL mode rankings have been created.
    Reuses one dense query per case across three/four modes for fair ablation.
    """
    run_id=run.check_run_id(run_id)
    checkout=run.CACHES/run.REPOS[suite][2]
    if not checkout.is_dir():
        raise FileNotFoundError('Pinned checkout not found: '+str(checkout))
    if run.git('rev-parse','HEAD',cwd=checkout)!=run.REPOS[suite][1]:
        raise RuntimeError('Frozen checkout commit mismatch')
    index=(Path(intelligence_index).expanduser().resolve() if intelligence_index
           else run.RESULTS/run_id/'_prepared_indexes'/suite/
                'middle-files'/'code_intelligence.sqlite')
    if not index.is_file():
        raise FileNotFoundError('Pinned intelligence index not found: '+str(index))
    repo=Repo(checkout)
    repo.intelligence_db=index
    cases=[c for c in run.read_cases() if c['suite']==suite
           and (not case_ids or c['id'] in case_ids)]
    result=[]
    modes=('baseline','dense','hybrid','hybrid_symbol','hybrid_symbol_gated',
           'hybrid_symbol_scoped','hybrid_dense_tail')
    for case in cases:
        query=case['question']
        started=time.perf_counter()
        lexical=search_file_candidates(repo,query,limit=40,strategy='v59')
        line_hits=search_relevant_sources(repo,query,limit=30)
        dense=dense_search(repo,query,db,embedder,limit=60,per_file=1)
        symbols=symbol_candidates(repo,query,limit=30)
        gated_symbols=symbol_candidates(repo,query,limit=30,confidence_gate=True)
        views=[('filename',1.0,lexical),('fts-line',1.1,line_hits),
               ('dense',1.4,dense)]
        # Exact production RRF weights, limits and view ordering.
        ranked={'baseline':lexical[:30],'dense':dense[:40],
                'hybrid':_rrf(views,limit=30),
                'hybrid_symbol':_rrf(
                    views+[('exact-symbol',1.3,symbols)],limit=30),
                'hybrid_symbol_gated':_rrf(
                    views+[('exact-symbol',1.3,gated_symbols)],limit=30)}
        ranked['hybrid_symbol_scoped']=scoped_symbol_resolve(
            repo,query,ranked['hybrid'],limit=30)
        ranked['hybrid_dense_tail']=hybrid_head_dense_tail(
            ranked['hybrid'],dense,limit=30,head=8)
        elapsed=time.perf_counter()-started
        # Gold is read only now, after all retrieval decisions.
        gold=case.get('gold_spans') or []
        relevant={s['path'] for s in gold}
        variants={mode:_evaluate(ranked[mode],gold) for mode in modes}
        names=_indexed_symbol_names(repo,query,symbols)
        hybrid=variants['hybrid']
        with_symbol=variants['hybrid_symbol']
        gated=variants['hybrid_symbol_gated']
        scoped=variants['hybrid_symbol_scoped']
        dense_tail=variants['hybrid_dense_tail']
        dense_eval=variants['dense']
        result.append({
            'id':case['id'],'question':query,
            'gold_files':len(relevant),'gold_spans':len(gold),
            'seconds':round(elapsed,3),
            'variants':variants,
            'symbol_diagnostics':{
                'match_count':len(symbols),
                'matched_gold_file_paths':sorted(
                    relevant & {s['path'] for s in symbols}),
                'matched_symbol_names':sorted(
                    {n for hit in names for n in hit['names']}),
                'matching_name_locations':names,
                'gated_match_count':len(gated_symbols),
                'gated_matching_name_locations':_indexed_symbol_names(
                    repo,query,gated_symbols),
            },
            'hybrid_to_symbol':{
                'new_gold_files_at_8':sorted(
                    set(with_symbol['gold_files_at_8']) -
                    set(hybrid['gold_files_at_8'])),
                'lost_gold_files_at_8':sorted(
                    set(hybrid['gold_files_at_8']) -
                    set(with_symbol['gold_files_at_8'])),
                'new_chunk_overlap_ids':sorted(
                    set(with_symbol['chunk_span_overlap_ids_at_20']) -
                    set(hybrid['chunk_span_overlap_ids_at_20'])),
                'lost_chunk_overlap_ids':sorted(
                    set(hybrid['chunk_span_overlap_ids_at_20']) -
                    set(with_symbol['chunk_span_overlap_ids_at_20'])),
                'new_top8_paths':sorted(
                    set(with_symbol['top_files'])-set(hybrid['top_files'])),
                'displaced_top8_paths':sorted(
                    set(hybrid['top_files'])-set(with_symbol['top_files'])),
            },
            'gated_vs_hybrid':{
                'new_gold_files_at_8':sorted(
                    set(gated['gold_files_at_8'])-set(hybrid['gold_files_at_8'])),
                'lost_gold_files_at_8':sorted(
                    set(hybrid['gold_files_at_8'])-set(gated['gold_files_at_8'])),
                'new_chunk_overlap_ids':sorted(
                    set(gated['chunk_span_overlap_ids_at_20'])-
                    set(hybrid['chunk_span_overlap_ids_at_20'])),
                'lost_chunk_overlap_ids':sorted(
                    set(hybrid['chunk_span_overlap_ids_at_20'])-
                    set(gated['chunk_span_overlap_ids_at_20'])),
            },
            'scoped_vs_hybrid':{
                'new_gold_files_at_8':sorted(
                    set(scoped['gold_files_at_8'])-set(hybrid['gold_files_at_8'])),
                'lost_gold_files_at_8':sorted(
                    set(hybrid['gold_files_at_8'])-set(scoped['gold_files_at_8'])),
                'new_chunk_overlap_ids':sorted(
                    set(scoped['chunk_span_overlap_ids_at_20'])-
                    set(hybrid['chunk_span_overlap_ids_at_20'])),
                'lost_chunk_overlap_ids':sorted(
                    set(hybrid['chunk_span_overlap_ids_at_20'])-
                    set(scoped['chunk_span_overlap_ids_at_20'])),
                'new_top8_paths':sorted(
                    set(scoped['top_files'])-set(hybrid['top_files'])),
                'displaced_top8_paths':sorted(
                    set(hybrid['top_files'])-set(scoped['top_files'])),
                'scoped_hinted_files_at_8':sum(
                    bool(row.get('symbol_hints'))
                    for row in ranked['hybrid_symbol_scoped'][:8]),
            },
            'dense_tail_vs_hybrid':{
                'new_gold_files_at_8':sorted(
                    set(dense_tail['gold_files_at_8'])-set(hybrid['gold_files_at_8'])),
                'lost_gold_files_at_8':sorted(
                    set(hybrid['gold_files_at_8'])-set(dense_tail['gold_files_at_8'])),
                'new_gold_files_at_20':sorted(
                    set(dense_tail['gold_files_at_20'])-set(hybrid['gold_files_at_20'])),
                'lost_gold_files_at_20':sorted(
                    set(hybrid['gold_files_at_20'])-set(dense_tail['gold_files_at_20'])),
                'new_chunk_overlap_ids_at_20':sorted(
                    set(dense_tail['chunk_span_overlap_ids_at_20'])-
                    set(hybrid['chunk_span_overlap_ids_at_20'])),
                'lost_chunk_overlap_ids_at_20':sorted(
                    set(hybrid['chunk_span_overlap_ids_at_20'])-
                    set(dense_tail['chunk_span_overlap_ids_at_20'])),
            },
            'dense_to_hybrid':{
                'new_gold_files_at_8':sorted(
                    set(hybrid['gold_files_at_8']) -
                    set(dense_eval['gold_files_at_8'])),
                'lost_gold_files_at_8':sorted(
                    set(dense_eval['gold_files_at_8']) -
                    set(hybrid['gold_files_at_8'])),
            }
        })
    summary={}
    total_files=sum(x['gold_files'] for x in result)
    total_spans=sum(x['gold_spans'] for x in result)
    for mode in modes:
        hits8=sum(x['variants'][mode]['file_hits_at_8'] for x in result)
        hits20=sum(x['variants'][mode]['file_hits_at_20'] for x in result)
        spans=sum(x['variants'][mode]['chunk_span_overlap_hits_at_20'] for x in result)
        summary[mode]={
            'file_hits_at_8':hits8,
            'recall_at_8':round(hits8/total_files,4) if total_files else None,
            'file_hits_at_20':hits20,
            'recall_at_20':round(hits20/total_files,4) if total_files else None,
            'chunk_span_overlap_hits_at_20':spans if mode!='baseline' else None,
            'chunk_span_overlap_at_20':(
                round(spans/total_spans,4) if total_spans else None)
                if mode!='baseline' else None,
        }
    summary['symbol_diagnostics']={
        'cases_with_symbol_matches':sum(
            bool(x['symbol_diagnostics']['match_count']) for x in result),
        'cases_with_symbol_on_gold_file':sum(
            bool(x['symbol_diagnostics']['matched_gold_file_paths']) for x in result),
        'hybrid_to_symbol_gold_file_gain_cases':sum(
            bool(x['hybrid_to_symbol']['new_gold_files_at_8']) for x in result),
        'hybrid_to_symbol_gold_file_loss_cases':sum(
            bool(x['hybrid_to_symbol']['lost_gold_files_at_8']) for x in result),
        'total_retrieval_seconds':round(sum(x['seconds'] for x in result),3),
        'scoped_gold_file_gain_cases':sum(
            bool(x['scoped_vs_hybrid']['new_gold_files_at_8']) for x in result),
        'scoped_gold_file_loss_cases':sum(
            bool(x['scoped_vs_hybrid']['lost_gold_files_at_8']) for x in result),
        'scoped_cases_with_hints_at_8':sum(
            bool(x['scoped_vs_hybrid']['scoped_hinted_files_at_8']) for x in result),
        'dense_tail_top20_gain_cases':sum(
            bool(x['dense_tail_vs_hybrid']['new_gold_files_at_20']) for x in result),
        'dense_tail_top20_loss_cases':sum(
            bool(x['dense_tail_vs_hybrid']['lost_gold_files_at_20']) for x in result),
        'gated_symbol_match_cases':sum(bool(x['symbol_diagnostics']['gated_match_count'])
                                        for x in result),
    }
    return {'suite':suite,'run_id':run_id,'case_count':len(result),
            'gold_files':total_files,'gold_spans':total_spans,
            'summary':summary,'cases':result,
            'method':{'ollama_embedding_queries_per_case':1,
                      'generative_llm_calls':0,
                      'reuse_identical_ranked_views':True,
                      'symbol_gate_only_changes_exact_symbol_view':True,
                      'scoped_mode_uses_existing_hybrid_ranking':True,
                      'dense_tail_preserves_hybrid_top8':True,
                      'frozen_source_commit':run.REPOS[suite][1]},
            'note':'Gold-blind ranking; chunk overlap is a retrieval bound, NOT '
                   'observed evidence recall, citation validity or answer correctness.'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--from-run',required=True)
    p.add_argument('--suite',choices=sorted(run.REPOS),default='repocontextbench')
    p.add_argument('--embed-db',type=Path,required=True)
    p.add_argument('--model',default='qwen3-embedding:0.6b')
    p.add_argument('--host',default='http://127.0.0.1:11434')
    p.add_argument('--dimensions',type=int,default=1024)
    p.add_argument('--case-id',action='append',default=[])
    p.add_argument('--intelligence-index',type=Path)
    p.add_argument('--out',type=Path)
    p.add_argument('--summary-only',action='store_true',
                   help='Print only summary and report path; save full JSON with --out')
    args=p.parse_args(argv)
    report=compare(args.from_run,args.suite,args.embed_db,
                   OllamaEmbedder(args.model,args.host,args.dimensions),args.case_id,
                   intelligence_index=args.intelligence_index)
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(text+'\n',encoding='utf-8')
    if args.summary_only:
        print(json.dumps({'summary':report['summary'],
                          'report':str(args.out) if args.out else None},
                         ensure_ascii=False,indent=2))
    else:
        print(text)


if __name__=='__main__':main()
