"""Safe SQLite/index maintenance for the local code agent (stdlib only).

Dry-run by default. --apply optimizes known SQLite files and removes only
completed benchmark per-case index copies. Never deletes knowledge, source,
embedding master DBs, or original workflow records.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3

ROOT=Path(__file__).resolve().parent


def _path(p):
    return Path(p).expanduser().resolve()


def databases(root, output, results, embedding_db, kb_path):
    home=Path.home()/'.local_code_agent'
    kb=_path(kb_path or os.getenv('LOCAL_CODE_AGENT_KB_PATH') or
             home/'knowledge'/'global_code_knowledge.sqlite')
    dbs={'global_knowledge':kb,
         'code_intelligence':output/'middle-files'/'code_intelligence.sqlite'}
    if (home/'index').is_dir():
        for p in sorted((home/'index').glob('*.sqlite')):
            dbs['project_fts:'+p.name]=p
    if results.is_dir():
        for p in sorted(results.glob('*/_prepared_indexes/*/middle-files/code_intelligence.sqlite')):
            dbs['benchmark_master:'+str(p.relative_to(results))]=p
    explicit=embedding_db or os.getenv('LOCAL_CODE_AGENT_EMBEDDING_DB')
    if explicit:
        p=_path(explicit)
        if p.is_file():
            dbs['dense_embedding']=p
        elif p.is_dir():
            for db in sorted(p.glob('*.sqlite')):
                dbs['dense_embedding:'+db.name]=db
    if results.is_dir():
        for p in sorted(results.glob('*.sqlite')):
            dbs.setdefault('benchmark_embedding:'+p.name,p)
    return dbs


def completed_copies(results):
    if not results.is_dir():
        return
    for run in sorted(results.iterdir()):
        if not run.is_dir() or run.is_symlink():
            continue
        for case in sorted(run.iterdir()):
            if not case.is_dir() or case.is_symlink():
                continue
            db=case/'middle-files'/'code_intelligence.sqlite'
            record=case/'runner_record.json'
            if not db.is_file() or db.is_symlink() or not record.is_file():
                continue
            try:
                status=json.loads(record.read_text(encoding='utf-8'))
            except (OSError,ValueError,UnicodeError):
                continue
            if status.get('machine_result_available') is True:
                yield db


def inspect(db):
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=1)) as conn:
        integrity=conn.execute('PRAGMA quick_check').fetchone()[0]
        pages=conn.execute('PRAGMA page_count').fetchone()[0]
        empty=conn.execute('PRAGMA freelist_count').fetchone()[0]
        page_size=conn.execute('PRAGMA page_size').fetchone()[0]
    return {'quick_check':integrity,'pages':pages,'free_pages':empty,
            'estimated_reclaimable_bytes':empty*page_size}


def optimize(db):
    # VACUUM needs spare working disk space; refuse on nearly-full drives.
    size=db.stat().st_size
    needed=2*size+100*1024*1024
    available=shutil.disk_usage(db.parent).free
    if available<needed:
        return {'status':'skipped_low_disk','available_bytes':available,
                'needed_free_bytes':needed}
    try:
        with closing(sqlite3.connect(str(db),timeout=2)) as conn:
            if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                return {'status':'skipped_integrity_error'}
            conn.execute('PRAGMA optimize')
            conn.commit()
            conn.execute('VACUUM')
        return {'status':'optimized','bytes_after':db.stat().st_size}
    except (sqlite3.Error,OSError) as exc:
        return {'status':'failed','error':str(exc)[:300]}


def main(argv=None):
    p=argparse.ArgumentParser(description='Audit and optimize agent SQLite storage. Dry-run by default.')
    p.add_argument('--root',type=Path,default=ROOT,help='Agent repository root')
    p.add_argument('--output',type=Path,help='Architecture output directory')
    p.add_argument('--results',type=Path,help='Benchmark results directory')
    p.add_argument('--embedding-db',type=Path,help='Embedding index SQLite file or directory')
    p.add_argument('--kb-path',type=Path,help='Global knowledge SQLite database')
    p.add_argument('--apply',action='store_true',help='Apply safe SQLite maintenance and cleanup')
    p.add_argument('--no-vacuum',action='store_true')
    p.add_argument('--no-clean-copies',action='store_true')
    args=p.parse_args(argv)
    root=_path(args.root)
    output=_path(args.output) if args.output else root/'output'/'architecture'
    results=_path(args.results) if args.results else root/'benchmark'/'results'
    report={'mode':'apply' if args.apply else 'dry-run',
            'databases':[],'redundant_benchmark_copies':[],
            'summary':{'database_bytes_before':0,'candidate_copy_bytes':0,
                       'copies_removed':0,'bytes_removed':0}}
    for name,db in databases(root,output,results,args.embedding_db,args.kb_path).items():
        exists=db.is_file()
        row={'name':name,'path':str(db),'exists':exists,
             'bytes_before':db.stat().st_size if exists else 0}
        report['summary']['database_bytes_before']+=row['bytes_before']
        if exists and not db.is_symlink():
            try:
                row.update(inspect(db))
                if args.apply and not args.no_vacuum:
                    row.update(optimize(db))
            except (sqlite3.Error,OSError) as exc:
                row.update(status='unreadable',error=str(exc)[:300])
        report['databases'].append(row)
    for db in completed_copies(results):
        size=db.stat().st_size
        row={'path':str(db),'bytes':size,'action':'would_remove'}
        report['summary']['candidate_copy_bytes']+=size
        if args.apply and not args.no_clean_copies:
            try:
                db.unlink()
                row['action']='removed'
                report['summary']['copies_removed']+=1
                report['summary']['bytes_removed']+=size
            except OSError as exc:
                row.update(action='failed',error=str(exc)[:300])
        report['redundant_benchmark_copies'].append(row)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
