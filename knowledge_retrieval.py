"""Bounded concept-assisted source discovery, independent from benchmark labels.

Every path comes from the repository's own SQLite index. Concept, symbol,
and graph matches are navigation signals, never source line citations.
"""
from __future__ import annotations

import re
from collections import defaultdict

# Short or overly generic words must not turn KB expansion into a broad OR.
_NON_DISCRIMINATIVE = frozenset((
    "data", "code", "file", "files", "class", "type", "types",
    "system", "logic", "application", "project", "source", "using",
    "model", "models", "service", "services", "function", "method",
    "object", "runtime", "process", "worker", "example", "test",
    "tests", "run", "work", "working", "flow", "state", "program",
    "module", "modules", "value", "values", "response", "request",
    "result", "results", "input", "output", "create", "update",
    "load", "store", "save", "get", "set", "make",
))


def safe_knowledge_terms(raw_terms, original_words, limit=6):
    """Select precise single-token KB synonyms not already in the question."""
    original={str(word).casefold() for word in original_words}
    result=[]
    for item in raw_terms:
        term=str(item).casefold().strip()
        # No SQL wildcards, punctuation, FTS operators, or unbounded terms.
        if (len(term)<5 or len(term)>40 or term in original
                or term in _NON_DISCRIMINATIVE
                or not re.fullmatch(r"[a-z][a-z0-9]*",term)):
            continue
        if term not in result:
            result.append(term)
        if len(result)>=max(0,min(int(limit),8)):
            break
    return result


def discover_concept_paths(conn, terms, *, max_per_term=180):
    """Separate BM25 search per KB term plus indexed symbol-name lookup.

    Crucially, these file paths do not need to match the user's original
    words. Global FTS expansion is never mixed with the original query OR,
    which avoids letting a common synonym suppress strong original matches.
    """
    found=defaultdict(lambda: {"fts":set(),"symbols":set()})
    for term in terms[:8]:
        # FTS5 quoted single-token query, not user-controlled FTS operators.
        expression='"'+term+'"'
        for (path,) in conn.execute(
            "SELECT path FROM search_fts WHERE search_fts MATCH ? "
            "ORDER BY bm25(search_fts) LIMIT ?",
            (expression,max(1,min(400,int(max_per_term))))):
            found[path]["fts"].add(term)
        # Symbol names commonly use CamelCase or snake_case, so FTS may not
        # tokenize the relevant concept out of a declaration name.
        for path,name in conn.execute(
            "SELECT path,name FROM symbols WHERE lower(name) LIKE ? LIMIT 120",
            ("%"+term+"%",)):
            found[path]["symbols"].add(term)
    return dict(found)


def related_source_paths(conn, seed_paths, *, max_links=90):
    """One-hop source graph navigation from already ranked file leads.

    Support file:file relations and symbol relations whose source location is
    known. Graph edges remain static/heuristic and do not prove runtime calls.
    """
    seeds=list(dict.fromkeys(seed_paths))[:12]
    if not seeds:
        return {}
    neighbors=defaultdict(set)
    file_ids=["file:"+p for p in seeds]
    placeholders=",".join("?" for _ in file_ids)
    sql=(
        "SELECT src,dst FROM relations "
        f"WHERE src IN ({placeholders}) OR dst IN ({placeholders}) LIMIT ?"
    )
    for src,dst in conn.execute(sql,(*file_ids,*file_ids,max_links)):
        if not isinstance(src,str) or not isinstance(dst,str):
            continue
        if not src.startswith("file:") or not dst.startswith("file:"):
            continue
        a,b=src[5:],dst[5:]
        if a in seeds and b!=a:
            neighbors[b].add(a)
        if b in seeds and a!=b:
            neighbors[a].add(b)
    # Resolved symbol-call candidates are indexed separately from file links.
    # Only traverse edges whose declaring file belongs to the seed set.
    path_holders=",".join("?" for _ in seeds)
    symbol_sql=(
        "SELECT r.path,s.path FROM relations r JOIN symbols s ON s.id=r.dst "
        f"WHERE r.path IN ({path_holders}) AND r.kind='calls-candidate' "
        "LIMIT ?"
    )
    for source,target in conn.execute(symbol_sql,(*seeds,max_links)):
        if source in seeds and target!=source:
            neighbors[target].add(source)
    return dict(neighbors)
