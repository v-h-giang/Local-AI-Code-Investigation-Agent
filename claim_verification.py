"""Conservative claim-to-evidence audit (not a semantic entailment judge).

Checks exact citations against observed numbered source lines, never against
untrusted filenames alone. Human/model semantic grading remains distinct.
"""
from __future__ import annotations
import re

REF=re.compile(r'(?<!\w)([\w./\\-]+\.[A-Za-z0-9]+:\d+)\b')
LINE=re.compile(r'^\s*(\d+)\s+\|\s')


def observed_source_refs(observations):
    """Return refs whose full numbered source line was present in tool outputs."""
    confirmed=set()
    def walk(item):
        if isinstance(item,list):
            for entry in item:walk(entry)
        elif isinstance(item,dict):
            path=item.get('path')
            content=item.get('content')
            if isinstance(path,str) and isinstance(content,str):
                for line in content.splitlines():
                    match=LINE.match(line)
                    if match:
                        confirmed.add(path+':'+str(int(match.group(1))))
            for key in ('observation','evidence','source_excerpts'):
                if key in item:walk(item[key])
    walk(observations)
    return confirmed


def audit_claims(answer, allowed_refs, *, observations=None, max_claims=24):
    allowed=set(allowed_refs)
    observed=observed_source_refs(observations) if observations is not None else None
    # Approximate sentence segmentation. This is a diagnostic, not a grader.
    sentences=[s.strip(' \t\r\n-*') for s in re.split(r'(?<=[.!?。])\s+|\n+',answer)
               if s.strip(' \t\r\n-*')]
    claims=[]
    for sentence in sentences[:max_claims]:
        if len(sentence)<12 or sentence.startswith(('#','```')):
            continue
        refs=list(dict.fromkeys(REF.findall(sentence)))
        if not refs:
            status='no_source_citation'
        elif any(ref not in allowed for ref in refs):
            status='invalid_citation'
        elif observed is not None and any(ref not in observed for ref in refs):
            status='citation_not_in_observed_source'
        else:
            status='citation_present_not_semantically_verified'
        claims.append({'statement':sentence[:500], 'citation_refs':refs,
                       'status':status})
    return {'claims':claims,'claims_examined':len(claims),
            'invalid_citation_claims':sum(c['status']=='invalid_citation' for c in claims),
            'uncited_claims':sum(c['status']=='no_source_citation' for c in claims),
            'citation_not_observed_claims':sum(
                c['status']=='citation_not_in_observed_source' for c in claims),
            'semantic_entailment_verified':False,
            'note':'Only citation provenance is checked. Whether source actually entails a claim requires independent review.'}
