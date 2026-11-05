"""Scoped, source-index-grounded symbol navigation (experimental; read-only).

Pure-natural-language questions: resolve compound symbol names ONLY inside
existing hybrid-ranked file candidates, without changing file ranks or Dense
line windows. Explicit code identifiers: additionally rescue at most two
unambiguous exact definitions, respecting an explicitly named language.

All symbol hits are navigational hints, never citations or code evidence.
No gold labels, LLM-derived paths, source execution, or additional embeddings.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import re
import sqlite3


_EXCLUDE_KINDS = {'heading', 'section', 'title'}
_COMMON = {
    'the','and','for','from','where','what','which','when','why','how','with',
    'would','should','could','does','into','about','using','your','this','that',
    'are','can','will','several','after','before','then','while','same','multiple',
    'agent','agents','workflow','workflows','run','running','file','files',
    'code','class','method','function','source','python','dotnet','program',
    'app','application','model','models','test','tests','data','call','calls',
    'start','result','results','return','value','values','system','user',
}


def _language_scope(question):
    if re.search(r'(?i)\.net\b|\bc#\b|\bcsharp\b|\bdotnet\b', question):
        return 'dotnet'
    if re.search(r'(?i)\bpython\b', question):
        return 'python'
    if re.search(r'(?i)\bfortran\b|\bf90\b', question):
        return 'fortran'
    return None


def _in_language(path, language):
    if language is None:
        return True
    lower = path.casefold().replace('\\', '/')
    suffix = Path(lower).suffix
    if language == 'dotnet':
        return lower.startswith('dotnet/') or suffix in ('.cs', '.csx')
    if language == 'python':
        return lower.startswith('python/') or suffix in ('.py', '.pyi')
    return suffix in ('.f', '.for', '.f90', '.f95', '.f03', '.f08')


def _name_parts(value):
    value = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', value)
    value = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', value)
    return {token.casefold() for token in re.findall(r'[A-Za-z0-9]+', value)
            if len(token) >= 4 and token.casefold() not in _COMMON}


def _valid_symbol(row, language):
    return (
        isinstance(row['path'], str) and isinstance(row['line'], int)
        and row['line'] >= 1 and _in_language(row['path'], language)
        and isinstance(row['name'], str) and row['name']
        and (row['kind'] or '').casefold() not in _EXCLUDE_KINDS
    )


def _hint(row, matched_tokens=()):
    start = row['line']
    end = row['end_line']
    end = max(start, min(start + 47, end)) if isinstance(end, int) else start
    return {
        'name': row['name'], 'kind': row['kind'], 'path': row['path'],
        'line': start, 'end_line': end,
        'matched_tokens': sorted(matched_tokens), 'citation': False,
    }


def scoped_symbol_resolve(repo, question, hybrid_rows, *, limit=30,
                          scope_limit=12, max_rescue=2):
    """Annotate scope-local symbols; rescue unique named definitions if needed.

    Hybrid ranking and Dense line windows remain intact unless an explicit
    rare identifier has a unique definition outside the top-ranked files.
    """
    from semantic_retrieval import _high_confidence_symbol_terms

    base = [dict(row) for row in hybrid_rows if isinstance(row, dict)
            and isinstance(row.get('path'), str)]
    if not base:
        # Even explicit name-only queries may be rescued from the index.
        base = []
    limit = max(1, min(50, int(limit)))
    scope_limit = max(1, min(24, int(scope_limit)))
    max_rescue = max(0, min(2, int(max_rescue)))
    scope = list(dict.fromkeys(row['path'] for row in base[:scope_limit]))
    language = _language_scope(question)
    explicit = _high_confidence_symbol_terms(question)
    query_parts = {part for word in re.findall(r'[A-Za-z_][A-Za-z_0-9]*', question)
                   for part in _name_parts(word)}
    matches = {}
    all_explicit = []

    db = Path(getattr(repo, 'intelligence_db', '') or '')
    if not db.is_file():
        return base[:limit]
    try:
        with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro',
                                     uri=True, timeout=2)) as conn:
            conn.row_factory = sqlite3.Row
            # Natural-language resolution is strictly anchored to pre-ranked
            # candidate files: no full-repository fuzzy symbol scan.
            for path in scope:
                if not _in_language(path, language):
                    continue
                for row in conn.execute(
                        'SELECT path,line,end_line,name,kind FROM symbols '
                        'WHERE path=? ORDER BY line LIMIT 192', (path,)):
                    if not _valid_symbol(row, language):
                        continue
                    overlap = _name_parts(row['name']) & query_parts
                    if len(overlap) < 2:
                        continue
                    matches.setdefault(path, []).append(_hint(row, overlap))
            # Explicit identifiers can find real source definitions beyond
            # the initial files; generic English tokens are never used here.
            for token in explicit:
                for row in conn.execute(
                        'SELECT path,line,end_line,name,kind FROM symbols '
                        'WHERE name=? COLLATE NOCASE ORDER BY path,line LIMIT 160',
                        (token,)):
                    if not _valid_symbol(row, language):
                        continue
                    h = _hint(row, [token])
                    all_explicit.append(h)
                    matches.setdefault(row['path'], []).append(h)
    except sqlite3.Error:
        return base[:limit]

    for row in base:
        hints = matches.get(row['path'], [])
        if hints:
            seen = set()
            unique = []
            for h in sorted(hints, key=lambda h: (
                    0 if h['name'].casefold() in {t.casefold() for t in explicit} else 1,
                    -len(h['matched_tokens']), h['line'], h['name'])):
                key = (h['line'], h['name'])
                if key in seen:
                    continue
                seen.add(key)
                unique.append(h)
                if len(unique) == 2:
                    break
            row['symbol_hints'] = unique

    # Only unambiguous, explicitly named definitions are allowed to insert
    # a file not already in the top eight. Natural-language questions NEVER
    # displace the existing top-8 file set.
    ranked_paths = {row['path'] for row in base[:8]}
    unique_paths = list(dict.fromkeys(h['path'] for h in all_explicit))
    rescued = []
    if explicit and 0 < len(unique_paths) <= max_rescue and not (
            ranked_paths & set(unique_paths)):
        for path in unique_paths:
            h = next(h for h in all_explicit if h['path'] == path)
            rescued.append({
                'path': path, 'line_hint': h['line'],
                'line_start': h['line'], 'line_end': h['end_line'],
                'start_line': h['line'], 'end_line': h['end_line'],
                'line_hint_source': 'scoped-symbol',
                'candidate_origin': 'indexed-scoped-symbol',
                'kind': 'symbol-file-candidate',
                'file_role': 'implementation',
                'retrieval_views': ['scoped-symbol'],
                'symbol_hints': [h], 'symbol_rescue': True,
                'citation': False,
            })
    rescued_paths = {row['path'] for row in rescued}
    return (rescued + [row for row in base if row['path'] not in rescued_paths])[:limit]
