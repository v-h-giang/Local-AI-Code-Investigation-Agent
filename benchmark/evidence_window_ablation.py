"""P1.6 source-backed prefetch A/B at equal character budgets (offline).

Compares exact existing acquire_evidence() baseline with deterministic
reserved-character 1/2-window experimental variants. Reads actual pinned
source only; never executes repository code or invokes Ollama. Candidate
windows come from the previously saved gold-blind retrieval ablation.
Gold spans are consulted ONLY after prefetch excerpts have been produced.

This is a PREFETCH excerpt test, NOT a simulated agent/LLM answer.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from benchmark import run
from benchmark.top8_multiwindow_diagnostics import window, extra_lines
from codebase import Repo
from context_compression import compress
from evidence_acquisition import acquire_evidence

_NUMBERED=re.compile(r'^\s*(\d+)\s+\|\s')
_MODES=(0,1,2)


def _size(value):
    return len(json.dumps(value,ensure_ascii=False))


def _source_excerpt(repo, candidate, question, char_limit):
    """Read real, bounded source lines and produce their exact citable subset."""
    part=window(candidate)
    if part is None:
        return None
    path,start,end=part
    if char_limit<200:
        return None
    try:
        source=repo.read_file(path,start,end)
    except (OSError,ValueError,TypeError,KeyError):
        return None
    numbered=[]
    for raw in source.splitlines():
        match=_NUMBERED.match(raw)
        if match:
            number=int(match.group(1))
            if start<=number<=end:
                numbered.append((number,raw))
    if not numbered:
        return None
    result=compress(path,numbered,question,char_limit,mode='structure_mmr')
    if not result:
        return None
    visible={f'{path}:{line}' for line,_ in numbered}
    references=result.get('source_refs') or []
    if (not isinstance(references,list)
            or any(ref not in visible for ref in references)):
        raise ValueError('Evidence compressor returned unobserved source refs')
    # Only actual, displayed complete source lines may support a citation.
    in_content={f'{path}:{int(m.group(1))}' for raw in result.get('content','').splitlines()
                if (m:=_NUMBERED.match(raw))}
    if any(ref not in in_content for ref in references):
        raise ValueError('Evidence compressor refs not displayed in excerpt')
    result=dict(result)
    result['prefetch_window_origin']='dense-alternate'
    result['prefetch_window']=[start,end]
    return result


def acquire_prefetch_variants(repo, saved_case, *, max_chars=3000,
                              per_window_chars=500, limit=6):
    """Produce comparable outputs before looking at any benchmark gold spans."""
    if max_chars<1000 or not 200<=per_window_chars<=max_chars//3:
        raise ValueError('Invalid character budget')
    question=saved_case['question']
    hybrid=((saved_case.get('variants') or {}).get('hybrid') or {})
    candidates=hybrid.get('top8_diagnostics')
    if not isinstance(candidates,list) or len(candidates)>8:
        raise ValueError('Saved Hybrid top8 diagnostics missing')
    all_paths={row.get('path') for row in candidates}
    multi=saved_case.get('multiwindow_diagnostics') or {}
    choices=multi.get('alternates')
    if not isinstance(choices,list) or len(choices)>4:
        raise ValueError('Saved selected multiwindow choices missing')

    original=[part for row in candidates if (part:=window(row)) is not None]
    if len(original)!=len(candidates):
        raise ValueError('Invalid Hybrid original source window')
    validated=list(original)
    for candidate in choices:
        part=window(candidate)
        if part is None or part[0] not in all_paths:
            raise ValueError('Alternate is outside Hybrid top8 files')
        added=extra_lines(part,validated)
        if added<8 or added!=candidate.get('new_lines'):
            raise ValueError('Saved alternate has invalid new line count')
        validated.append(part)

    variants={}
    for budget in _MODES:
        selected=choices[:budget]
        reserved=len(selected)*per_window_chars
        original_budget=max_chars-reserved
        base=acquire_evidence(
            repo,candidates,question,max_chars=original_budget,
            limit=limit,mode='structure_mmr',llm=None)
        # Each reserved slot has an independent cap and baseline excerpts
        # are never silently sliced or replaced.
        excerpts=list(base)
        accepted=0
        read_errors=0
        for candidate in selected:
            try:
                excerpt=_source_excerpt(repo,candidate,question,per_window_chars)
            except ValueError:
                # A provenance mismatch must fail rather than silently pass.
                raise
            if excerpt is None:
                read_errors+=1
                continue
            if _size(excerpts+[excerpt])>max_chars:
                read_errors+=1
                continue
            excerpts.append(excerpt)
            accepted+=1
        if _size(excerpts)>max_chars:
            raise RuntimeError('Total evidence budget exceeded')
        variants[str(budget)]={
            'excerpts':excerpts,
            'excerpt_count':len(excerpts),
            'alternate_windows_requested':len(selected),
            'alternate_windows_emitted':accepted,
            'alternate_windows_skipped':read_errors,
            'serialized_chars':_size(excerpts),
            'budget_chars':max_chars,
            'base_reserved_chars':reserved,
        }
    return variants


def _span_ids_from_refs(gold, excerpts, key):
    """Gold-span hit only if an actual displayed source line intersects it."""
    refs=set()
    for excerpt in excerpts:
        for ref in excerpt.get(key) or []:
            if not isinstance(ref,str):
                continue
            path,_,line=ref.rpartition(':')
            if line.isdecimal():
                refs.add((path,int(line)))
    return sorted({
        span.get('id',str(i+1))
        for i,span in enumerate(gold)
        if any(path==span['path']
               and span['start_line']<=line<=span['end_line']
               for path,line in refs)
    })


def evaluate_case(repo, saved_case, source_case, *,
                  max_chars=3000, per_window_chars=500, limit=6):
    if saved_case['id']!=source_case['id'] or (
            saved_case['question']!=source_case['question']):
        raise ValueError('Pinned case metadata differs from saved report')
    variants=acquire_prefetch_variants(
        repo,saved_case,max_chars=max_chars,
        per_window_chars=per_window_chars,limit=limit)
    # Gold is read AFTER all source excerpts and windows are chosen.
    gold=source_case.get('gold_spans') or []
    metrics={}
    for budget in _MODES:
        prefetch=variants[str(budget)]
        excerpts=prefetch.pop('excerpts')
        visible=_span_ids_from_refs(gold,excerpts,'visible_refs')
        citeable=_span_ids_from_refs(gold,excerpts,'source_refs')
        if not set(citeable)<=set(visible):
            raise ValueError('Citable gold spans not present in visible source')
        metrics[str(budget)]={**prefetch,
            'gold_spans_visible':len(visible),
            'gold_spans_citable':len(citeable),
            'gold_visible_ids':visible,
            'gold_citable_ids':citeable,
            'displayed_source_lines':sum(
                len(x.get('visible_refs') or []) for x in excerpts),
            'citable_source_lines':sum(
                len(x.get('source_refs') or []) for x in excerpts),
        }
    return {'id':source_case['id'],'gold_spans':len(gold),
            'variants':metrics}


def analyze(saved, benchmark_cases, repo, *, max_chars=3000,
            per_window_chars=500,limit=6):
    if not isinstance(saved.get('cases'),list) or not saved['cases']:
        raise ValueError('Missing saved multiwindow cases')
    expected={case['id']:case for case in benchmark_cases
              if case['suite']==saved['suite']}
    seen=set()
    cases=[]
    for row in saved['cases']:
        if row['id'] in seen:
            raise ValueError('Duplicate saved case ID')
        seen.add(row['id'])
        source=expected.get(row['id'])
        if source is None:
            raise ValueError('Case ID absent from pinned benchmark')
        cases.append(evaluate_case(repo,row,source,
            max_chars=max_chars,per_window_chars=per_window_chars,limit=limit))
    budgets={}
    for budget in _MODES:
        name=str(budget)
        rows=[case['variants'][name] for case in cases]
        budgets[name]={
            'gold_spans_visible':sum(r['gold_spans_visible'] for r in rows),
            'gold_spans_citable':sum(r['gold_spans_citable'] for r in rows),
            'cases_with_visible_gold':sum(r['gold_spans_visible']>0 for r in rows),
            'cases_with_citable_gold':sum(r['gold_spans_citable']>0 for r in rows),
            'alternate_windows_requested':sum(r['alternate_windows_requested'] for r in rows),
            'alternate_windows_emitted':sum(r['alternate_windows_emitted'] for r in rows),
            'alternate_windows_skipped':sum(r['alternate_windows_skipped'] for r in rows),
            'serialized_chars':sum(r['serialized_chars'] for r in rows),
            'displayed_source_lines':sum(r['displayed_source_lines'] for r in rows),
            'citable_source_lines':sum(r['citable_source_lines'] for r in rows),
        }
    baseline=budgets['0']
    for row in budgets.values():
        row['delta_visible_vs_baseline']=row['gold_spans_visible']-baseline['gold_spans_visible']
        row['delta_citable_vs_baseline']=row['gold_spans_citable']-baseline['gold_spans_citable']
    # Per-case regressions matter even when aggregate recall increases.
    for name in ('1','2'):
        budgets[name]['cases_losing_visible_gold']=sum(
            bool(set(case['variants']['0']['gold_visible_ids'])-
                 set(case['variants'][name]['gold_visible_ids']))
            for case in cases)
        budgets[name]['cases_losing_citable_gold']=sum(
            bool(set(case['variants']['0']['gold_citable_ids'])-
                 set(case['variants'][name]['gold_citable_ids']))
            for case in cases)
        budgets[name]['cases_gaining_visible_gold']=sum(
            bool(set(case['variants'][name]['gold_visible_ids'])-
                 set(case['variants']['0']['gold_visible_ids']))
            for case in cases)
        budgets[name]['cases_gaining_citable_gold']=sum(
            bool(set(case['variants'][name]['gold_citable_ids'])-
                 set(case['variants']['0']['gold_citable_ids']))
            for case in cases)
    return {
        'summary':{
            'case_count':len(cases),
            'gold_spans_total':sum(c['gold_spans'] for c in cases),
            'per_case_total_char_budget':max_chars,
            'alternate_window_char_cap':per_window_chars,
            'prefetch_file_limit':limit,
            'budgets':budgets,
        },
        'cases':cases,
        'limitations':[
            'Actual pinned source text is read but there is NO agent or LLM call.',
            'Only source lines in returned extracts are counted, not candidate overlap.',
            'Gold labels are consulted after candidate selection and extraction.',
            'Budget is serialized JSON characters; not precise model token count.',
            'Experimental budgets reserve characters from baseline prefetch.',
            'This is not final-answer quality or actual model citation validity.',
            'All results are exploratory on an already inspected 20-case dataset.',
        ],
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--from-report',type=Path,required=True)
    p.add_argument('--max-chars',type=int,default=3000)
    p.add_argument('--per-window-chars',type=int,default=500)
    p.add_argument('--limit',type=int,default=6)
    p.add_argument('--out',type=Path)
    args=p.parse_args(argv)
    if not args.from_report.is_file():
        p.error('Saved multiwindow report missing')
    saved=json.loads(args.from_report.read_text(encoding='utf-8'))
    suite=saved.get('suite')
    if suite not in run.REPOS:
        p.error('Unknown benchmark suite')
    if (saved.get('method') or {}).get('frozen_source_commit')!=run.REPOS[suite][1]:
        p.error('Saved benchmark source commit mismatch')
    checkout=run.CACHES/run.REPOS[suite][2]
    if not checkout.is_dir():
        p.error('Pinned source checkout missing: '+str(checkout))
    if run.git('rev-parse','HEAD',cwd=checkout)!=run.REPOS[suite][1]:
        p.error('Pinned source checkout revision mismatch')
    result=analyze(saved,run.read_cases(),Repo(checkout),
                   max_chars=args.max_chars,
                   per_window_chars=args.per_window_chars,
                   limit=args.limit)
    result['suite']=suite
    result['from_report']=str(args.from_report)
    out=args.out or (run.RESULTS/'_diagnostics'/'evidence_window_ablation.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',
                   encoding='utf-8')
    print(json.dumps({'summary':result['summary'],'report':str(out)},
                     ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    sys.exit(main())
