"""Experimental V5.10 source-evidence fusion, independent of benchmark labels.

The first eight candidates are copied verbatim from the deterministic baseline.
Only the remaining window is diversified using KB aliases, symbol declarations,
one-hop static source graph and matching source paths. Nothing here is a citation.
This experiment is opt-in until unseen-data recall and latency have been measured.
"""
from __future__ import annotations
from collections import defaultdict
from contextlib import closing
from pathlib import Path
import re
import sqlite3

from knowledge_base import expand_query_terms
from knowledge_retrieval import safe_knowledge_terms, discover_concept_paths, related_source_paths

_COMMON = frozenset({
    "from","with","where","what","when","which","this","that","these",
    "those","would","could","should","about","into","does","your",
    "there","their","using","used","code","source","files","file",
    "method","methods","class","classes","function","functions","agent",
    "agents","implement","implemented","implementation","example","examples",
    "system","project","results","result","output","input","where","show",
    "explain","find","locate","need","want","work","works","working",
    "request","response","task","tasks","run","running","how","for",
    "does","have","been","user","into","some","only",
})

def _tokens(value):
    separated=re.sub(r"([a-z0-9])([A-Z])",r"\1 \2",str(value))
    separated=re.sub(r"([A-Z])([A-Z][a-z])",r"\1 \2",separated)
    return set(re.findall(r"[a-z0-9]+",separated.lower()))

def _role(path):
    low=path.lower().replace("\\","/")
    if "/tests/" in low or low.startswith("tests/"):
        return "test"
    if low.endswith(".md"):
        return "documentation"
    if "/samples/" in low:
        return "sample"
    if "/src/" in low or "/packages/" in low:
        return "implementation"
    return "other"

def fusion_exploration(repo, question, baseline, *, limit=20):
    """Return new KB/path/graph leads, independently ranked and deduplicated.

    Candidates must have a meaningful source signal; aliases alone are not
    enough if there is no corresponding path, FTS text or symbol match.
    """
    words={w for w in _tokens(question) if len(w)>=4 and w not in _COMMON}
    knowledge_terms=safe_knowledge_terms(
        expand_query_terms(question,max_terms=6),words,limit=6)
    seed_paths=[r["path"] for r in baseline[:12]]
    indexed=getattr(repo,"intelligence_db",None)
    if indexed is None or not Path(indexed).is_file():
        return []
    with closing(sqlite3.connect(indexed)) as conn:
        kb=discover_concept_paths(conn,knowledge_terms) if knowledge_terms else {}
        graph=related_source_paths(conn,seed_paths,max_links=150)
        paths=[row[0] for row in conn.execute("SELECT path FROM files")]

    baseline_paths={r["path"] for r in baseline}
    base_groups={r["path"].split("/",2)[0] for r in baseline[:8]}
    docs_requested=bool(re.search(
        r"\b(?:documentation|documented|readme|guide|guides|examples?)\b",
        question,re.I))
    scored=[]
    for path in paths:
        if path in baseline_paths:
            continue
        pwords=_tokens(path)
        technical=pwords & words
        kb_path=pwords & set(knowledge_terms)
        evidence=kb.get(path)
        has_graph=path in graph
        symbol=set(evidence["symbols"]) if evidence else set()
        fts=set(evidence["fts"]) if evidence else set()
        # Single generic path term cannot admit a file on its own.
        if not (has_graph or symbol or fts or len(technical)>=2 or kb_path):
            continue
        score=(6*min(3,len(technical))+
               8*min(2,len(kb_path))+
               4*min(3,len(fts))+
               8*min(2,len(symbol))+
               6*min(2,len(graph.get(path,()))))
        if path.split("/",2)[0] in base_groups:
            score+=3
        role=_role(path)
        if role=="documentation":
            score+=5 if docs_requested else -5
        elif role=="test":
            score-=2
        if path.lower().startswith((".github/","docs/decisions/")):
            score-=12
        if score<=0:
            continue
        scored.append({
            "path":path,
            "path_score":score,
            "match_terms":sorted(technical),
            "content_terms":[],
            "kind":"hybrid-file-candidate",
            "file_role":role,
            "citation":False,
            "knowledge_path_terms":sorted(kb_path),
            "kb_fts_terms":sorted(fts),
            "kb_symbol_terms":sorted(symbol),
            "graph_neighbors":sorted(graph.get(path,())),
            "candidate_origin":"v510-exploration",
        })
    scored.sort(key=lambda r:(-r["path_score"],-len(r["kb_symbol_terms"]),
                              len(r["path"]),r["path"]))
    # Diversify source folders; do not spend all exploration slots on one family.
    result=[];groups=defaultdict(int)
    for row in scored:
        folder=row["path"].rsplit("/",1)[0] if "/" in row["path"] else "."
        if groups[folder]>=2:
            continue
        result.append(row)
        groups[folder]+=1
        if len(result)>=max(12,min(80,limit*3)):
            break
    return result

def fuse_baseline_exploration(baseline, exploration, *, limit=20):
    """Reserve up to four slots in 9..20 for independent new paths.

    This *may* improve top-20 recall but is not guaranteed to do so.
    It never changes the first eight baseline paths for the same limit.
    """
    limit=max(1,min(50,int(limit)))
    protected=list(baseline[:min(8,limit)])
    if len(protected)>=limit:
        return protected
    seen={r["path"] for r in protected}
    tail=[r for r in baseline if r["path"] not in seen]
    novel=[r for r in exploration if r["path"] not in
           {r["path"] for r in baseline}]
    slots=min(4,(limit-len(protected))//3,len(novel))
    output=list(protected)
    # Alternate two baseline leads and one exploratory lead in the tail,
    # then fill from original baseline order. Never rank with benchmark gold.
    ti=0;ei=0
    while len(output)<limit and (ti<len(tail) or ei<slots):
        for _ in range(2):
            if len(output)>=limit or ti>=len(tail):
                break
            row=tail[ti];ti+=1
            if row["path"] not in seen:
                output.append(row);seen.add(row["path"])
        if len(output)<limit and ei<slots:
            row=novel[ei];ei+=1
            if row["path"] not in seen:
                output.append(row);seen.add(row["path"])
    for row in tail:
        if len(output)>=limit:break
        if row["path"] not in seen:
            output.append(row);seen.add(row["path"])
    for row in novel[ei:]:
        if len(output)>=limit:break
        if row["path"] not in seen:
            output.append(row);seen.add(row["path"])
    return output
