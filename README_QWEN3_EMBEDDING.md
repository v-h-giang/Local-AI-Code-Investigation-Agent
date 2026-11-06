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

## Comparing compression modes after the completed structure_mmr run

The 20-case `structure_mmr_nemotron_dense_clean` result is already a
historical measurement. **Do not modify or resume it with new code.**
New benchmark runs now record `semantic_settings` (retrieval mode,
compression mode, prefetch, embedding model and dimensions) inside
`run_config.json`. They reject resume attempts with mismatching settings.
Older run configs without this section are accepted for backward compatibility
but print a warning; they cannot prove their original settings.

`structure_llm_summary` now reserves a small slice of each source-excerpt
budget for the unverified LLM note; if a note is invalid, the full original
`structure_mmr` excerpt budget is restored. This is a code change, so do not
compare it as if it were the prior C4 version.

Run the unit tests first:

```powershell
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest tests.test_context_compression tests.test_evidence_acquisition tests.test_index_recovery tests.test_semantic_embedding tests.test_benchmark_cleanup -v
```

Run **new** experiments under the same frozen source commit, embedding index,
Nemotron model and maximum 4 tool steps:

```powershell
$env:LOCAL_CODE_AGENT_SEMANTIC_MODE = "dense"
$env:LOCAL_CODE_AGENT_PREFETCH = "1"
$env:LOCAL_CODE_AGENT_COMPRESSION_MODE = "llm_evidence_select"
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id llm_evidence_select_nemotron_dense_01 --max-steps 4

$env:LOCAL_CODE_AGENT_COMPRESSION_MODE = "structure_llm_summary"
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id structure_llm_summary_nemotron_dense_01 --max-steps 4
```

To verify each new run's saved configuration:

```powershell
Get-Content benchmark/results/llm_evidence_select_nemotron_dense_01/run_config.json
Get-Content benchmark/results/structure_llm_summary_nemotron_dense_01/run_config.json
```

Compare gold-span hits, observed gold-file hits, validity, elapsed time,
prefetched files and per-case answer grounding. Metrics alone do not prove
final answer correctness; review the generated `review_template.csv`.
The completed default-mode baseline was 21/99 gold spans and 23/59 gold files,
20/20 successful runs, with 5534.19 seconds overall.

## Experimental agent roadmap (2026-11)

Three independent enhancements have been implemented **behind opt-in flags**
on `feature/qwen3-embedding-retrieval`, not enabled in the existing benchmark
baseline:

1. **Hybrid + Symbol Retrieval**: `hybrid_symbol` adds exact, indexed SQLite
   symbol-name matches as a fourth weighted RRF view alongside filename FTS,
   source-line FTS and Dense. Paths and line ranges are *navigation hints*,
   never automatically valid source evidence. Existing `hybrid` / `dense`
   modes are unchanged.
2. **Agent Memory / Context Compaction**:
   `LOCAL_CODE_AGENT_CONTEXT_COMPACTION=1` compacts **prompt history**
   into prior tool actions, queries and source reference IDs, preserving a
   bounded recent observation. The returned full trace, original source and
   citations remain unchanged. This is NOT persistent cross-session memory,
   not OpenAI's opaque native compaction and not an LLM-generated summary.
   Extend `--max-steps` to 8 or 12 to investigate its utility; baseline
   remains 4.
3. **Claim-level Verification, phase 1 (provenance audit)**:
   `LOCAL_CODE_AGENT_CLAIM_AUDIT=1` identifies each apparent statement's
   citations and distinguishes missing citations, invalid citations,
   references not found in actually shown numbered source and citations
   which exist but whose **semantic support remains unverified**. The
   `claim_verification` object is an audit, NOT correctness scoring or
   independently validated natural-language entailment.

All experimental modes preserve the read-only source investigation contract
and are recorded in new `run_config.json` files.

### Safe offline tests

```powershell
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest tests.test_agent_improvements tests.test_context_compression tests.test_evidence_acquisition tests.test_index_recovery tests.test_semantic_embedding -v
```

### A/B experiments — do not overwrite previous benchmark runs

First isolate retrieval changes on the existing 4-step benchmark:

