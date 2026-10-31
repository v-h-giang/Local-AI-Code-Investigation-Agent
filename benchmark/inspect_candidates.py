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
import run
from codebase import Repo
from code_intelligence import search_file_candidates


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-run',required=True,
                        help='Existing benchmark run with prepared SQLite index')
    parser.add_argument('--suite',choices=['repocontextbench','stackrepoqa'],
                        default='repocontextbench')
    parser.add_argument('--case-id',action='append',default=[])
    parser.add_argument('--limit',type=int,default=20)
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
    results=[]
    for case in selected:
        ranked=search_file_candidates(repo,case['question'],limit=max(20,args.limit))
        gold={span['path'] for span in case['gold_spans']}
        result={'id':case['id'],'gold_files':len(gold)}
        for k in (8,20):
            paths={item['path'] for item in ranked[:k]}
            hits=sorted(paths & gold)
            result[f'candidate_gold_hits_at_{k}']=len(hits)
            result[f'candidate_recall_at_{k}']=round(len(hits)/len(gold),4) if gold else None
        result['top_candidates']=[{'path':r['path'],'score':r['path_score'],
                                   'content_terms':r.get('content_terms',[])}
                                  for r in ranked[:max(1,min(20,args.limit))]]
        results.append(result)
    print(json.dumps({'suite':suite,'run_id':run_id,'cases':results},
                     ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
