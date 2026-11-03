# Qwen3-Embedding-0.6B — optional source retrieval

[Overview](#overview) · [Setup](#setup) · [Experiment A](#experiment-a-retrieval) · [Experiment B](#experiment-b-reasoning-models) · [Experiment C](#experiment-c-end-to-end) · [Limitations](#limitations)

## Overview

This is an **experimental, local-only retrieval path** for the existing code-investigation agent. The production `agent.py` is unchanged. Existing SQLite FTS5 and symbol/graph search remain available. The embedding index is a separate SQLite file and contains vectors, chunk ranges and short code previews; keep it private.

- `semantic_retrieval.py`: incremental chunk embedding using Ollama `/api/embed`, local cosine retrieval, and BM25/FTS/dense reciprocal-rank fusion.
- `semantic_agent.py`: opt-in agent CLI wrapper. Adds embedding retrieval for the default `v59` file discovery strategy; retains `baseline` and previous tools. When a line hint is available for a selected file, it converts file search into a validated `read_source` operation. Hints are **not citations**.
- `benchmark/embedding_compare.py`: compares frozen-repo baseline, dense and hybrid retrieval using the same gold files, never using labels for ranking.
- `tests/test_semantic_embedding.py`: offline deterministic tests; no Ollama required.

## Setup

Windows PowerShell, from the Git repository root:

```powershell
git fetch origin
git switch feature/qwen3-embedding-retrieval
ollama pull qwen3-embedding:0.6b
py -3 -m unittest discover -s tests -v
```

Create the standard intelligence index **first** for your target source project:

```powershell
py -3 agent.py --project "D:\\Work\\LegacyProject" intelligence --out "D:\\AgentOutput\\architecture"
```

Build the optional semantic index (the vector index is deliberately OUTSIDE the source project):

```powershell
py -3 semantic_retrieval.py index --project "D:\\Work\\LegacyProject" --intelligence-index "D:\\AgentOutput\\architecture\\middle-files\\code_intelligence.sqlite" --db "D:\\AgentOutput\\architecture\\middle-files\\qwen3_embed.sqlite" --chunk-lines 48 --overlap 12 --batch-size 8
```

The index resumes when rerun, reuses unchanged files and only regenerates changed files. Chunking and embedding dimension are fixed per DB. To change them, specify a NEW DB path. On a memory-limited machine start with `--batch-size 4` or `8`. Ollama must be running locally.

Optional standalone retrieval:

```powershell
py -3 semantic_retrieval.py search --project "D:\\Work\\LegacyProject" --intelligence-index "D:\\AgentOutput\\architecture\\middle-files\\code_intelligence.sqlite" --db "D:\\AgentOutput\\architecture\\middle-files\\qwen3_embed.sqlite" --mode hybrid --query "Where is workflow checkpoint restoration implemented?" --limit 20
```

Run the existing agent with embedding retrieval enabled:

```powershell
py -3 semantic_agent.py --semantic-db "D:\\AgentOutput\\architecture\\middle-files\\qwen3_embed.sqlite" --project "D:\\Work\\LegacyProject" --model qwen3:8b investigate "Where is workflow checkpoint restoration implemented?" --report-format md
```

Leave the ordinary `agent.py` untouched to run the lexical baseline.

## Experiment A: retrieval

Use the existing pinned dataset and prepared index. The example uses the existing `semantic_kb_v511_smoke` cache; replace its run ID if yours differs.

```powershell
py -3 semantic_retrieval.py index --project "benchmark\\repositories\\agent-framework" --intelligence-index "benchmark\\results\\semantic_kb_v511_smoke\\_prepared_indexes\\repocontextbench\\middle-files\\code_intelligence.sqlite" --db "benchmark\\results\\agent-framework.sqlite" --batch-size 8
py -3 benchmark/embedding_compare.py --from-run semantic_kb_v511_smoke --suite repocontextbench --embed-db "benchmark\\results\\agent-framework.sqlite" --out "benchmark\\results\\qwen3_embedding_ab.json"
```

This produces baseline/dense/hybrid **file recall@8/20** and a separate **chunk/gold-span overlap proxy**. A chunk overlap is not a validated source-line citation and must not be reported as such. No generative LLM is called.

## Experiment B: reasoning models

Do NOT fork branches just to change model tags. Keep the source, embedding DB, frozen repository commit and tool budget identical. Use different `--model` and `--run-id` values:

```powershell
$env:LOCAL_CODE_AGENT_EMBEDDING_DB = (Resolve-Path "benchmark\\results").Path
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model qwen3:8b --run-id qwen3_embedding_reasoning
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id nemotron_embedding_reasoning
```

When `LOCAL_CODE_AGENT_EMBEDDING_DB` points to a directory, the wrapper selects `<project-folder-name>.sqlite` (e.g. `agent-framework.sqlite` or `jdbi.sqlite`). Confirm the actual Ollama model tag with `ollama list` before starting. The standard runner does NOT modify any source repository.

## Experiment C: end-to-end

Build one embedding DB for each pinned benchmark repository (e.g. `agent-framework.sqlite`, `jdbi.sqlite`) and put both in the same directory. Then use the standard runner with `--suite all`, first Qwen then Nemotron, at identical `--max-steps`, `--review-rounds`, `--max-llm-calls`, and model context settings. The runner already records `file:line` evidence validity, gold-span hits and final answers. Use unique run IDs, and evaluate only the same case IDs for both models.

For a strict baseline comparison, run **ordinary** `agent.py` with identical cases and budget. Never compare different selected case sets.

## Experiment C1: bounded evidence prefetch and extractive compression

The verified B control has 20 cases, 59 gold files and 99 gold spans; do not
overwrite its results. For C1, keep the same model, pinned checkout, embedding
index, question set and `--max-steps 4`. Enable the new *optional* reader:

```powershell
$env:LOCAL_CODE_AGENT_EMBEDDING_DB = (Resolve-Path "benchmark\\results\\agent-framework.sqlite").Path
$env:LOCAL_CODE_AGENT_SEMANTIC_MODE = "dense"
$env:LOCAL_CODE_AGENT_PREFETCH = "1"
py -3 -m unittest tests.test_evidence_acquisition tests.test_semantic_embedding -v
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id c1_nemotron_dense_prefetch --max-steps 4
```

`LOCAL_CODE_AGENT_PREFETCH=0` (the default) keeps the original B behavior.
The reader processes up to the first eight ranked source candidates and prefetches
up to six distinct files with valid indexed line windows. It reads original
numbered source lines and compresses them **extractively** within a 3000-character
snippet budget (plus small metadata overhead), preferentially retaining keyword
matches, declarations and nearby context. Omitted lines get **no citations**.
This avoids an extra LLM summarization call that might fabricate or suppress code.
A prefetched passage is included as a step-0 observation; it consumes prompt
budget but not one of the four LLM-guided tool steps. A duplicate initial
`search_file` probe for an already-prefetched file is skipped. The original
`agent.py` is unaffected.

Compare C1 against the existing `b_nemotron_dense` run using actual observed
gold-file, gold-span and final-citation metrics. More observed code is not itself
proof of answer correctness. Inspect per-case tool traces and manually score
claim support. Consider a second experiment with structural passage reranking
and claim verification only **after** C1 is measured.

## Limitations

- No evidence of improved Recall@K exists until the local Ollama model and pinned benchmark have been run. The repository tests use fake embeddings only.
- Cosine similarity is an exact linear scan of cached chunk vectors, which may be slow on exceptionally large codebases. This MVP has no ANN vector index or trained reranker.
- The default 48-line chunks are retrieval windows, **not precise answer citations**. The agent must still read actual line-numbered source. For tighter windows, experiment with a separate 24–32-line-chunk DB.
- Reindex after source changes. Do not move a SQLite index to an unrelated source root.
- Memory use grows with chunk count; model memory and vector-index disk use are independent. Keep the local Ollama server on loopback.
- This experimental branch depends on `improve/retrieval-stage-audit-v512`; it does not change `main` until reviewed and merged.