```powershell
$env:LOCAL_CODE_AGENT_SEMANTIC_MODE = "hybrid_symbol"
$env:LOCAL_CODE_AGENT_CONTEXT_COMPACTION = "0"
$env:LOCAL_CODE_AGENT_CLAIM_AUDIT = "0"
$env:LOCAL_CODE_AGENT_COMPRESSION_MODE = "structure_mmr"
$env:LOCAL_CODE_AGENT_PREFETCH = "1"
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id hybrid_symbol_4step_01 --max-steps 4
```

Then measure compaction and provenance auditing separately on selected
hard cases or the complete suite **with distinct run IDs**:

```powershell
$env:LOCAL_CODE_AGENT_CONTEXT_COMPACTION = "1"
$env:LOCAL_CODE_AGENT_CLAIM_AUDIT = "1"
py -3 benchmark/run.py --suite repocontextbench --agent semantic_agent.py --model nemotron-3.5-bolt:e4b --run-id hybrid_symbol_memory_audit_8step_01 --max-steps 8
```

Do not claim that the second result isolates memory improvements: it also
changes tool-step budget. For causal comparison run an 8-step experiment
with compaction OFF and matching other settings and source/model commits.
Compare Recall@8, observed-file/span recall, citation validity, time,
claim-audit statuses and separately human-scored answer correctness.

### Outstanding work (not implemented or not yet validated)

| Priority | Work | Status |
| --- | --- | --- |
| P0 | Analyze per-case retrieval, evidence and final-answer failures from three completed compression experiments | Pending artifact-level audit |
| P1 | Hybrid + exact symbol RRF | Implemented experimentally, offline test added; 20-case validation pending |
| P2 | Multi-step bounded prompt-history compaction | Implemented experimentally; long-step A/B and quality evaluation pending |
| P3 | Claim-to-source provenance audit | Implemented phase 1; independent semantic entailment grading **not implemented** |
| P4 | Query rewriting, cross-encoder / reranker, call-graph-aware follow-up | Planned, not implemented |
| P5 | Stronger static dataflow/call graph with source-range proof | Planned |
| P6 | Sandboxed optional dynamic tests and reproducible grading of answers | Planned |

Historical results: Dense + `structure_mmr` 21/99 gold spans, 23/59 gold
files, 5534.19 s; `llm_evidence_select` 21/99, 24/59, 5517.60 s;
`structure_llm_summary` 20/99, 24/59, 5812.09 s. All three had valid
citations and 20/20 completed cases. These are **evidence proxies** rather
than answer-correctness rates.

## Offline diagnosis after the Hybrid Symbol 20-case run

Before changing RRF weights or running 8-step Nemotron, compare the saved
`structure_mmr_nemotron_dense_clean` and `hybrid_symbol_4step_01`
investigation records. The following command uses **no inference model**,
does **not** rerun retrieval and does **not** modify source or benchmark
results:

```powershell
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_symbol_retrieval_diagnostics -v
py -3 benchmark/symbol_retrieval_diagnostics.py `
  --baseline structure_mmr_nemotron_dense_clean `
  --variant hybrid_symbol_4step_01 `
  --out benchmark/results/_diagnostics/dense_vs_hybrid_symbol.json
```

The console prints the diagnostic summary, and `dense_vs_hybrid_symbol.json`
contains all 20 case records, top-8 file differences, exact symbol inventory
matches, ranked symbol candidates, observed and final evidence hits, and
non-causal diagnostic flags. **Gold evidence is only read after the archived
run results, for scoring.** No label information influences the agent.

If the pinned Code Intelligence SQLite was deleted, rebuild a dedicated
read-only diagnostic index first:

```powershell
py -3 agent.py --project benchmark/repositories/agent-framework intelligence --out benchmark/results/diagnostic-index
py -3 benchmark/symbol_retrieval_diagnostics.py `
  --baseline structure_mmr_nemotron_dense_clean `
  --variant hybrid_symbol_4step_01 `
  --intelligence-index benchmark/results/diagnostic-index/middle-files/code_intelligence.sqlite
```

The index rebuild only scans the frozen source checkout; it does not rerun
the expensive model inference. Old per-case machine JSON and runner records
must still be available. The tool refuses to compare different model/repo
commits and surfaces missing files explicitly.

