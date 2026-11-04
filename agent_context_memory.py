"""Bounded, source-safe agent context compaction for extended investigations.

Only compacts what goes into the LLM prompt. Full tool history and original
source observations remain in the returned investigation trace. No model calls.
"""
from __future__ import annotations
import json


def compact_history(history, *, max_chars=2600, recent=2):
    """Return bounded tool-observation view and audit metadata.

    Compacted entries contain tool, query, error and exact source refs only.
    They are memory/navigation hints, never additional source observations.
    """
    if max_chars < 300:
        raise ValueError('max_chars too small')
    if not history:
        return [], {'compacted_steps':0,'prompt_chars':2}
    view=[]
    # Preserve the most recent full tool observation when possible. If the
    # last two are too large, prefer one over dropping BOTH source excerpts.
    for row in reversed(history[-max(0,recent):]):
        candidate=[row]+view
        if len(json.dumps(candidate,ensure_ascii=False,default=str))<=max_chars:
            view=candidate
    old=history[:len(history)-len(view)]
    compact=[]
    for row in old:
        compact.append({'step':row.get('step'),'tool':row.get('tool'),
                        'query':str(row.get('query',''))[:140],
                        'source_refs':list(dict.fromkeys(row.get('source_refs',[])))[:14],
                        'error':str(row.get('error',''))[:100]})
    while compact and len(json.dumps(compact+view,ensure_ascii=False,default=str))>max_chars:
        compact.pop(0)
    while view and len(json.dumps(compact+view,ensure_ascii=False,default=str))>max_chars:
        view.pop(0)
    result=compact+view
    return result, {'compacted_steps':len(compact),
                    'omitted_steps':len(history)-len(result),
                    'prompt_chars':len(json.dumps(result,ensure_ascii=False,default=str))}


def prompt_history(history, *, enabled=False, max_chars=2600, recent=2):
    if not enabled:
        return history[-3:], {'compacted_steps':0,'omitted_steps':max(0,len(history)-3)}
    return compact_history(history,max_chars=max_chars,recent=recent)
