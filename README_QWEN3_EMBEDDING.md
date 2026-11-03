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

`LOCAL_CODE_AGENT_PREFETCH=0` disables the default prefetch and reproduces the original B behavior.
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

## Context compression modes (default: `structure_mmr`)

Compression is opt-in within the `semantic_agent.py` workflow; evidence
prefetch is enabled by default there. Use stable, self-explanatory mode names
for operational commands and run IDs:

| Mode | Implementation |
| --- | --- |
| `structure_mmr` **(default)** | Structural keyword grouping + maximal marginal relevance (MMR) + bounded source selection; deterministic, no additional LLM calls |
| `llm_evidence_select` | Reuse the configured reasoning LLM to select existing numbered source lines; only original source text becomes evidence |
| `structure_llm_summary` | Retain the `structure_mmr` source evidence and optionally append a short **unverified** LLM-generated semantic note if it fits the budget |
| `legacy` | Earlier extractive line-scoring compressor, useful as a control |

For backward compatibility, the old experimental names are accepted as
aliases: `c2` → `structure_mmr`, `c3` → `llm_evidence_select`,
`c4` → `structure_llm_summary`. Prefer descriptive names in new
scripts, run IDs, and automation tasks.

```powershell
$env:LOCAL_CODE_AGENT_EMBEDDING_DB = (Resolve-Path "benchmark\results\agent-framework.sqlite").Path
$env:LOCAL_CODE_AGENT_SEMANTIC_MODE = "dense"
$env:LOCAL_CODE_AGENT_PREFETCH = "1"

# Default (no compression-mode variable required):
$env:LOCAL_CODE_AGENT_COMPRESSION_MODE = "structure_mmr"
py -3 -m unittest tests.test_context_compression tests.test_evidence_acquisition tests.test_semantic_embedding -v
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id structure_mmr_nemotron_dense --max-steps 4

# Optional alternative: LLM selects evidence line IDs
$env:LOCAL_CODE_AGENT_COMPRESSION_MODE = "llm_evidence_select"
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id llm_evidence_select_nemotron_dense --max-steps 4

# Optional alternative: structural evidence plus LLM note
$env:LOCAL_CODE_AGENT_COMPRESSION_MODE = "structure_llm_summary"
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id structure_llm_summary_nemotron_dense --max-steps 4
```

Direct invocation also accepts:
`py -3 semantic_agent.py --compression-mode llm_evidence_select --semantic-db <path> --project <path> investigate "question"`.

To reproduce the earlier reasoning baseline without evidence prefetch, set
`$env:LOCAL_CODE_AGENT_PREFETCH = "0"`.

The LLM-assisted modes use at most two additional LLM compression calls per
question; other candidates use deterministic structural compression. All
citations are taken from actually displayed, unchanged source lines.
`structure_mmr` uses language-independent **structural heuristics**, not
a complete AST parser. These modes have not yet been end-to-end benchmarked.

## Benchmark disk space and clean rerun

The benchmark runner now deletes each **private per-case copy** of
`middle-files/code_intelligence.sqlite` after its case finishes. It retains
the single suite-level `_prepared_indexes` master index, the Dense embedding
SQLite DB, all case records, machine JSON, stdout/stderr and summary files.
Use `--keep-case-index` only if you explicitly need per-case SQLite copies.

After fixing source/tests, run a new experiment from the beginning with a
**new run ID**, rather than resuming cases produced by older code:

```powershell
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest tests.test_context_compression tests.test_evidence_acquisition tests.test_semantic_embedding tests.test_benchmark_cleanup -v
$env:LOCAL_CODE_AGENT_EMBEDDING_DB = (Resolve-Path "benchmark\\results\\agent-framework.sqlite").Path
$env:LOCAL_CODE_AGENT_SEMANTIC_MODE = "dense"
$env:LOCAL_CODE_AGENT_PREFETCH = "1"
$env:LOCAL_CODE_AGENT_COMPRESSION_MODE = "structure_mmr"
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id structure_mmr_nemotron_dense_clean --max-steps 4
```

The old `c1_nemotron_dense_prefetch` report is incomplete; do not mix
completed old-case outputs with new source changes or compression settings.
Run the same case set for each alternative compression mode and use distinct
run IDs.

## SQLite / knowledge base maintenance

Storage is distributed across separate, local indexes:

| Store | Default location | Contents |
| --- | --- | --- |
| Global programming knowledge | `%USERPROFILE%\\.local_code_agent\\knowledge\\global_code_knowledge.sqlite` | Versioned programming concepts and relations; override with `LOCAL_CODE_AGENT_KB_PATH` |
| Project search index | `%USERPROFILE%\\.local_code_agent\\index\\*.sqlite` | Per-repository FTS search, rebuildable |
| Code Intelligence | `output\\architecture\\middle-files\\code_intelligence.sqlite` (or `--out`) | Symbols, FTS, relationships and module information |
| Dense embedding index | Explicit `--db`, or configured `LOCAL_CODE_AGENT_EMBEDDING_DB` | Code chunks and embedding vectors, potentially expensive to regenerate |
| Benchmark master index | `benchmark\\results\\<run-id>\\_prepared_indexes\\...` | Cached master index |
| Benchmark case index | `benchmark\\results\\<run-id>\\<case-id>\\middle-files\\code_intelligence.sqlite` | Temporary per-case SQLite copy |
| Bundled knowledge packs | `knowledge\\packs\\*.json` | Versioned seed concepts (not removed by maintenance) |
| Workflow output | `output\\architecture\\middle-files\\workflow\\` | State, audit, cached results (not removed by maintenance) |