**Known observed baseline before case diagnostics:**
Dense + Structure MMR = 21/99 spans, 23/59 files, 5534.19 s;
Hybrid+Symbol = 18/99 spans, 21/59 files, 4417.11 s.
Recall@8 = 32.20% both. This is not enough to blame any individual ranking
stage; inspect per-case diagnostic records first.

## P1 retrieval ablation: isolate FTS and Exact Symbol

The completed 20-case experiment recorded 21/99 Dense gold spans versus
18/99 Hybrid+Symbol gold spans, but that end-to-end comparison changed
**both** the lexical hybrid views and symbol matching. To isolate the
retrieval-stage effects without expensive reasoning-model calls, use the
updated four-arm offline `benchmark/embedding_compare.py`.

This mode runs **one local Ollama embedding inference per question**, not
Nemotron. It reads the existing pinned Qwen3 embedding SQLite and the
saved run's Code Intelligence SQLite; it does not reindex or retrain.

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_embedding_compare -v

# Inspect existing embedding-index locations; choose the SQLite DB
# previously used by semantic_agent.py, not the intelligence index.
Get-ChildItem benchmark,output -Recurse -Filter *.sqlite |
  Select-Object FullName

# Use the SAME embedding DB as hybrid_symbol_4step_01:
$db = $env:LOCAL_CODE_AGENT_EMBEDDING_DB
py -3 benchmark/embedding_compare.py `
  --from-run hybrid_symbol_4step_01 `
  --embed-db "$db" `
  --out benchmark/results/_diagnostics/dense_hybrid_symbol_ablation.json
```

If `$env:LOCAL_CODE_AGENT_EMBEDDING_DB` is empty or points to a directory,
provide the full exact path to the embedding SQLite. The code validates that
the index belongs to the pinned source root and that model/dimensions match.

The report contains per-case top-8 ranks, `retrieval_views`, actual matched
symbol names from SQLite (diagnostic only), exact-symbol gold-file overlap,
line-window overlap, `dense_to_hybrid` and `hybrid_to_symbol` deltas.
It is **not** final evidence or answer accuracy. Gold spans are accessed
only after all retrieval rankings are generated. Existing model and
retrieval algorithms remain untouched; the branch's `main` remains
unmodified.

Interpretation:
- If `hybrid` degrades relative to `dense`, investigate filename/FTS
  fusion before attributing loss to symbols.
- If `hybrid_symbol` degrades relative to `hybrid`, investigate common
  symbol names, missing module/language scope, and symbol-hint priority.
- If retrieved gold-file recall improves but final observed/cited span
  recall degrades, diagnose evidence acquisition and tool-step allocation.
- Do not tune weights against the 20 gold cases and then claim a clean
  benchmark improvement; use held-out cases or independent validation.

## Opt-in Symbol Confidence Gating (P1.1)

The 20-case retrieval ablation found: Dense Recall@8=19/59,
Hybrid=21/59 (35.59%), Hybrid+Exact Symbol=19/59.
To isolate the noisy symbol boost, `hybrid_symbol_gated` is an **opt-in**
experimental mode. Existing `dense`, `hybrid`, `hybrid_symbol`, and
RRF weights are unchanged. Only the symbol candidate view changes:
the gate accepts backtick identifiers, call syntax, snake_case,
camelCase, and mixed-case abbreviations; excludes Markdown headings
and generic prose terms. This deliberately favors precision over recall
for natural-language descriptions of symbols.

Run local regression tests, then a paired ablation (requires the existing
Qwen3 embedding SQLite and local Ollama; no Nemotron generation):

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest tests.test_agent_improvements benchmark.tests.test_embedding_compare -v
py -3 benchmark/embedding_compare.py `
  --from-run hybrid_symbol_4step_01 `
  --embed-db "benchmark/results/agent-framework.sqlite" `
  --out "benchmark/results/_diagnostics/gated_symbol_ablation.json"
```

The output contains **five** arms including `hybrid_symbol_gated`.
To send a compact summary to ChatGPT:

```powershell
$r = Get-Content "benchmark/results/_diagnostics/gated_symbol_ablation.json" -Raw | ConvertFrom-Json
$r.summary | ConvertTo-Json -Depth 6
```

Decision criterion: gated symbol Recall@8 should recover at least
21/59 gold files (35.59%), while tracking @20 and chunk overlap for
regression. The exact result is unknown until the experiment executes.
Do not tune gating using benchmark gold labels; validate on held-out
repositories/cases before claiming generalization.

