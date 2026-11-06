"""Validate externally authored gold span coordinates against a frozen source tree.

This is a separate post-authoring quality gate. Candidate generation reads only
its question manifest; this validator does not rank or select source evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from codebase import Repo
from benchmark.heldout_evidence_eval import _read_jsonl, _path, _question, _validate_checkout
from benchmark.heldout_window_builder import read_questions

_COMMIT=re.compile(r'^[0-9a-f]{40}$')
_NUMBERED=re.compile(r'^\s*(\d+)\s+\|\s')


def validate_labels(repo, questions, labels, known, *, repository, commit):
    if not questions or not isinstance(labels,list):
        raise ValueError('Missing question or label records')
    by_id={r['id']:r for r in questions}
    if len(labels)!=len(by_id):
        raise ValueError('Labeled case count differs from questions')
    known_ids={r.get('id') for r in known}
    known_questions={(r.get('repo','').casefold(),_question(r['question']))
                     for r in known if isinstance(r.get('repo'),str) and
                     isinstance(r.get('question'),str) and r['question'].strip()}
    seen=set(); links=[]; span_count=0
    for row in labels:
        if not isinstance(row,dict):
            raise ValueError('Label record must be an object')
        ident=row.get('id')
        if ident not in by_id or ident in seen:
            raise ValueError('Duplicate or unexpected labeled case')
        seen.add(ident)
        q=by_id[ident]
        if any(row.get(k)!=q[k] for k in ('id','suite','repo','commit','question')):
            raise ValueError('Labeled record does not match question manifest')
        if ident in known_ids or (repository.casefold(),_question(q['question'])) in known_questions:
            raise ValueError('Case overlaps a previously inspected benchmark question')
        spans=row.get('gold_spans')
        if not isinstance(spans,list) or not spans:
            raise ValueError('Labeled case must contain nonempty gold_spans')
        gold_ids=set()
        for span in spans:
            if not isinstance(span,dict) or set(span)!={'id','path','start_line','end_line'}:
                raise ValueError('Gold span must contain ID, path, start_line, end_line only')
            sid=span.get('id');path=_path(span.get('path'))
            lo=span.get('start_line');hi=span.get('end_line')
            if not isinstance(sid,str) or not sid or sid in gold_ids:
                raise ValueError('Invalid or duplicate gold span ID')
            gold_ids.add(sid)
            if type(lo) is not int or type(hi) is not int or lo<1 or hi<lo:
                raise ValueError('Invalid gold span line range')
            if hi-lo+1>160:
                raise ValueError('Gold span length exceeds auditable bound')
            raw=repo.read_file(path,lo,hi)
            observed=[int(m.group(1)) for line in raw.splitlines()
                      if (m:=_NUMBERED.match(line))]
            if observed!=list(range(lo,hi+1)):
                raise ValueError(f'Gold span not present at pinned source: {ident}:{sid}')
            links.append({'case_id':ident,'gold_id':sid,
                          'source':f'https://github.com/{repository}/blob/{commit}/{path}#L{lo}-L{hi}',
                          'source_lines':len(observed)})
            span_count+=1
    return {'case_count':len(labels),'gold_span_count':span_count,
            'review_links':links,
            'review_status':'coordinates_verified_not_semantics_reviewed',
            'notes':['Coordinates are checked against pinned source lines.',
                     'Reviewer must independently confirm span relevance.',
                     'Labeled data must not be passed to candidate generation.']}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--questions-jsonl',type=Path,required=True)
    p.add_argument('--labels-jsonl',type=Path,required=True)
    p.add_argument('--checkout',type=Path,required=True)
    p.add_argument('--repository',required=True)
    p.add_argument('--commit',required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args(argv)
    known=ROOT/'benchmark'/'datasets'/'benchmark_30.jsonl'
    for f in (args.questions_jsonl,args.labels_jsonl,known):
        if not f.is_file():p.error('Missing input file: '+str(f))
    if args.out.exists():p.error('Refusing to overwrite validation report: '+str(args.out))
    questions=read_questions(args.questions_jsonl,repository=args.repository,commit=args.commit)
    checkout=_validate_checkout(args.checkout,args.repository,args.commit)
    report=validate_labels(Repo(checkout),questions,_read_jsonl(args.labels_jsonl),
                           _read_jsonl(known),repository=args.repository,commit=args.commit)
    report['inputs_sha256']={'questions':hashlib.sha256(args.questions_jsonl.read_bytes()).hexdigest(),
                             'labels':hashlib.sha256(args.labels_jsonl.read_bytes()).hexdigest()}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'case_count':report['case_count'],
                      'gold_span_count':report['gold_span_count'],
                      'review_status':report['review_status'],
                      'report':str(args.out)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
