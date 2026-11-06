"""Experimental reference-aware choice between existing source excerpt sets.

Inputs are real numbered source excerpts from prefetch and shared-budget
selection. The guard compares query-bearing source references and query term
coverage. Output is one of the two supplied excerpt sets, without editing
source lines or adjusting citations.
"""
from __future__ import annotations

import json
import re

from context_budget_selector import _tokens

_LINE = re.compile(r'^\s*(\d+)\s+\|\s')
_DECL = re.compile(
    r'\b(?:def|class|subroutine|function|module|interface|program|'
    r'call|return|await|public|private|throw)\b', re.I)


def _refs(excerpts):
    refs = set()
    for item in excerpts:
        refs.update(item.get('source_refs') or [])
    return refs


def _lines(excerpts):
    """Return original displayed lines keyed by exact path/line references."""
    lines = {}
    for item in excerpts:
        path = item.get('path')
        if not isinstance(path, str) or not path:
            raise ValueError('Invalid evidence path')
        displayed = []
        for source in item.get('content', '').splitlines():
            m = _LINE.match(source)
            if not m:
                raise ValueError('Unnumbered source line in evidence')
            ref = f'{path}:{int(m.group(1))}'
            displayed.append(ref)
            if ref in lines and lines[ref] != source:
                raise ValueError('Conflicting source text for same line reference')
            lines[ref] = source
        if item.get('source_refs') != displayed or item.get('visible_refs') != displayed:
            raise ValueError('Evidence refs must match displayed source lines')
    return lines


def choose_guarded(baseline, adaptive, question, *, policy='critical',
                   max_chars=3000):
    """Choose one existing excerpt set via a fixed query/source-only policy.

    critical: retain baseline if an identifier/structural query-relevant
              source line is absent from adaptive evidence.
    query:    retain baseline only when a critical line is missing AND
              adaptive does not cover more distinct question terms.
    """
    if policy not in ('critical', 'query'):
        raise ValueError('Unknown reference guard policy')
    if not isinstance(question, str):
        raise ValueError('Expected question text')
    base_lines = _lines(baseline)
    next_lines = _lines(adaptive)
    base_refs = set(base_lines)
    next_refs = set(next_lines)
    question_terms = _tokens(question)

    protected = set()
    for ref, raw in base_lines.items():
        matches = _tokens(raw) & question_terms
        if len(matches) >= 2 or (matches and _DECL.search(raw)):
            protected.add(ref)
    missing = protected - next_refs
    old_terms = set().union(*(_tokens(raw) & question_terms
                              for raw in base_lines.values())) if base_lines else set()
    new_terms = set().union(*(_tokens(raw) & question_terms
                              for raw in next_lines.values())) if next_lines else set()
    fallback = bool(missing) and (
        policy == 'critical' or len(new_terms) <= len(old_terms))
    chosen = baseline if fallback else adaptive
    size = len(json.dumps(chosen, ensure_ascii=False))
    if size > max_chars:
        raise ValueError('Guarded evidence exceeds total character budget')
    return {
        'excerpts': chosen,
        'choice': 'baseline' if fallback else 'adaptive_1',
        'policy': policy,
        'serialized_chars': size,
        'baseline_ref_count': len(base_refs),
        'retained_baseline_ref_count': len(base_refs & _refs(chosen)),
        'critical_baseline_ref_count': len(protected),
        'critical_baseline_refs_missing_from_adaptive': len(missing),
        'baseline_query_term_count': len(old_terms),
        'adaptive_query_term_count': len(new_terms),
    }
