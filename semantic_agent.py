"""Experimental agent.py entrypoint using an indexed Qwen3 code embedding DB.

This wrapper preserves production agent.py, and is usable as benchmark/run.py
--agent argument. Its file-navigation hook changes only the v59 strategy;
legacy baseline and all source-evidence validation remain intact.

Set LOCAL_CODE_AGENT_EMBEDDING_DB or pass --semantic-db. The database is
required for investigate: no silent fallback to lexical retrieval.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import subprocess


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    options = argparse.ArgumentParser(add_help=False)
    options.add_argument('--semantic-db')
    options.add_argument('--semantic-mode',choices=('hybrid','dense'),
                         default=os.environ.get('LOCAL_CODE_AGENT_SEMANTIC_MODE','hybrid'))
    options.add_argument('--semantic-model',
                         default=os.environ.get('LOCAL_CODE_AGENT_SEMANTIC_MODEL',
                                                'qwen3-embedding:0.6b'))
    options.add_argument('--semantic-dimensions',type=int,
                         default=int(os.environ.get('LOCAL_CODE_AGENT_SEMANTIC_DIMENSIONS',
                                                    '1024')))
    options.add_argument('--compression-mode',
                         choices=('structure_mmr','llm_evidence_select',
                                  'structure_llm_summary','legacy','c2','c3','c4'),
                         default=os.environ.get('LOCAL_CODE_AGENT_COMPRESSION_MODE',
                                                'structure_mmr'))
    settings,remaining = options.parse_known_args(args)
    import agent
    if 'investigate' not in remaining:
        return agent.main(remaining)
    database = settings.semantic_db or os.environ.get('LOCAL_CODE_AGENT_EMBEDDING_DB')
    if database is None:
        raise SystemExit('Embedding DB is required: --semantic-db or LOCAL_CODE_AGENT_EMBEDDING_DB')
    database = Path(database).expanduser().resolve()
    if '--project' not in remaining:
        raise SystemExit('Missing --project: required to verify or rebuild semantic index')
    project = Path(remaining[remaining.index('--project')+1]).expanduser().resolve()
    if database.is_dir() or database.suffix.lower() != '.sqlite':
        database = database / (project.name + '.sqlite')
    if not database.is_file():
        # Reconstruct from the source, never from benchmark gold labels.
        # semantic_retrieval.py also restores missing Code Intelligence first.
        output = Path('output/architecture')
        if '--out' in remaining:
            output = Path(remaining[remaining.index('--out')+1])
        intelligence = output.expanduser().resolve()/'middle-files'/'code_intelligence.sqlite'
        host = remaining[remaining.index('--host')+1] if '--host' in remaining else 'http://127.0.0.1:11434'
        cmd=[sys.executable,str(Path(__file__).resolve().parent/'semantic_retrieval.py'),
             'index','--project',str(project),
             '--intelligence-index',str(intelligence),'--db',str(database),
             '--model',settings.semantic_model,
             '--dimensions',str(settings.semantic_dimensions),'--host',host,
             '--batch-size','8']
        print('[Semantic] Missing embedding index: '+str(database),flush=True)
        print('[Semantic] Auto rebuilding. Requires Ollama and embedding model: '
              +settings.semantic_model,flush=True)
        try:
            subprocess.run(cmd,check=True)
        except (OSError,subprocess.CalledProcessError) as exc:
            raise SystemExit('Automatic semantic index recovery failed. '
                             'Check Ollama, installed embedding model, project '
                             'path and free disk space. Retry command: '
                             +subprocess.list2cmdline(cmd)) from exc
        if not database.is_file():
            raise SystemExit('Semantic index recovery completed without database: '
                             +str(database))

    from semantic_retrieval import OllamaEmbedder, dense_search, hybrid_search
    from code_intelligence import search_file_candidates as original
    import code_intelligence
    import investigation_loop
    host = 'http://127.0.0.1:11434'
    if '--host' in remaining:
        host = remaining[remaining.index('--host')+1]
    embedder = OllamaEmbedder(settings.semantic_model,host,settings.semantic_dimensions)
    # Retain only paths returned by index-backed retrieval, not model-guessed paths.
    line_windows = {}

    def semantic_search(repo, query, limit=6, *, strategy='v59'):
        if strategy!='v59':
            return original(repo,query,limit=limit,strategy=strategy)
        if settings.semantic_mode=='dense':
            matches=dense_search(repo,query,database,embedder,limit=limit,per_file=1)
            rows=[{'path':item['path'], 'path_score':round(item['similarity']*100,4),
                   'file_role':'implementation', 'citation':False,
                   'kind':'semantic-file-candidate',
                   'candidate_origin':'qwen3-embedding',
                   'line_hint':item['line_hint'],
                   'line_start':item['start_line'], 'line_end':item['end_line']}
                  for item in matches]
        else:
            rows=hybrid_search(repo,query,database,embedder,limit=limit,
                               lexical_search=original)
        for item in rows:
            if isinstance(item.get('line_hint'),int) and item.get('path') not in line_windows:
                line_windows[item['path']]=(int(item.get('line_start',item['line_hint'])),
                                            int(item.get('line_end',item['line_hint'])))
        return rows

    # The legacy search_file action requires lexical matches inside the file.
    # That misses the exact natural-language/paraphrase cases dense retrieval
    # is intended to rescue. Convert ONLY known indexed line hints into a
    # source read. The original read_source tool still validates the path and
    # produces numbered source evidence; these hints are not citations.
    original_validator=investigation_loop._validate_action
    def validate_with_embeddings(action):
        if isinstance(action,dict) and action.get('tool')=='search_file':
            span=line_windows.get(action.get('path'))
            if span:
                start,end=span
                return original_validator({'tool':'read_source',
                                           'path':action['path'],
                                           'start_line':max(1,start-8),
                                           'end_line':min(start+99,end+8)})
        return original_validator(action)

    code_intelligence.search_file_candidates=semantic_search
    investigation_loop._validate_action=validate_with_embeddings
    # structure_mmr is the default; disable prefetch to reproduce B/C0.
    # The configured local reasoning model is reused in C3/C4 (no new service).
    # The hook is an instance-local function installed before agent.main().
    if os.environ.get('LOCAL_CODE_AGENT_PREFETCH','1')=='1':
        from evidence_acquisition import acquire_evidence
        def prefetch(repo, candidates, question, *, max_chars=3000,
                     limit=6, llm=None):
            return acquire_evidence(repo,candidates,question,max_chars=max_chars,
                                    limit=limit,mode=settings.compression_mode,llm=llm)
        investigation_loop._evidence_prefetch=prefetch
    return agent.main(remaining)


if __name__=='__main__':
    sys.exit(main())
