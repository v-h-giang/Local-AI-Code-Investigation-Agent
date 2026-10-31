# Universal Code Knowledge Base (V5.4–V5.8 incremental foundation)

## Mục lục
- [1. Phạm vi thực tế](#1-phạm-vi-thực-tế)
- [2. Kiến trúc](#2-kiến-trúc)
- [3. Cài đặt](#3-cài-đặt)
- [4. Kiểm tra nguồn đa ngôn ngữ](#4-kiểm-tra-nguồn-đa-ngôn-ngữ)
- [5. Knowledge packs](#5-knowledge-packs)
- [6. Module knowledge](#6-module-knowledge)
- [7. LSP bridge](#7-lsp-bridge)
- [8. Chạy benchmark](#8-chạy-benchmark)
- [9. Giới hạn và hướng nâng cấp](#9-giới-hạn-và-hướng-nâng-cấp)

## 1. Phạm vi thực tế

This implementation provides a **local, extensible knowledge foundation**, not an exhaustive database of all programming facts. Six bundled packs contain 126 curated programming concepts, with aliases and typed relations. Users can add local JSON packs without changing production Python logic.

Version labels describe implementation areas, **not full semantic correctness**:
- **V5.4**: central file/language registry; conservative extra symbol extractors; optional Tree-sitter grammar selection.
- **V5.5**: versioned, provenance-carrying global knowledge SQLite and user-owned JSON packs.
- **V5.6**: per-repository module/language inventory plus bounded concept-assisted candidate ranking.
- **V5.7**: safe import of **already exported** LSP location JSON, not an executable language-server client.
- **V5.8**: explicit local pack updater and existing optional bounded Ollama symbol-vector search. No automatic web updater.

The final answer must still be grounded in **actual repository source lines**. General knowledge, candidate paths, and imported LSP locations are never valid citations by themselves.

## 2. Kiến trúc

```text
Question
  ├─ technology detection / extension registry
  ├─ Global KB ~/.local_code_agent/knowledge/global_code_knowledge.sqlite
  │    └─ versioned local knowledge/packs/*.json
  └─ Per-project index OUTPUT/middle-files/code_intelligence.sqlite
       ├─ files, symbols, FTS5, mentions, relations
       ├─ module_profiles (language, file/symbol counts)
       └─ optional lsp_locations (external, untrusted navigation)
              ↓
        bounded concept hints + FTS5/BM25 + path ranking
              ↓
        read_source, verify line, answer with citations
```

All indexing and pack loading are offline and read-only **with respect to the user's project files**. SQLite index/output files are deliberately written outside the project source tree when the user selects an external output directory. No source code from the inspected repository is executed.

## Recommended everyday workflow

The two ordinary commands are `architecture` and `investigate`. Each
automatically invokes knowledge pack refresh, incremental source intelligence,
and technology/module detection. The combined machine-readable status lives
under `OUTPUT/middle-files/source_context.json`; no separate initial
`knowledge build`, `intelligence`, or `technologies` invocation is needed.
KB concepts are navigation hints, never citations. Failure to write the
optional global KB does not prevent ordinary source indexing.

```powershell
.\.venv\Scripts\python.exe agent.py --project "D:\SourceProject" architecture --out "D:\SourceAnalysis"
.\.venv\Scripts\python.exe agent.py --project "D:\SourceProject" investigate "Where is the Fortran solver?" --out "D:\SourceAnalysis"
```

The additional `knowledge`, `intelligence` and `technologies` commands below
are optional diagnostics or custom-pack management tools.

## 3. Cài đặt

In Windows PowerShell:

```powershell
git pull origin main
.\setup.ps1
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m unittest discover -s benchmark/tests -v
```

`setup.ps1` still uses `-OllamaMode Auto` by default. The curated KB uses Python standard library; no new mandatory dependency or additional Ollama inference is required.

```powershell
.\.venv\Scripts\python.exe agent.py --project . knowledge status
.\.venv\Scripts\python.exe agent.py --project . knowledge build
.\.venv\Scripts\python.exe agent.py --project . knowledge query "How do we resume a workflow?"
.\.venv\Scripts\python.exe agent.py --project . knowledge related workflow.checkpoint
```

To use a different global SQLite file, pass `--kb-path "D:\knowledge\global.sqlite"` or set the environment variable `LOCAL_CODE_AGENT_KB_PATH`.

## 4. Kiểm tra nguồn đa ngôn ngữ

```powershell
.\.venv\Scripts\python.exe agent.py --project "D:\SourceProject" intelligence --out "D:\SourceAnalysis"
.\.venv\Scripts\python.exe agent.py --project "D:\SourceProject" symbol advance --out "D:\SourceAnalysis"
.\.venv\Scripts\python.exe agent.py --project "D:\SourceProject" technologies --out "D:\SourceAnalysis"
.\.venv\Scripts\python.exe agent.py --project "D:\SourceProject" investigate "Where is the Fortran solver initialized?" --non-ai --out "D:\SourceAnalysis"
```

`language_registry.py` identifies common programming and configuration file types, including Fortran, C/C++, Go, Rust, Python, Java, C#, JavaScript/TypeScript, Kotlin, Swift, SQL, YAML, XML, and many others. A file that is indexed as text is **not** necessarily fully understood by the AST parser.

`universal_symbols.py` provides deliberately conservative declarations for selected languages, including Fortran modules and subroutines. Optional Tree-sitter support is best-effort; language pack availability varies.

## 5. Knowledge packs

Bundled seeds: [knowledge/packs/](knowledge/packs/) (six versioned packs: core, languages/systems, backend/cloud, security/testing, data/frontend/AI, and legacy/enterprise).

Example schema (illustration, not an additional pack):

```json
{
  "schema_version": 1,
  "pack_id": "example-code-pack",
  "version": "1.0.0",
  "license": "CC0-1.0",
  "concepts": [
    {
      "id": "example.recovery",
      "domain": "distributed-systems",
      "label": "recovery checkpoint",
      "description": "Technical concept and its search synonyms.",
      "source": "curated-local",
      "aliases": ["recovery checkpoint", "restore point"]
    }
  ],
  "relations": []
}
```

Save local pack files as UTF-8 JSON in a directory and import explicitly:

```powershell
.\.venv\Scripts\python.exe agent.py --project . knowledge build --pack-dir "D:\KnowledgePacks"
```

Packs are validated, hashed, and replaced transactionally by `pack_id` when contents change. **No source URL is fetched automatically**. Invalid relations or fields fail with an error. Importing only one folder does not delete other existing packs from the DB.

A concept's `source` field records provenance; it does not prove that a repository implements the concept.

## 6. Module knowledge

The per-project index includes `module_profiles`, computed from actual indexed paths and symbols. This is descriptive metadata, not a generated architectural claim. For instance, the tool can show how many Fortran files or methods are present without assuming any actual runtime flow.

The source database remains compatible with existing command-line investigation modes; global KB signals add only a small bounded path ranking boost and cannot create source citations.

## 7. LSP bridge

V5.7 implements a **pre-exported JSON bridge**; it does not run or install language servers. LSP input is not treated as verified source evidence.

Input format:

```json
[
  {
    "symbol": "advance",
    "uri": "file:///D:/SourceProject/src/solver.f90",
    "range": { "start": { "line": 14, "character": 0 } }
  }
]
```

LSP line numbers are zero-based; the repository index uses one-based line numbers. Only existing files inside the configured project are accepted. External URLs, nonexistent files and out-of-range locations are rejected.

```powershell
.\.venv\Scripts\python.exe agent.py --project "D:\SourceProject" lsp-import "D:\Export\locations.json" --out "D:\SourceAnalysis"
.\.venv\Scripts\python.exe agent.py --project "D:\SourceProject" lsp-symbol advance --out "D:\SourceAnalysis"
```

The bridge never launches an LSP server or executes inspected code; it is an opt-in adapter for information obtained separately. A future LSP client would need explicit trust boundaries and versioned server capabilities.

## V5.9 — Two-pass concept retrieval

A query now follows two independent paths:

1. The **original search** uses exact question terms and bounded FTS5/BM25 as
   before. It remains the strongest ranking signal.
2. A **Knowledge Base expansion pass** selects up to six safe single-token
   aliases from matched concepts. Those tokens search FTS5 separately and
   find indexed symbol names (including CamelCase names).
3. Files that match KB terms, but not the original question, are admitted
   as *candidate paths*. The ranker combines original term, filename, symbol,
   and KB evidence, then adds at most one hop of static/heuristic source-graph
   neighbors from leading file candidates.
4. No filename, KB concept, symbol hint, or graph association is a citation.
   Final output needs an actual source line validated by the investigation.

The graph cannot prove runtime behavior. The limited aliases and caps trade
off precision and recall; this is not LLM semantic embedding search.
The legacy deterministic ranker is preserved as `strategy="baseline"` so
the same frozen repository/index can be used for a paired A/B comparison.

```powershell
.\.venv\Scripts\python.exe benchmark\inspect_candidates.py --from-run universal_kb_offline_fresh_1 --suite repocontextbench --compare --summary-only --limit 20
```

The `comparison` output reports baseline, V5.9, deltas, improved cases
and regressed cases at 8 and 20 candidates. It does **not** run Ollama, nor
does it supply the benchmark gold evidence to the production retriever.
The actual 20-case recall must be measured on the user's local prepared index.

## 8. Chạy benchmark

First run the test suites shown above. The existing 20 RepoContextBench cases and 10 StackRepoQA cases remain unchanged; no benchmark gold labels are embedded into the knowledge packs or retrieval logic.

For offline candidate diagnostics using an existing prepared index:

```powershell
.\.venv\Scripts\python.exe benchmark\inspect_candidates.py --from-run retrieval_v51_gpu_smoke --suite repocontextbench --limit 20 --summary-only
```

Compare micro/macro recall at 8/20 against the previous run before benchmarking Qwen. This code change **has not yet been validated on the user's Windows environment**; do not assume accuracy or performance improvements until measured.

## 9. Giới hạn và hướng nâng cấp

- All-language *recognition* is not all-language semantic analysis; AST/LSP coverage varies by grammar/server.
- Domain pack seed is small. Extend from versioned official references and curate ambiguous aliases.
- No live language server client is bundled. LSP export import is the supported V5.7 subset.
- Local pack updates require an explicit command; automated Internet retrieval, signature verification, and upstream diff review are future work.
- Existing optional `vectorize`/`semantic` Ollama modes remain separate. No always-on embeddings are required.
- Graph edges from lexical mentions remain candidates unless explicitly verified.
- Cross-domain benchmark testing, including unseen repositories, is essential to avoid overfitting.
