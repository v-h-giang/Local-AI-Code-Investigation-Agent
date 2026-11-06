"""Build gold-blind Hybrid/Dense candidate windows for a new pinned repository.

Question-only input is accepted. Retrieval uses existing FTS5, Qwen3 embeddings,
and RRF implementations. Candidate coordinates are never synthesized from labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codebase import Repo
from code_intelligence import search_file_candidates, search_relevant_sources, search_file_locations
from benchmark.heldout_evidence_eval import _validate_checkout, _path, _question
from benchmark.top8_multiwindow_diagnostics import select_from_dense_windows
from semantic_retrieval import OllamaEmbedder, _rrf, dense_search

_SHA = re.compile(r'^[0-9a-f]{40}$')
_NUMBERED = re.compile(r'^\s*(\d+)\s+\|\s')


def read_questions(path, *, repository, commit):
    if not _SHA.fullmatch(commit):
        raise ValueError('A pinned 40-hex source SHA is required')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Repository must be owner/name')
    questions = []
    ids, prompts = set(), set()
    for lineno, raw in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        if not isinstance(row, dict):
            raise ValueError(f'Question line {lineno} must be an object')
        # A strict whitelist isolates retrieval from answer keys and any
        # explanatory fields accidentally attached to a question record.
        if set(row) != {'id', 'suite', 'repo', 'commit', 'question'}:
            raise ValueError('Question manifest has unexpected fields at line '+str(lineno))
        if not isinstance(row['id'], str) or not row['id'] or row['id'] in ids:
            raise ValueError('Duplicate or invalid question ID')
        if not isinstance(row['suite'], str) or not row['suite']:
            raise ValueError('Invalid suite')
        if row['repo'] != repository or row['commit'] != commit:
            raise ValueError('Question repository or commit mismatch')
        norm = _question(row['question'])
        if norm in prompts:
            raise ValueError('Duplicate question')
        ids.add(row['id']); prompts.add(norm)
        questions.append(row)
    if not questions or len({row['suite'] for row in questions}) != 1:
        raise ValueError('Questions must form one nonempty suite')
    return questions


def _window_for_candidate(repo, row, question):
    if not isinstance(row, dict):
        return None
    path = _path(row.get('path'))
    lo = row.get('line_start', row.get('start_line'))
    hi = row.get('line_end', row.get('end_line'))
    if type(lo) is not int or type(hi) is not int or lo < 1 or hi < lo:
        hint = row.get('line_hint', row.get('line'))
        if type(hint) is not int or hint < 1:
            locations = search_file_locations(repo, path, question, limit=1)
            hint = locations[0]['line'] if locations else 1
        if type(hint) is not int or hint < 1:
            hint = 1
        lo, hi = max(1, hint-12), hint+35
    elif lo == hi:
        lo, hi = max(1, lo-12), lo+35
    hi = min(hi, lo+47)
    # Confirm the proposed span reads a numbered line in the checked-out
    # repository. Read-only source validation, not a relevance judgment.
    raw = repo.read_file(path, lo, hi)
    if not any(_NUMBERED.match(line) for line in raw.splitlines()):
        return None
    return {'path':path, 'line_start':lo, 'line_end':hi}


def build_report(repo, questions, db, embedder):
    results = []
    for row in questions:
        query = row['question']
        files = search_file_candidates(repo, query, limit=40, strategy='v59')
        hits = search_relevant_sources(repo, query, limit=30)
        dense, windows_by_path = dense_search(
            repo, query, db, embedder, limit=60, per_file=1,
            collect_windows_per_file=3)
        hybrid = _rrf([('filename',1.0,files),('fts-line',1.1,hits),
                       ('dense',1.4,dense)], limit=30)
        head = []
        paths = set()
        for candidate in hybrid:
            item = _window_for_candidate(repo, candidate, query)
            if item is None or item['path'] in paths:
                continue
            paths.add(item['path'])
            head.append(item)
            if len(head) == 8:
                break
        if not head:
            raise ValueError('No source-backed candidates for '+row['id'])
        alternates = select_from_dense_windows(head, windows_by_path,
                                                max_extra=4, min_new_lines=8)
        # Neither the retrieval ranks nor the output contain gold labels.
        results.append({
            'id':row['id'], 'question':query,
            'variants':{'hybrid':{'top8_diagnostics':head}},
            'multiwindow_diagnostics':{'alternates':[
                {key: item[key] for key in ('path','start_line','end_line','new_lines')}
                for item in alternates]},
        })
    return {
        'suite':questions[0]['suite'], 'repo':questions[0]['repo'],
        'method':{
            'frozen_source_commit':questions[0]['commit'],
            'candidate_generation':'v59 file FTS + source FTS + Qwen3 dense RRF',
            'retrieval_ranked_views':'filename:1.0, fts-line:1.1, dense:1.4',
            'dense_windows_per_file':3,
            'gold_input':'question-only manifest',
            'embedding_model':getattr(embedder,'model','unspecified'),
        },
        'cases':results,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--questions-jsonl',type=Path,required=True)
    p.add_argument('--checkout',type=Path,required=True)
    p.add_argument('--repository',required=True)
    p.add_argument('--commit',required=True)
    p.add_argument('--intelligence-index',type=Path,required=True)
    p.add_argument('--embed-db',type=Path,required=True)
    p.add_argument('--model',default='qwen3-embedding:0.6b')
    p.add_argument('--host',default='http://127.0.0.1:11434')
    p.add_argument('--dimensions',type=int,default=1024)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args(argv)
    for file in (args.questions_jsonl,args.intelligence_index,args.embed_db):
        if not file.is_file():
            p.error('Missing input file: '+str(file))
    if args.out.exists():
        p.error('Refusing to overwrite candidate report: '+str(args.out))
    questions=read_questions(args.questions_jsonl,repository=args.repository,
                             commit=args.commit)
    checkout=_validate_checkout(args.checkout,args.repository,args.commit)
    repo=Repo(checkout)
    repo.intelligence_db=args.intelligence_index.resolve()
    embedding=OllamaEmbedder(args.model,args.host,args.dimensions)
    report=build_report(repo,questions,args.embed_db.resolve(),embedding)
    report['inputs']={
        'questions_sha256':hashlib.sha256(args.questions_jsonl.read_bytes()).hexdigest(),
        'intelligence_sha256':_sha_file(args.intelligence_index),
        'embedding_sha256':_sha_file(args.embed_db),
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'case_count':len(report['cases']),
                      'hybrid_windows':sum(len(r['variants']['hybrid']['top8_diagnostics']) for r in report['cases']),
                      'dense_alternates':sum(len(r['multiwindow_diagnostics']['alternates']) for r in report['cases']),
                      'report':str(args.out)},ensure_ascii=False,indent=2))


def _sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


if __name__=='__main__':
    main()
