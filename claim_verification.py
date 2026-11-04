"""Conservative source-citation/claim audit, NOT a semantic entailment judge.

Reports unverifiable and unsupported citation use without claiming that a
quoted source line proves an arbitrary natural-language statement.
"""
from __future__ import annotations
import re

REF=re.compile(r'(?<!\w)([\w./\\-]+\.[A-Za-z0-9]+:\d+)\b')


def audit_claims(answer, allowed_refs, *, max_claims=24):
    allowed=set(allowed_refs)
    # Split prose statements, not source code; avoid treating headings as claims.
    sentences=[s.strip(' \t\r\n-*') for s in re.split(r'(?<=[.!?。])\s+|\n+',answer)
               if s.strip(' \t\r\n-*')]
    claims=[]
    for sentence in sentences[:max_claims]:
        if len(sentence)<12 or sentence.startswith(('#','```')):
            continue
        refs=list(dict.fromkeys(REF.findall(sentence)))
        status=('no_source_citation' if not refs else
                'invalid_citation' if any(ref not in allowed for ref in refs) else
                'citation_present_not_semantically_verified')
        claims.append({'statement':sentence[:500], 'citation_refs':refs,
                       'status':status})
    return {'claims':claims,'claims_examined':len(claims),
            'invalid_citation_claims':sum(c['status']=='invalid_citation' for c in claims),
            'uncited_claims':sum(c['status']=='no_source_citation' for c in claims),
            'semantic_entailment_verified':False,
            'note':'A valid citation does not prove the claim. Manual or model-based evidence grading remains necessary.'}
