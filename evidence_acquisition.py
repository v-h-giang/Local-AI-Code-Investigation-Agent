"""Deterministic, citation-safe compression of retrieved source passages.

This is extractive compression, not LLM-generated summarization: every
citation corresponds to a complete, actually displayed source line.
"""
from __future__ import annotations

import json
import re


_STOP = {'what','where','which','when','does','with','from','that','this',
         'into','about','using','would','should','could','there','these',
         'file','code','function','source','implement','implemented'}
_DECL = re.compile(r'\b(?:def|class|subroutine|module|function|public|private|'
                   r'return|if|case|call|throw|await|async|interface|struct)\b',re.I)
_NUMBERED = re.compile(r'^\s*(\d+) \| ')


def _terms(question):
    tokens=set(re.findall(r'[a-z][a-z0-9_]{3,}',question.lower()))
    return tokens-_STOP


def _compress_window(path, numbered, question, max_chars):
    """Select complete original lines and keep exact path:line provenance."""
    if not numbered or max_chars<200:
        return None
    terms=_terms(question)
    def score(item):
        line=item[1].lower()
        return 4*sum(t in line for t in terms)+(2 if _DECL.search(line) else 0)
    ranked=sorted(range(len(numbered)),
                  key=lambda i:(-score(numbered[i]),i))
    # Keep a short contiguous neighborhood around the strongest match.
    anchor=ranked[0]
    begin=max(0,anchor-2)
    end=min(len(numbered),anchor+4)
    choices=list(range(begin,end))
    # Add other independently relevant lines only when they provide new context.
    for idx in ranked:
        if idx not in choices and score(numbered[idx])>0 and len(choices)<10:
            choices.append(idx)
    # Greedy evidence selection must be ranked by information value, not
    # ascending source line: otherwise early boilerplate can use the entire
    # budget before the matched function appears.
    priority=sorted(choices,key=lambda i:(
        -score(numbered[i]), abs(i-anchor), i))
    kept=[]
    for idx in priority:
        ln,raw=numbered[idx]
        attempted=sorted(kept+[(ln,raw)],key=lambda pair:pair[0])
        refs=[f'{path}:{line}' for line,_ in attempted]
        result={'path':path,'content':'\n'.join(text for _,text in attempted),
                'source_refs':refs,'visible_refs':refs,
                'compressed':len(attempted)<len(numbered),
                'source_lines_considered':len(numbered)}
        if len(json.dumps(result,ensure_ascii=False))>max_chars:
            continue
        kept=attempted
    if not kept:
        return None
    refs=[f'{path}:{line}' for line,_ in kept]
    return {'path':path,'content':'\n'.join(text for _,text in kept),
            'source_refs':refs,'visible_refs':refs,
            'compressed':len(kept)<len(numbered),
            'source_lines_considered':len(numbered)}


def acquire_evidence(repo, candidates, question, max_chars=3600, limit=6, *,\n                     mode='c2', llm=None):
    """Read actual code at embedding hints, compress across multiple files.

    Only indexed candidate windows are eligible. Missing hints are ignored;
    no invented line numbers, file paths or gold labels are consulted.
    """
    output=[]
    used=set()
    for candidate in candidates:
        if len(output)>=limit:
            break
        if not isinstance(candidate,dict):
            continue
        path=candidate.get('path')
        start=candidate.get('line_start',candidate.get('start_line'))
        end=candidate.get('line_end',candidate.get('end_line'))
        if (not isinstance(path,str) or not isinstance(start,int)
                or not isinstance(end,int) or start<1 or end<start
                or path in used):
            continue
        # Never read unbounded or model-generated source ranges.
        end=min(end,start+47)
        try:
            content=repo.read_file(path,start,end)
        except (OSError,ValueError,TypeError,KeyError):
            continue
        numbered=[]
        for raw in content.splitlines():
            match=_NUMBERED.match(raw)
            if match:
                ln=int(match.group(1))
                if start<=ln<=end:
                    numbered.append((ln,raw))
        if not numbered:
            continue
        # Reserve remaining budget for other files; never silently slice lines.
        remaining=max_chars-len(json.dumps(output,ensure_ascii=False))
        allowed=min(780,remaining-40)
        from context_compression import compress\n        snippet=compress(path,numbered,question,allowed,mode=mode,llm=llm)
        if snippet:
            next_output=output+[snippet]
            if len(json.dumps(next_output,ensure_ascii=False))<=max_chars:
                output=next_output
                used.add(path)
    return output
