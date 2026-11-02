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
import run
from codebase import Repo
from code_intelligence import search_file_candidates
from semantic_retrieval import OllamaEmbedder,dense_search,hybrid_search


def compare(run_id,suite,db,embedder,case_ids=()):
    run_id=run.check_run_id(run_id)
    checkout=run.CACHES/run.REPOS[suite][2]
    if not checkout.is_dir():
        raise FileNotFoundError('Pinned checkout not found: '+str(checkout))
    if run.git('rev-parse','HEAD',cwd=checkout)!=run.REPOS[suite][1]:
        raise RuntimeError('Frozen checkout commit mismatch')
    index=run.RESULTS/run_id/'_prepared_indexes'/suite/'middle-files'/'code_intelligence.sqlite'
    if not index.is_file():
        raise FileNotFoundError('Pinned intelligence index not found: '+str(index))
    repo=Repo(checkout)
    repo.intelligence_db=index
    cases=[c for c in run.read_cases() if c['suite']==suite
           and (not case_ids or c['id'] in case_ids)]
    result=[]
    for case in cases:
        query=case['question']
        gold=case.get('gold_spans') or []
        relevant={s['path'] for s in gold}
        variants={}
        for mode in ('baseline','dense','hybrid'):
            start=time.perf_counter()
            if mode=='baseline':
                rows=search_file_candidates(repo,query,limit=30,strategy='v59')
            elif mode=='dense':
                rows=dense_search(repo,query,db,embedder,limit=40,per_file=1)
            else:
                rows=hybrid_search(repo,query,db,embedder,limit=30)
            secs=time.perf_counter()-start
            paths=list(dict.fromkeys(r['path'] for r in rows))
            candidates={k:set(paths[:k]) for k in (8,20)}
            # Chunk overlap is an upper bound on line discovery; a source
            # range is not a validated or answer-supporting citation.
            windows=[r for r in rows[:20] if 'start_line' in r and 'end_line' in r]
            window_hits=sum(any(w['path']==sp['path'] and
                                w['start_line']<=sp['end_line'] and
                                w['end_line']>=sp['start_line']
                                for w in windows) for sp in gold)
            variants[mode]={
                'file_hits_at_8':len(candidates[8]&relevant),
                'file_hits_at_20':len(candidates[20]&relevant),
                'chunk_span_overlap_hits_at_20':window_hits,
                'rank_of_first_gold':next((i for i,p in enumerate(paths,1)
                                           if p in relevant),None),
                'seconds':round(secs,3),
                'top_files':paths[:8],
            }
        result.append({'id':case['id'],'gold_files':len(relevant),
                       'gold_spans':len(gold),'variants':variants})
    summary={}
    for mode in ('baseline','dense','hybrid'):
        gold_files=sum(x['gold_files'] for x in result)
        gold_spans=sum(x['gold_spans'] for x in result)
        hits8=sum(x['variants'][mode]['file_hits_at_8'] for x in result)
        hits20=sum(x['variants'][mode]['file_hits_at_20'] for x in result)
        span_hits=sum(x['variants'][mode]['chunk_span_overlap_hits_at_20'] for x in result)
        summary[mode]={
            'recall_at_8':round(hits8/gold_files,4) if gold_files else None,
            'recall_at_20':round(hits20/gold_files,4) if gold_files else None,
            'chunk_span_overlap_at_20':round(span_hits/gold_spans,4) if gold_spans else None,
            'total_query_seconds':round(sum(x['variants'][mode]['seconds'] for x in result),3),
        }
    return {'suite':suite,'run_id':run_id,'case_count':len(result),
            'gold_files':sum(x['gold_files'] for x in result),
            'summary':summary,'cases':result,
            'note':'Frozen corpus; label-blind retrieval; candidate spans are NOT evidence citations.'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--from-run',required=True)
    p.add_argument('--suite',choices=sorted(run.REPOS),default='repocontextbench')
    p.add_argument('--embed-db',type=Path,required=True)
    p.add_argument('--model',default='qwen3-embedding:0.6b')
    p.add_argument('--host',default='http://127.0.0.1:11434')
    p.add_argument('--dimensions',type=int,default=1024)
    p.add_argument('--case-id',action='append',default=[])
    p.add_argument('--out',type=Path)
    args=p.parse_args(argv)
    report=compare(args.from_run,args.suite,args.embed_db,
                   OllamaEmbedder(args.model,args.host,args.dimensions),args.case_id)
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(text+'\n',encoding='utf-8')
    print(text)


if __name__=='__main__':main()