Use the new safe maintenance command. **Without `--apply`, it only reports
paths, SQLite integrity/free pages, potential reclaimable space, and completed
benchmark case copies.** With `--apply`, it executes `PRAGMA optimize` and
`VACUUM` on available known SQLite databases when spare disk space permits,
and removes **only** private benchmark SQLite copies that have a saved
`runner_record.json` with `machine_result_available=true`. It does not
delete any SQLite rows from canonical databases or erase knowledge.

```powershell
# Audit (no writes)
py -3 maintenance.py

# Free disk from completed-case index copies first, without VACUUM
py -3 maintenance.py --apply --no-vacuum

# After ensuring sufficient space and stopping the agent, optimize SQLite
py -3 maintenance.py --apply --no-clean-copies

# Override custom locations when needed
py -3 maintenance.py --output "D:\\AgentOutput\\architecture" --embedding-db "D:\\AgentOutput\\qwen3_embed.sqlite"
```

If a database is currently in use, stop benchmark runs/agents before VACUUM.
SQLite optimization requires temporary free disk space; the command skips
VACUUM when free space is insufficient. For source-code changes, rerun the
incremental indexer rather than trying to guess and delete individual rows.
This is storage maintenance, **not** semantic deduplication or knowledge
garbage collection.

Run offline tests:

```powershell
py -3 -m unittest tests.test_maintenance -v
```

## Automatic setup and index recovery after deleting output/results

The setup script now persists **default** local semantic settings (without
overwriting deliberate existing overrides):

| Environment setting | Default | Purpose |
| --- | --- | --- |
| `LOCAL_CODE_AGENT_EMBEDDING_DB` | Absolute `<repo>/benchmark/results` directory | Directory holding `<source-repo-name>.sqlite`; do not point to a deleted individual file |
| `LOCAL_CODE_AGENT_SEMANTIC_MODE` | `dense` | Select Dense retrieval |
| `LOCAL_CODE_AGENT_COMPRESSION_MODE` | `structure_mmr` | Default structural/MMR compression |
| `LOCAL_CODE_AGENT_PREFETCH` | `1` | Read verified source excerpts before reasoning |
| `LOCAL_CODE_AGENT_SEMANTIC_MODEL` | `qwen3-embedding:0.6b` | Embedding model used by benchmark auto-recovery |
| `LOCAL_CODE_AGENT_SEMANTIC_DIMENSIONS` | `1024` | Expected embedding dimensionality |

On Windows PowerShell:

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
.\setup.ps1 -PullEmbeddingModel
py -3 -m unittest tests.test_index_recovery tests.test_semantic_embedding tests.test_context_compression -v
```

`setup.ps1` also retains its existing `-PullModel`, `-WithTreeSitter`,
`-RunTests`, `-ProcessOnly` and `-OllamaMode` flags. Environment defaults
persist at Windows User scope unless `-ProcessOnly` is supplied; open a fresh
terminal after setup if necessary. `-PullEmbeddingModel` downloads the
embedding model **only when explicitly requested**. It is not needed if
the model has already been installed.

**Recovery rules:** The benchmark runner automatically rebuilds the
per-suite `code_intelligence.sqlite` when missing. For
`--agent semantic_agent.py`, it also checks the Dense embedding index before
each case, and generates `agent-framework.sqlite` (or `jdbi.sqlite`) from
the pinned source checkout when missing. An existing matching Dense index is
reused; an existing unreadable or project-mismatched index produces an
actionable error rather than being silently overwritten. Direct calls to
`semantic_agent.py investigate` also auto-rebuild missing Dense indexes;
`semantic_retrieval.py index` rebuilds its missing Code Intelligence
prerequisite from the supplied project and output location.

If `output/` and `benchmark/results/` were deleted, the complete indexing
pipeline can therefore recover on first use provided (1) source checkout is
still present; (2) Ollama runs locally with the embedding model installed;
(3) available disk space is sufficient. The first request may spend substantial
time re-embedding all chunks. Existing custom paths are retained by setup;
if an old custom environment variable points to a deleted file, correct it
manually or rerun setup with that override cleared.

Example fresh benchmark:

```powershell
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id structure_mmr_fresh_01 --max-steps 4
```

This does not recover deleted **benchmark reports**, **knowledge-base JSON
packs**, or user-authored content; it regenerates only reconstructible indexes.
The global programming knowledge SQLite is initialized during setup from
bundled packs, but those packs must remain available. Index rebuilds never use
gold answer labels.

## Limitations

- No evidence of improved Recall@K exists until the local Ollama model and pinned benchmark have been run. The repository tests use fake embeddings only.
- Cosine similarity is an exact linear scan of cached chunk vectors, which may be slow on exceptionally large codebases. This MVP has no ANN vector index or trained reranker.
- The default 48-line chunks are retrieval windows, **not precise answer citations**. The agent must still read actual line-numbered source. For tighter windows, experiment with a separate 24–32-line-chunk DB.
- Reindex after source changes. Do not move a SQLite index to an unrelated source root.
- Memory use grows with chunk count; model memory and vector-index disk use are independent. Keep the local Ollama server on loopback.
- This experimental branch depends on `improve/retrieval-stage-audit-v512`; it does not change `main` until reviewed and merged.
