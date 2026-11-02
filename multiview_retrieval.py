"""Experimental V5.13 multi-view file and line retrieval.

Independent lexical candidate, indexed-line, and Qwen-plan query views are
fused without benchmark labels. File paths are navigation hints; line hints
come exclusively from the indexed source table. Standard library only.
"""
from __future__ import annotations

from collections import defaultdict
import re

def _safe_queries(question, plan_queries=()):
    result=[]
    for query in (question, *(plan_queries or ())):
        if not isinstance(query,str) or not query.strip() or len(query)>700:
            continue
        if any(ord(c)<32 or ord(c)==127 for c in query):
            continue
        if query.strip().lower() not in {x.lower() for x in result}:
            result.append(query.strip())
        if len(result)>=4:
            break
    return result


def fuse_views(views, limit=12, k=40):
    """Weighted RRF over INDEPENDENT, ranked retrieval views.

    Each view is (name, weight, rows). A duplicate file inside a view is
    counted once, avoiding popular files with many matching lines dominating.
    Weights reflect view type, never benchmark labels. Tie-break is stable.
    """
    scores=defaultdict(float)
    details={}
    sources=defaultdict(set)
    hints=defaultdict(list)
    for name,weight,rows in views:
        seen=set()
        for rank,row in enumerate(rows,1):
            if not isinstance(row,dict):
                continue
            path=row.get('path')
            if not isinstance(path,str) or not path or path in seen:
                continue
            seen.add(path)
            scores[path]+=float(weight)/(k+rank)
            sources[path].add(name)
            details.setdefault(path,row)
            line=row.get('line')
            if isinstance(line,int) and line>0:
                hints[path].append((rank,line,str(row.get('excerpt',''))[:160]))
    ranked=sorted(scores,key=lambda path:(-scores[path],-len(sources[path]),path))
    output=[]
    for path in ranked[:max(1,min(50,int(limit)))]:
        original=details[path]
        item={'path':path,'path_score':round(scores[path]*1000,4),
              'kind':'multiview-file-candidate',
              'file_role':original.get('file_role','other'),
              'citation':False,
              'candidate_origin':'multiview-rrf',
              'retrieval_views':sorted(sources[path])}
        if hints[path]:
            _,line,excerpt=min(hints[path])
            item['line_hint']=line
            item['line_hint_excerpt']=excerpt
            item['line_hint_source']='indexed-source-fts'
        output.append(item)
    return output


def retrieve_multiview(repo,question,plan_queries=(),limit=12):
    """Fuse independent FTS/file views; no generation calls or writes.

    This is a bounded opt-in experiment. A line hint is NOT a citation until
    the agent reads and validates real source text.
    """
    from code_intelligence import search_file_candidates, search_relevant_sources
    queries=_safe_queries(question,plan_queries)
    if not queries:
        return []
    views=[]
    for i,query in enumerate(queries):
        # One broad OR query cannot starve every independent search view.
        # Keep file discovery and line retrieval separate and complementary.
        files=search_file_candidates(repo,query,limit=32,
                                     strategy='v59' if i==0 else 'baseline')
        lines=search_relevant_sources(repo,query,limit=24)
        views.append((f'file:{i}',1.0 if i==0 else 0.8,files))
        views.append((f'line:{i}',1.15 if i==0 else 1.0,lines))
    return fuse_views(views,limit=limit)