To run the gate in a future end-to-end experiment, explicitly select
`LOCAL_CODE_AGENT_SEMANTIC_MODE=hybrid_symbol_gated`. Do not alter
`main` or claim evidence quality is verified from retrieval metrics.

## P1.2 Hybrid-first Scoped Symbol Resolution (experimental)

The 20 RepoContextBench natural-language cases gave gated symbol retrieval 21/59
gold files at top 8, identical to Hybrid, with zero gated symbol matches.
This is a no-regression result, NOT a symbol-retrieval improvement.

New opt-in mode: `hybrid_symbol_scoped`. It uses the existing Hybrid ranking
unchanged and annotates matching multi-token symbol names inside its top 12
files (existing read-only SQLite). Explicit code identifiers may rescue up
to two unambiguous definition paths; explicit Python/.NET/Fortran query
scope restricts eligible paths. Heading-only names are ignored.
Natural-language symbol hints do not change rankings or Dense line windows.
They are navigation hints only, not evidence/citations; the acquisition
compressor does not yet consume these annotations.

Tests (no Ollama):

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_scoped_symbol_resolution `
  benchmark.tests.test_embedding_compare tests.test_agent_improvements -v
```

Paired offline retrieval run (one Qwen3 Embedding call per case; no Nemotron):

```powershell
py -3 benchmark/embedding_compare.py `
  --from-run hybrid_symbol_4step_01 `
  --embed-db "benchmark/results/agent-framework.sqlite" `
  --out "benchmark/results/_diagnostics/scoped_symbol_ablation.json"
$r = Get-Content "benchmark/results/_diagnostics/scoped_symbol_ablation.json" -Raw | ConvertFrom-Json
$r.summary | ConvertTo-Json -Depth 6
```

The report contains a sixth arm: `hybrid_symbol_scoped`, with additional
`scoped_vs_hybrid` per-case deltas. The target control remains Hybrid
file recall@8=21/59 (35.59%); Dense retains stronger top-20 coverage.
Do not interpret candidate overlap as observed/cited gold evidence.

## P1.3 Symbol hint opportunity audit (no-model, read-only)

After scoped symbol mode showed the same 21/59 top-8 gold files and
26/99 chunk overlaps as Hybrid, with hints in 9/20 cases, first test
whether those hints actually overlap gold source spans. Do not let them
replace Dense source windows before measuring their usefulness.

The following command replays saved Hybrid top-8 candidate paths using
the pinned existing intelligence SQLite (no Ollama, no embedding query,
no Nemotron, no source modification) and compares existing source windows
with hypothetical +/-8-line windows around local scoped symbols:

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_scoped_hint_diagnostics `
  benchmark.tests.test_scoped_symbol_resolution -v
py -3 benchmark/scoped_hint_diagnostics.py `
  --from-report "benchmark/results/_diagnostics/scoped_symbol_ablation.json" `
  --out "benchmark/results/_diagnostics/scoped_hint_opportunity.json"
```

The console prints only summary, including symbol-hint count, number of
hints on gold files, exact-line gold overlap, +/-8 window overlap, and
**new gold spans found by union of saved Hybrid top-8 source windows
with hypothetical symbol windows**. Note that this last metric is top-8
window opportunity, not the previous top-20 retrieval chunk overlap,
and neither is proof of actual evidence observation/citation.

Decision gate: if no new gold spans overlap with source symbol windows,
do NOT wire hints into evidence acquisition yet. If multiple cases show
new matches, implement a separate opt-in *additive* multihint reader,
preserving original Dense windows and provenance, then A/B it.

## P1.4 Dense-preserving Hybrid fusion (offline-only)

The saved 20-case analysis found Hybrid recall@8=21/59 (35.59%),
Dense recall@20=37/59 (62.71%), and Hybrid recall@20=34/59
(57.63%). Scoped hints supplied one hypothetical extra gold-span window
in case 0009 (auto_retry.py). Do not feed symbol hints into the evidence
reader until there is stronger evidence of value.

An isolated offline candidate fusion `hybrid_dense_tail` now:
- Keeps the first 8 Hybrid candidates and their line windows unchanged.
- Appends distinct Dense candidates to positions 9+ with original Dense windows.
- Uses remaining Hybrid-tail candidates only if space remains.
- Makes no model call other than the original shared Qwen3 query, and
  never reads gold labels for ranking.

This intentionally tests capacity allocation in top20; it does not imply
improved final-answer correctness. The agent's normal discover_files call
typically requests only eight candidates, so the Dense tail is NOT enabled
as a new runtime agent mode pending offline evidence and agent-budget review.

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_dense_preserving_fusion `
  benchmark.tests.test_embedding_compare -v
