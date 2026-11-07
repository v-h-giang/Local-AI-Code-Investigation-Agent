"""Read-only structural audit of multi-window selection against frozen SQLite.

Does NOT query Ollama, select by gold labels or run source code.
Structural alternatives are NOT embedding-ranked alternatives.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import run
from benchmark.top8_multiwindow_diagnostics import (
    window, select_alternates, select_from_dense_windows,
)


def self_test():
    """Fail fast if the local selector cannot consume raw Dense chunk fields."""
    hybrid=[{'path':'src/long.py','line_start':1,'line_end':48}]
    rows={'src/long.py':[
        {'path':'src/long.py','start_line':1,'end_line':48,'similarity':0.9},
        {'path':'src/long.py','start_line':37,'end_line':84,'similarity':0.8},
        {'path':'src/long.py','start_line':145,'end_line':192,'similarity':0.7},
    ]}
    chosen=select_from_dense_windows(hybrid,rows,max_extra=2)
    if [r['start_line'] for r in chosen] != [37,145]:
        raise RuntimeError(
            'Local multi-window selector is incompatible with raw Dense '
            'start_line/end_line fields; git pull before rerunning benchmark.')
    return True


def audit(report, conn):
    """Audit structural possibility only: source-file chunks have no scores."""
    rows=report.get('cases')
    if not isinstance(rows,list):
        raise ValueError('Missing cases in saved report')
    samples=[]
    detail=[]
    total_paths=0
    indexed=0
    multi=0
    viable=0
    structural_count=0
    cases_multi=0
    cases_viable=0
    used=set()
    for item in rows:
        variants=item.get('variants') or {}
        head=(variants.get('hybrid') or {}).get('top8_diagnostics')
        if not isinstance(head,list):
            raise ValueError('Missing Hybrid top8 for '+str(item.get('id')))
        if item.get('id') in used:
            raise ValueError('Duplicate case ID in report')
        used.add(item['id'])
        case_multi=0
        case_viable=0
        for candidate in head:
            path=candidate.get('path')
            if not isinstance(path,str):
                continue
            total_paths+=1
            chunks=conn.execute(
                'SELECT start_line,end_line FROM chunks WHERE path=? '
                'ORDER BY start_line', (path,)).fetchall()
            if chunks:
                indexed+=1
            if len(chunks)>1:
                multi+=1
                case_multi+=1
            raw=[{'path':path,'start_line':int(start),
                  'end_line':int(end)}
                 for start,end in chunks]
            # Unranked structural feasibility, NOT semantic quality:
            alternatives=select_alternates(
                [candidate],raw,max_extra=4,min_new_lines=8)
            if alternatives:
                viable+=1
                case_viable+=1
                structural_count+=len(alternatives)
                if len(samples)<8:
                    samples.append({
                        'id':item['id'],'path':path,
                        'hybrid_window':window(candidate),
                        'indexed_chunk_count':len(chunks),
                        'unranked_example_window':(
                            alternatives[0]['start_line'],
                            alternatives[0]['end_line']),
                        'example_new_lines':alternatives[0]['new_lines'],
                    })
        cases_multi+=bool(case_multi)
        cases_viable+=bool(case_viable)
        actual=((item.get('multiwindow_diagnostics') or {})
                .get('extra_window_count'))
        detail.append({'id':item['id'],
                       'top8_multi_chunk_files':case_multi,
                       'top8_structural_viable_files':case_viable,
                       'saved_selected_alternates':actual})
    saved_total=sum((x['saved_selected_alternates'] or 0) for x in detail)
    return {
        'summary':{
            'cases':len(rows),
            'hybrid_top8_path_occurrences':total_paths,
            'top8_paths_present_in_embedding_index':indexed,
            'top8_multi_chunk_path_occurrences':multi,
            'top8_structurally_viable_path_occurrences':viable,
            'total_unranked_structural_alternates':structural_count,
            'cases_with_multichunk_top8_files':cases_multi,
            'cases_with_structurally_viable_top8_files':cases_viable,
            'alternates_selected_in_saved_benchmark':saved_total,
            'selector_raw_dense_self_test_passed':True,
            'needs_instrumentation':bool(viable and not saved_total),
        },
        'examples':samples,
        'cases':detail,
        'interpretation':(
            'Structural availability is an upper-bound possibility; '
            'it does not prove that the top-3 similarity-ranked chunks '
            'will pass the nonoverlap filter.'
        ),
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--from-report',type=Path,required=True)
    p.add_argument('--embed-db',type=Path,required=True)
    p.add_argument('--out',type=Path)
    args=p.parse_args(argv)
    self_test()
    if not args.from_report.is_file() or not args.embed_db.is_file():
        p.error('Report or embedding SQLite missing')
    saved=json.loads(args.from_report.read_text(encoding='utf-8'))
    suite=saved.get('suite')
    if suite not in run.REPOS:
        p.error('Unexpected benchmark suite')
    if (saved.get('method') or {}).get('frozen_source_commit') != run.REPOS[suite][1]:
        p.error('Source revision mismatch')
    uri=args.embed_db.resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as conn:
        result=audit(saved,conn)
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(
            json.dumps(result,ensure_ascii=False,indent=2)+'\n',
            encoding='utf-8')
    print(json.dumps(
        {'summary':result['summary'],'examples':result['examples'][:3],
         'report':str(args.out) if args.out else None},
        ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    sys.exit(main())
