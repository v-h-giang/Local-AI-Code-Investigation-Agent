"""Compact local Knowledge Base context for the existing Qwen investigation plan.

No new LLM calls, no project code execution, and no gold file labels. KB
descriptions and repository metadata are UNTRUSTED navigation hints, never
source citations. A missing database yields an empty context.
"""
from __future__ import annotations
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from knowledge_base import database_path

_COMMON=frozenset("where when what which why how does are can could should would the and "
                  "with from about that this these those into code source repo repository "
                  "file files method class function implementation example explain "
                  "find locate show which them their they our your some have does there "
                  "implemented work working works possible used using".split())

def _tokens(value):
    return {token for token in re.findall(r"[a-z][a-z0-9_]{2,}",str(value).casefold())
            if token not in _COMMON}

def _overlap(query_words, text_words):
    score=0
    for q in query_words:
        if q in text_words:
            score+=4
        elif len(q)>=5 and any(
            t.startswith(q[:5]) or q.startswith(t[:5]) for t in text_words if len(t)>=5):
            score+=1
    return score

def kb_prompt_context(question, repo=None, *, max_chars=2300, concept_limit=18):
    """Select a bounded, domain-diverse context for semantic Qwen planning.

    Unlike exact alias lookup, selection also uses token overlap and a
    deterministic broad fallback catalog. The LLM may infer related technical
    concepts using its own knowledge; KB is a guide, not a strict vocabulary.
    """
    limit=max(300,min(4000,int(max_chars)))
    path=database_path()
    ranked=[]
    if path.is_file():
        try:
            with closing(sqlite3.connect(path)) as conn:
                rows=conn.execute(
                    "SELECT c.concept_id,c.domain,c.label,c.description,"
                    "GROUP_CONCAT(a.normalized,' | ') AS aliases "
                    "FROM concepts c LEFT JOIN aliases a ON c.concept_id=a.concept_id "
                    "GROUP BY c.concept_id,c.domain,c.label,c.description "
                    "ORDER BY c.concept_id"
                ).fetchall()
            q=_tokens(question)
            for cid,domain,label,description,aliases in rows:
                core=_tokens(label+" "+(aliases or ""))
                description_tokens=_tokens(description)
                score=2*_overlap(q,core)+_overlap(q,description_tokens)
                ranked.append((score,str(cid),str(domain),str(label),
                               str(description)))
        except (OSError,sqlite3.Error,ValueError,UnicodeError):
            ranked=[]
    ranked.sort(key=lambda x:(-x[0],x[2],x[1]))
    high=[r for r in ranked if r[0]>0]
    selected=[];seen=set()
    for row in high[:max(1,min(concept_limit,24))]:
        selected.append(row);seen.add(row[1])
    # When no exact match, show a broad, domain-diverse glossary to let the
    # model connect intent to terminology that the user didn't explicitly use.
    if len(selected)<max(6,min(12,concept_limit)):
        by_domain={}
        for row in ranked:
            if row[1] in seen:continue
            by_domain.setdefault(row[2],[]).append(row)
        for round_id in range(3):
            for domain in sorted(by_domain):
                group=by_domain[domain]
                if len(group)>round_id and len(selected)<min(concept_limit,18):
                    row=group[round_id]
                    selected.append(row);seen.add(row[1])
    lines=[]
    if selected:
        lines.append("General programming concepts (hints, NOT repository evidence):")
        for score,cid,domain,label,description in selected:
            desc=(" — "+description[:110]) if score>=4 else ""
            lines.append(f"- {cid} [{domain}]: {label}{desc}")
    technologies=[]
    if repo is not None:
        index=getattr(repo,"intelligence_db",None)
        if index is not None and Path(index).is_file():
            try:
                with closing(sqlite3.connect(index)) as conn:
                    technologies=conn.execute(
                        "SELECT language,SUM(file_count) FROM module_profiles "
                        "GROUP BY language ORDER BY SUM(file_count) DESC LIMIT 8"
                    ).fetchall()
            except (sqlite3.Error,OSError,ValueError):
                technologies=[]
    if technologies:
        lines.append("Detected repository languages (file metadata only): "+
                     ", ".join(f"{language}={n}" for language,n in technologies))
    content="\n".join(lines)
    # Never send a partially truncated concept record to the model.
    bounded=[]
    used=0
    for line in content.splitlines():
        if used+len(line)+1>limit:
            break
        bounded.append(line);used+=len(line)+1
    return "\n".join(bounded)