py -3 benchmark/embedding_compare.py `
  --from-run hybrid_symbol_4step_01 `
  --embed-db "benchmark/results/agent-framework.sqlite" `
  --out "benchmark/results/_diagnostics/dense_tail_ablation.json" `
  --summary-only
```

Only the compact summary is printed; the full case-level JSON is still
saved. Compare `hybrid_dense_tail` against Hybrid at top8/top20 and Dense
at top20, including chunk-window overlap. A fusion that sacrifices
many top20 files or window hits should not proceed to agent integration.

## P1.4 follow-up: fixed-allocation tail fusion alternatives

Measured results of the previous 20-case experiment: Hybrid 21/59 gold
files at top 8, 34/59 at top 20 and 26/99 chunk overlaps; Hybrid
plus Dense-first tail 21/59 at top 8, 35/59 at top 20 and 29/99
chunk overlaps. Dense alone: 37/59 at top 20 and 30/99 overlaps.
Three cases gained and three lost at least one gold file at top 20
with Dense-first allocation; investigate per-case losses before promotion.

New offline-only, fixed (not gold-tuned) alternatives:
- hybrid_interleaved_tail: preserve Hybrid top 8; interleave one
  unique Dense candidate and one Hybrid-tail candidate thereafter.
- hybrid_rrf_tail: preserve Hybrid top 8; use equal-weight RRF(k=40)
  for the remaining Hybrid and Dense candidates; preserve Dense source
  windows for tail files found by Dense.

Neither alters the runtime agent, nor calls Nemotron. All modes share
one Qwen3 embedding query per case. Source labels are used only after
retrieval. Do not select weights or final architecture based solely
on these 20 diagnostic cases; require independent validation.

Run on Windows PowerShell:

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_dense_preserving_fusion `
  benchmark.tests.test_embedding_compare -v
py -3 benchmark/embedding_compare.py `
  --from-run hybrid_symbol_4step_01 `
  --embed-db "benchmark/results/agent-framework.sqlite" `
  --out "benchmark/results/_diagnostics/tail_strategy_ablation.json" `
  --summary-only
```

Expect nine comparative modes including hybrid_interleaved_tail and
hybrid_rrf_tail. A candidate file hit or chunk window overlap is NOT
an observed/cited gold evidence span. The 8-file agent runtime discovery
limit remains an outstanding integration constraint.

## P1.5: Additive top-eight multi-window opportunity audit

The P1.4 comparison over 20 cases found Hybrid+Dense-first tail yields
21/59 Recall@8, 35/59 Recall@20, and 29/99 chunk-overlap hits.
Interleaved and RRF tails also yield 35/59 Recall@20 but only 27/99
chunk-overlap hits. Dense alone yields 37/59 Recall@20, 30/99 spans.
Tail-only improvements do NOT reach the agent when its file discovery
is limited to 8 candidates.

P1.5 therefore tests a different, strictly offline hypothesis: if a file
is already in Hybrid top8, can an additional distinct Dense window for
that SAME file expose a gold span missed by the saved Hybrid window?
The experiment uses the saved top8 diagnostics only, keeps the original
Hybrid file ranks/windows, and adds at most 4 non-overlapping-ish
candidate Dense windows (at least 8 newly exposed lines each).
The test uses no Ollama and does not read or change repository source.

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_top8_multiwindow_diagnostics `
  benchmark.tests.test_dense_preserving_fusion -v
py -3 benchmark/top8_multiwindow_diagnostics.py `
  --from-report "benchmark/results/_diagnostics/tail_strategy_ablation.json" `
  --out "benchmark/results/_diagnostics/top8_multiwindow_opportunity.json"
