# v4.9 — Local Code Intelligence & Investigation

This adds a *read-only* investigation layer to v4.8. It does **not** turn lexical matching into a fully resolved Java/ActionScript runtime call graph. The default workflow requires only the Python standard library, no cloud API, and no extra LLM calls.

## Architecture and CLI

Run from the extracted `local_code_agent` directory, replacing the Windows project path:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" intelligence --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" symbol OrderService --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" trace processOrder --depth 3 --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" impact saveOrder --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" flows --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" clusters --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" history --file backend/OrderService.java --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" diff-impact --base HEAD~1 --head HEAD --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Where is order processing implemented?" --budget 1200 --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Explain order processing" --budget 1200 --out "D:\AgentOutput\architecture"
```

`intelligence` is run **once initially** and again whenever source changes. It incrementally reprocesses only changed files (using path/size/mtime metadata); source text remains local in an SQLite FTS5 index. Rebuilding incoming symbol references after source changes is performed deterministically. The index lives at `OUTPUT/middle-files/code_intelligence.sqlite`, not in the scanned project.

### Features incorporated

| Inspiration | Implemented locally | Current limitations |
|---|---|---|
| Serena, codebase-index | Symbol/definition/reference inventory; optional Tree-sitter parser adapter and lexical fallback | No bundled LSP; name-only resolution can miss overloads/dynamic dispatch |
| GitNexus | Candidate caller/callee links; static architecture relations and reverse impact traversal | FE RemoteObject → Java endpoint is only a candidate without explicit matching |
| Aider | Limited context evidence retrieval (`--budget`), no LLM requirement for indexing | Lexical BM25 ranking, not sophisticated repository PageRank |
| codebase-index | Incremental SQLite FTS5, file metadata tracking, code search | Fingerprint uses size and mtime; timestamp-preserving edits need index rebuild |
| GitNexus | Weakly connected clusters and entrypoint/SQL evidence inventory | Clusters are structural, not proven functional/business bounded contexts |
| dev-agent | Offline local Git history and Git-diff file impact | Commit descriptions reflect author text, not verified intent |
| dev-agent | Optional local symbol embeddings and vector similarity | Not full-repo embedding search; bounded, opt-in, requires local Ollama embedding model |

### Optional local AST adapter

When `tree_sitter_language_pack` is installed in the local Python environment and the corresponding grammar supports Java/ActionScript, AST-based declaration spans are also stored. Otherwise, built-in conservative lexical extraction works with no dependencies. **Tree-sitter is not bundled; language support depends on the installed package and version.** This release does not bundle Java LSP, fully resolve Java overloads, or build a runtime call graph. AST span extraction improves location accuracy but is not a semantic type resolver.

### Optional local vector search

```powershell
ollama pull nomic-embed-text
py -3 agent.py --project "D:\Work\LegacyProject" vectorize --embedding-model nomic-embed-text --max-symbols 200 --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" semantic "find the order validation function" --embedding-model nomic-embed-text --out "D:\AgentOutput\architecture"
```

The embedding endpoint is restricted to HTTP loopback (`localhost`, `127.0.0.1`, `::1`), is off by default and indexes at most 1,000 symbol signatures per invocation. It does not embed every line or upload source. The default Ollama generation model remains `qwen3:8b` with `num_ctx=2048`; the optional embedding model is separate.

## Evidence integrity and security

- Results distinguish candidate/static links from runtime-verified links.
- `trace`, `impact`, and `flows` output include file/line evidence when available, not fabricated call edges.
- SQL tables and HTTP routes are syntax matches; dynamic SQL and dependency injection may not resolve.
- `investigate` sends only a bounded set of ranked local source evidence to Qwen. Treat local generated output and SQLite as sensitive source-derived data.
- Existing v4.8 `architecture`, module reports and `.drawio` outputs are preserved.
- Source queries are read-only; Git operations are `log` and `diff` only.

### FE → BE → SQL candidates

The `flows` command compares Flex `RemoteObject` destinations or IDs against discovered backend Java classes and mapper IDs. Only lexical matching is used, with `heuristic-unverified` confidence and original `file:line` citations. It does **not** prove a BlazeDS endpoint actually resolves to that class, nor that a specific runtime request reaches the matched SQL mapper.
