"""Opt-in Qwen3-Embedding-0.6B source-chunk retrieval (stdlib; local-only).

Run after the ordinary `agent.py intelligence` index is built.
The vector index is independent of the production Code Intelligence DB.
Gold labels are never read during indexing, retrieval, or reranking.
"""
from __future__ import annotations

import argparse
from array import array
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_MODEL = 'qwen3-embedding:0.6b'
DEFAULT_HOST = 'http://127.0.0.1:11434'
TASK = ('Given a question about a source-code repository, retrieve source-code '
        'passages that contain the implementation and evidence needed to answer it.')
DB_VERSION = '1'
MODEL_RE = re.compile(r'^[a-zA-Z0-9_.:/-]{1,120}$')


def require_local_host(host):
    parsed = urllib.parse.urlsplit(host)
    if (parsed.scheme != 'http' or parsed.hostname not in
            ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Embedding host must be a local Ollama HTTP endpoint')
    return host.rstrip('/')


class OllamaEmbedder:
    def __init__(self, model=DEFAULT_MODEL, host=DEFAULT_HOST, dimensions=1024,
                 timeout=120):
        if not MODEL_RE.fullmatch(model):
            raise ValueError('Invalid embedding model name')
        if not 32 <= int(dimensions) <= 1024:
            raise ValueError('Dimensions must be in range 32..1024 for Qwen3-Embedding-0.6B')
        self.model = model
        self.host = require_local_host(host)
        self.dimensions = int(dimensions)
        self.timeout = timeout

    def embed(self, texts, *, query=False, keep_alive='5m'):
        if not texts:
            return []
        if query:
            texts = [f'Instruct: {TASK}\nQuery: {text}' for text in texts]
        request = urllib.request.Request(
            self.host + '/api/embed', method='POST',
            data=json.dumps({'model': self.model, 'input': texts,
                             'dimensions': self.dimensions, 'truncate': False,
                             'keep_alive': keep_alive}, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                content = json.loads(response.read(30_000_000))
        except urllib.error.HTTPError as exc:
            # HTTPError subclasses URLError: decode the response FIRST or we
            # lose the actionable Ollama reason (e.g. EOF / context / model).
            detail = exc.read(2048).decode('utf-8', errors='replace').strip()
            raise RuntimeError(
                f'Ollama /api/embed HTTP {exc.code}: ' +
                (detail[:600] if detail else str(exc.reason))) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError('Cannot reach local Ollama /api/embed: ' + str(exc)) from exc
        vectors = content.get('embeddings')
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError('Unexpected Ollama embedding response shape')
        results = []
        for vector in vectors:
            if (len(vector) != self.dimensions or
                    not all(isinstance(v, (float, int)) and math.isfinite(v) for v in vector)):
                raise ValueError('Embedding dimension mismatch or invalid numeric values')
            norm = math.sqrt(sum(float(v) * float(v) for v in vector))
            if norm <= 0:
                raise ValueError('Zero embedding vector')
            results.append(array('f', (float(v) / norm for v in vector)))
        return results


def _configure(conn):
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS indexed_files (
            path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, expected INTEGER NOT NULL,
            received INTEGER NOT NULL DEFAULT 0, complete INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chunks (
            path TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
            embedding BLOB NOT NULL, preview TEXT NOT NULL,
            PRIMARY KEY(path, start_line)
        );
        CREATE INDEX IF NOT EXISTS chunks_path_idx ON chunks(path);
    ''')


def _meta(conn):
    return dict(conn.execute('SELECT key,value FROM meta'))


def _chunk_lines(lines, size=48, overlap=12):
    if size < 8 or size > 160 or overlap < 0 or overlap >= size:
        raise ValueError('Invalid chunk size or overlap')
    step = size - overlap
    for offset in range(0, len(lines), step):
        segment = lines[offset:offset+size]
        if not segment:
            break
        yield offset+1, offset+len(segment), '\n'.join(segment)
        if offset+size >= len(lines):
            break


def _source_paths(index_db):
    if not Path(index_db).is_file():
        raise FileNotFoundError('Code intelligence index missing: ' + str(index_db))
    # This is a read-only connection to the existing source inventory.
    uri = Path(index_db).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        return [row[0] for row in conn.execute('SELECT path FROM files ORDER BY path')]



def _shorten_failed_chunk(entry, char_limit):
    """Shorten at real source-line boundaries; never pretend omitted lines were embedded."""
    path, start, end, text, preview = entry
    first, sep, remain = text.partition('\n')
    line_label, sep2, source = remain.partition('\n')
    if not sep or not sep2:
        raise ValueError('Malformed indexed embedding chunk')
    prefix = f'{first}\nLines: {start}-{end}\n'
    remaining = char_limit - len(prefix)
    if remaining <= 0:
        raise ValueError('Embedding chunk path/header exceeds fallback limit')
    kept = []
    for source_line in source.splitlines(keepends=True):
        if len(source_line) > remaining:
            if not kept:
                kept.append(source_line[:remaining])
            break
        kept.append(source_line)
        remaining -= len(source_line)
    if not kept:
        raise ValueError('Cannot shorten empty embedding chunk')
    covered_end = min(end, start + len(kept) - 1)
    short = f'{first}\nLines: {start}-{covered_end}\n' + ''.join(kept)
    return short, covered_end


def _embed_index_rows(embedder, rows, stats):
    """Recover from batch HTTP 400 without discarding previously indexed work.

    On singleton HTTP 400, try a smaller, source-line-bounded excerpt.
    Record its ACTUAL covered end line in SQLite; do not claim the original
    48-line chunk was fully embedded. Other failures remain visible.
    """
    try:
        vectors = embedder.embed([item[3] for item in rows], keep_alive='5m')
        return [(item, vector, item[2]) for item, vector in zip(rows, vectors)]
    except RuntimeError as exc:
        if 'HTTP 400' not in str(exc):
            raise
        if len(rows) > 1:
            stats['embed_batch_splits'] += 1
            middle = len(rows) // 2
            return (_embed_index_rows(embedder, rows[:middle], stats) +
                    _embed_index_rows(embedder, rows[middle:], stats))
        original = rows[0]
        for limit in (3500, 1800, 900):
            if len(original[3]) <= limit:
                continue
            shortened, actual_end = _shorten_failed_chunk(original, limit)
            try:
                vector = embedder.embed([shortened], keep_alive='5m')[0]
            except RuntimeError as retry_error:
                if 'HTTP 400' in str(retry_error):
                    continue
                raise
            stats['embed_chunks_shortened'] += 1
            return [(original, vector, actual_end)]
        raise RuntimeError(
            'Embedding chunk failed even after bounded retries for ' +
            original[0] + ':' + str(original[1]) +
            '. Original Ollama error: ' + str(exc)[:300]) from exc


def index_project(repo, intelligence_db, destination, embedder, *, chunk_lines=48,
                  overlap=12, batch_size=16, max_files=0, progress=None):
    """Resumable incremental indexing. Incomplete files never enter results."""
    batch_size = max(1, min(64, int(batch_size)))
    expected_meta = {
        'version': DB_VERSION, 'root': str(repo.root), 'model': embedder.model,
        'dimensions': str(embedder.dimensions), 'chunk_lines': str(chunk_lines),
        'overlap': str(overlap),
    }
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    paths = _source_paths(intelligence_db)
    if max_files:
        paths = paths[:max(1, int(max_files))]
    stats = {'files_total': len(paths), 'files_changed': 0,
             'files_reused': 0, 'files_failed': 0, 'chunks_embedded': 0,
             'embed_batch_splits': 0, 'embed_chunks_shortened': 0,
             'index': str(target)}
    with closing(sqlite3.connect(target)) as conn:
        _configure(conn)
        current = _meta(conn)
        if current and any(current.get(k) != v for k, v in expected_meta.items()):
            raise ValueError('Embedding index configuration changed: use a new --db or delete old DB')
        with conn:
            conn.executemany('INSERT OR REPLACE INTO meta VALUES (?,?)', expected_meta.items())
            # Remove files no longer present in the source inventory. A limited
            # --max-files run is intentionally partial and must not prune others.
            if not max_files:
                inventory_paths = set(paths)
                stale = [p for (p,) in conn.execute('SELECT path FROM indexed_files')
                         if p not in inventory_paths]
                for path in stale:
                    conn.execute('DELETE FROM chunks WHERE path=?', (path,))
                    conn.execute('DELETE FROM indexed_files WHERE path=?', (path,))
        pending = []

        def flush():
            nonlocal pending
            if not pending:
                return
            embedded_rows = _embed_index_rows(embedder, pending, stats)
            with conn:
                for (path, start, end, _body, preview), vector, covered_end in embedded_rows:
                    conn.execute('INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?)',
                                 (path, start, covered_end, vector.tobytes(), preview))
                    conn.execute('UPDATE indexed_files SET received=received+1 WHERE path=?',
                                 (path,))
                conn.execute('UPDATE indexed_files SET complete=1 '
                             'WHERE received>=expected AND complete=0')
            stats['chunks_embedded'] += len(pending)
            pending = []

        for path in paths:
            try:
                # The Repo API enforces traversal, symlink and source-extension
                # restrictions; reading it does not execute source code.
                source = repo._read(repo._safe(path))
                digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
                old = conn.execute('SELECT sha256,complete FROM indexed_files WHERE path=?',
                                   (path,)).fetchone()
                if old == (digest, 1):
                    stats['files_reused'] += 1
                    continue
                segments = list(_chunk_lines(source.splitlines(), chunk_lines, overlap))
                with conn:
                    conn.execute('DELETE FROM chunks WHERE path=?', (path,))
                    conn.execute('INSERT OR REPLACE INTO indexed_files VALUES (?,?,?,?,?)',
                                 (path, digest, len(segments), 0, int(not segments)))
                stats['files_changed'] += 1
                for start, end, body in segments:
                    # The model is asked about actual code, with repo path and
                    # nearby file context; we do not prepend Qwen instructions
                    # to indexed *documents* (only to queries).
                    plain = f'File: {path}\nLines: {start}-{end}\n{body}'
                    if len(plain) > 14000:
                        plain = plain[:14000]
                    preview = next((line.strip()[:180] for line in body.splitlines()
                                    if line.strip()), '')
                    pending.append((path, start, end, plain, preview))
                    if len(pending) >= batch_size:
                        flush()
                if progress and stats['files_changed'] % 100 == 0:
                    progress(dict(stats))
            except (OSError, ValueError, UnicodeError) as exc:
                stats['files_failed'] += 1
                if progress:
                    progress({'warning': path + ': ' + str(exc)[:180]})
        flush()
        stats['files_indexed'] = conn.execute(
            'SELECT COUNT(*) FROM indexed_files WHERE complete=1').fetchone()[0]
        stats['chunks_total'] = conn.execute(
            'SELECT COUNT(*) FROM chunks JOIN indexed_files USING(path) '
            'WHERE indexed_files.complete=1').fetchone()[0]
    return stats


def _query_vector(conn, embedder, query):
    config = _meta(conn)
    if (config.get('model') != embedder.model or
            config.get('dimensions') != str(embedder.dimensions)):
        raise ValueError('Embedding model/dimension mismatch with DB')
    vector = embedder.embed([query], query=True, keep_alive='5m')[0]
    return vector


def dense_search(repo, query, db, embedder, limit=40, *, per_file=2):
    """Find code passages with path and actual line spans; no verified citation."""
    if not query.strip():
        return []
    if not Path(db).is_file():
        raise FileNotFoundError('Embedding DB missing: ' + str(db))
    with closing(sqlite3.connect(db)) as conn:
        config = _meta(conn)
        if config.get('root') != str(repo.root):
            raise ValueError('Embedding index belongs to another project')
        needle = _query_vector(conn, embedder, query)
        scored = []
        for path, start, end, blob, preview in conn.execute(
            'SELECT c.path,c.start_line,c.end_line,c.embedding,c.preview '
            'FROM chunks c JOIN indexed_files f ON f.path=c.path WHERE f.complete=1'):
            candidate = array('f')
            candidate.frombytes(blob)
            if len(candidate) != len(needle):
                raise ValueError('Corrupt/mismatched embedding vector')
            score = sum(x*y for x,y in zip(needle,candidate))
            scored.append((score,path,start,end,preview))
        scored.sort(key=lambda row:(-row[0],row[1],row[2]))
        output=[]
        seen={}
        for score,path,start,end,preview in scored:
            if seen.get(path,0)>=per_file:
                continue
            output.append({'path':path,'start_line':start,'end_line':end,
                           'line_hint':start+(end-start)//2,
                           'similarity':round(score,6), 'preview':preview,
                           'retrieval_origin':'qwen3-embedding', 'citation':False})
            seen[path]=seen.get(path,0)+1
            if len(output)>=max(1,min(100,int(limit))):
                break
        return output


def _rrf(ranked_views, limit=20, rrf_k=40):
    scores={}
    info={}
    for name, weight, items in ranked_views:
        seen=set()
        for rank, item in enumerate(items,1):
            path=item.get('path')
            if not isinstance(path,str) or path in seen:
                continue
            seen.add(path)
            scores[path]=scores.get(path,0.0)+weight/(rrf_k+rank)
            row=info.setdefault(path,{'path':path, 'retrieval_views':[],
                                      'citation':False, 'candidate_origin':'qwen3-hybrid',
                                      'kind':'hybrid-file-candidate',
                                      'file_role':'other'})
            row['retrieval_views'].append(name)
            if item.get('file_role') and item['file_role']!='other':
                row['file_role']=item['file_role']
            hint = item.get('line_hint', item.get('line'))
            if isinstance(hint,int) and (name=='dense' or 'line_hint' not in row):
                row['line_hint']=hint
                row['line_start']=item.get('start_line',hint)
                row['line_end']=item.get('end_line',hint)
                # Keep both legacy wrapper aliases and the canonical range
                # keys used by benchmark/embedding_compare.py.
                row['start_line']=row['line_start']
                row['end_line']=row['line_end']
                row['line_hint_source']=name
    results=sorted(scores,key=lambda path:(-scores[path],-len(info[path]['retrieval_views']),path))
    for path in results:
        info[path]['path_score']=round(1000*scores[path],5)
    return [info[path] for path in results[:max(1,min(50,int(limit)))]]


def hybrid_search(repo, question, db, embedder, *, limit=20,
                  lexical_search=None, source_search=None):
    """Independent BM25-file + BM25-line + dense views. Gold-blind RRF."""
    if lexical_search is None:
        from code_intelligence import search_file_candidates
        lexical_search = search_file_candidates
    if source_search is None:
        from code_intelligence import search_relevant_sources
        source_search = search_relevant_sources
    lexical = lexical_search(repo,question,limit=40,strategy='v59')
    line_hits = source_search(repo,question,limit=30)
    dense = dense_search(repo,question,db,embedder,limit=60,per_file=1)
    return _rrf([('filename',1.0,lexical),('fts-line',1.1,line_hits),
                 ('dense',1.4,dense)],limit=limit)


def _cli(argv=None):
    from codebase import Repo
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('index','search'))
    p.add_argument('--project',required=True)
    p.add_argument('--db',required=True)
    p.add_argument('--intelligence-index',help='Existing code_intelligence.sqlite (for index)')
    p.add_argument('--model',default=DEFAULT_MODEL)
    p.add_argument('--host',default=DEFAULT_HOST)
    p.add_argument('--dimensions',type=int,default=1024)
    p.add_argument('--chunk-lines',type=int,default=48)
    p.add_argument('--overlap',type=int,default=12)
    p.add_argument('--batch-size',type=int,default=16)
    p.add_argument('--max-files',type=int,default=0)
    p.add_argument('--limit',type=int,default=20)
    p.add_argument('--mode',choices=('dense','hybrid'),default='hybrid')
    p.add_argument('--query',default='')
    args=p.parse_args(argv)
    repo=Repo(args.project)
    embedder=OllamaEmbedder(args.model,args.host,args.dimensions)
    if args.operation=='index':
        if not args.intelligence_index:
            p.error('--intelligence-index is required for indexing')
        result=index_project(repo,args.intelligence_index,args.db,embedder,
                             chunk_lines=args.chunk_lines,overlap=args.overlap,
                             batch_size=args.batch_size,max_files=args.max_files,
                             progress=lambda row:print(json.dumps(row,ensure_ascii=False),flush=True))
    else:
        if not args.query:
            p.error('--query is required for search')
        repo.intelligence_db=Path(args.intelligence_index) if args.intelligence_index else None
        if args.mode=='hybrid' and repo.intelligence_db is None:
            p.error('--intelligence-index is required for hybrid search')
        result=(dense_search(repo,args.query,args.db,embedder,args.limit)
                if args.mode=='dense' else
                hybrid_search(repo,args.query,args.db,embedder,limit=args.limit))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    sys.exit(_cli())