```

Only a compact summary is printed, with new hypothetical gold span window
hits and additional source lines. IMPORTANT: saved `top8_diagnostics` only
contains Dense's first eight candidates. This bounds available alternate
windows; it cannot detect a Dense window for a Hybrid top8 file ranked
9-60 by Dense. A window overlap is not read-source evidence or a citation.

Decision: if meaningful additional gold span coverage appears at modest
source-line cost, test an opt-in additive reader separately. Otherwise
prioritize evidence acquisition/LLM tool-step decisions and query retrieval.

## P1.5 follow-up: true multi-chunk same-query ablation

The first saved-report top-8 multiwindow diagnostic returned zero alternate
windows and zero new spans. This is an instrumentation limitation, not a
valid negative test of the multiwindow hypothesis: original
dense_search(..., per_file=1) stores one chunk per file, and Hybrid's
RRF already adopts that same Dense chunk window for matching files.
The saved report also exposes only the first eight Dense files.

An opt-in benchmark flag now collects up to 3 ranked Dense chunks per file
during the SAME cosine-similarity scan and embedding request. The default
dense_search return type, legacy ranking and all pre-existing A/B modes
are unchanged. For Hybrid top-eight files only, we choose up to 4 extra
distinct Dense windows with at least eight previously unread lines,
before reading gold spans. This is a hypothetical navigation audit only.

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_top8_multiwindow_diagnostics `
  benchmark.tests.test_embedding_compare -v
py -3 benchmark/embedding_compare.py `
  --from-run hybrid_symbol_4step_01 `
  --embed-db "benchmark/results/agent-framework.sqlite" `
  --out "benchmark/results/_diagnostics/multiwindow_full_ablation.json" `
  --collect-multiwindow --summary-only
```

Send only the printed `summary.multiwindow_diagnostics` (or the whole
brief summary). Compare `new_gold_span_window_hits` against
`additional_source_lines`. No source is read or cited by this diagnostic;
it is not an agent-run result. Additional per-file chunk collection may
increase peak RAM but performs no extra Ollama query.

## P1.5 zero-result index audit (no Ollama)

The second full-score multiwindow ablation again showed 0 alternates across
20 cases, even with collect_windows_per_file=3. This is not sufficient
to prove that indexed files contain no alternate source chunks. The
zero may come from indexing coverage, similarity order or selection.

Run the following read-only structural test BEFORE another embedding run:

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_multiwindow_index_audit `
  benchmark.tests.test_top8_multiwindow_diagnostics -v
py -3 benchmark/multiwindow_index_audit.py `
  --from-report "benchmark/results/_diagnostics/multiwindow_full_ablation.json" `
  --embed-db "benchmark/results/agent-framework.sqlite" `
  --out "benchmark/results/_diagnostics/multiwindow_index_audit.json"
```

The command prints a short summary plus three examples. It checks the
selector with raw Dense chunk field names before reading a pinned SQLite
index in read-only mode. Structural availability differs from similarity
rank: it cannot prove that the top 3 Dense chunks were distinct enough.
If structurally viable files exist but selected alternates remain zero,
inspect top-3 similarity windows in the saved run before changing reader.

## P1.5 full 20-case window-budget replay

The corrected 20-case --collect-multiwindow experiment produced
17/99 gold-span overlaps in Hybrid top-8 source windows and 23/99
after selecting 80 additional Dense windows in total. Six extra gold
spans in four cases cost 3201 newly exposed source lines (hypothetical
reading, not actual token budget or evidence). All twenty cases had
eligible alternate Dense windows. Ranking metrics remain unchanged.

To avoid another embedding run, evaluate the exact saved window ordering
at budgets 0, 1, 2, 3 and 4 per case. No re-ranking, source reads or
Ollama calls occur. Marginal gold-span yield and newly exposed source
lines are reported for each added window.

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_multiwindow_budget_ablation -v
py -3 benchmark/multiwindow_budget_ablation.py `
  --from-report "benchmark/results/_diagnostics/multiwindow_full_ablation_v2.json" `
  --out "benchmark/results/_diagnostics/multiwindow_budget_ablation.json"
```

Use the marginal table to choose whether a budget of one or two windows
is worth a future separate evidence-reader experiment. Avoid choosing
a general default solely from these 20 already-inspected diagnostic cases.
Neither source-window overlap nor additional-source-line cost asserts that
an agent actually read, cited or used the associated source evidence.

## P1.6 Fixed-budget, source-backed Evidence Acquisition A/B (offline)

P1.5 evaluated 20 already-inspected cases with Hybrid top-8 candidate
windows and additional Dense windows selected without gold information.
At budgets 0/1/2/3/4, hypothetical gold-span coverage was
17/21/23/23/23 out of 99, with 0/804/1575/2415/3201 additional
source lines. The third and fourth windows had zero marginal overlap gain.
These are window-overlap opportunities, NOT observed or cited source.

P1.6 is an independent, read-only, source-backed prefetch experiment:
- Uses the original `acquire_evidence()` for baseline 0.
- Tests 1 or 2 fixed-order alternate Dense windows from the SAVED report.
- Allocates an equal 3000-character total JSON budget for each setting;
  each alternate reserves 500 characters from the baseline budget.
- Reads the frozen source through Repo.read_file and compresses with the
  existing `structure_mmr`, retaining exact line-numbered source text.
- Counts separately visible gold-span lines and citable source_refs
  that actually appear in the returned excerpts; it also reports losses
  caused by reserving context for alternatives.
- Reads gold spans only AFTER all excerpts have been formed.
- Does not call Ollama, patch agent runtime, or claim answer correctness.

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_evidence_window_ablation `
  benchmark.tests.test_multiwindow_budget_ablation -v
py -3 benchmark/evidence_window_ablation.py `
  --from-report "benchmark/results/_diagnostics/multiwindow_full_ablation_v2.json" `
  --max-chars 3000 --per-window-chars 500 --limit 6 `
  --out "benchmark/results/_diagnostics/evidence_window_ablation.json"
```

Only source lines actually returned by the prefetch extracts count here.
Even `source_refs` denotes a line in a prefetch excerpt, not necessarily a
claim supported in a generated answer. Compare net gains, per-case losses,
the number of emitted alternate windows and budget use before advancing
to an opt-in agent-runtime A/B on independent cases.

## P1.6 actual-source A/B result and case diagnostics

The source-backed equal-3000-character prefetch comparison on 20 cases
found 10/99 citable gold spans for EACH of baseline, +1 and +2 extra
Dense windows. Cases with citable gold decreased from 9/20 to 8/20.
At +1, 19 of 20 requested windows emitted and displayed source lines
decreased from 189 to 170; at +2, 36 of 40 emitted and displayed
source lines decreased to 158. Each new strategy gained at least one
case but lost another. The identical aggregate gold-span total DOES
NOT establish equivalent or improved evidence quality. Do not enable
the alternate-window runtime prefetch based on these results.

Investigate gains/losses on SAVED JSON before further expensive A/B runs:

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval
py -3 -m unittest benchmark.tests.test_evidence_window_case_diagnostics -v
py -3 benchmark/evidence_window_case_diagnostics.py `
  --evidence-report "benchmark/results/_diagnostics/evidence_window_ablation.json" `
  --multiwindow-report "benchmark/results/_diagnostics/multiwindow_full_ablation_v2.json" `
  --out "benchmark/results/_diagnostics/evidence_window_case_diagnostics.json"
```

The printed changed-case output provides gold-span IDs gained and lost,
the opportunity IDs found in earlier Dense windows, and baseline versus
experimental serialized budget use. This is a retrospective audit, not a
gold-guided retrieval strategy. It does not read source, run Ollama or
modify the agent. Interpret it before proposing budget allocation changes.

## Limitations

- No evidence of improved Recall@K exists until the local Ollama model and pinned benchmark have been run. The repository tests use fake embeddings only.
- Cosine similarity is an exact linear scan of cached chunk vectors, which may be slow on exceptionally large codebases. This MVP has no ANN vector index or trained reranker.
- The default 48-line chunks are retrieval windows, **not precise answer citations**. The agent must still read actual line-numbered source. For tighter windows, experiment with a separate 24–32-line-chunk DB.
- Reindex after source changes. Do not move a SQLite index to an unrelated source root.
- Memory use grows with chunk count; model memory and vector-index disk use are independent. Keep the local Ollama server on loopback.
- This experimental branch depends on `improve/retrieval-stage-audit-v512`; it does not change `main` until reviewed and merged.
