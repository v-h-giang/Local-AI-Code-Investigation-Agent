# v4.16.1 — Performance fix for the stage after FE/BE/DB diagrams

**Quick start (Windows PowerShell):**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top --out "D:\AgentOutput\architecture"
```

If the previous release appeared to hang immediately after:

```text
[Stack] FE/BE/DB framework evidence and diagrams generated.
```

the following stage was generating the Code Intelligence SQLite/FTS5 index and up to 20 source-backed investigation questions, then optionally asking Qwen to rank them. It previously passed `verbose=False` to indexing, suppressing progress feedback. On large repositories the FTS5 `path UNINDEXED` column led to repeated full scans when removing data by path. Even unchanged repositories rebuilt call relations on every invocation.

**Fixes:**

- FTS5 file deletion uses an indexed rowid-to-path mapping, and the ordinary tables also have per-file B-tree indexes. New files skip unnecessary cleanup.
- Graph resolution uses a precomputed callable-name/language lookup and binary-searches caller positions. The graph is reused when source metadata and architecture edges are unchanged.
- Progress logs show indexing, graph resolution, and each Qwen ranking pass/batch; no more unexplained silence after the Stack step.
- Question ranking still evaluates up to 40 grounded candidates in the first pass, but the second pass focuses on the leading 12 from both categories. For 40 candidates this reduces the Qwen ranking calls from 20 to at most 13, preserving the 2-pass review by default.
- Schema version changes to `49.2`: the first run after this upgrade rebuilds the index once; subsequent runs reuse it when inputs are unchanged. Everything stays under `middle-files/`.

**How to identify the active stage:**

```powershell
Get-Content "D:\AgentOutput\architecture\middle-files\workflow\state.json"
Get-Content "D:\AgentOutput\architecture\middle-files\workflow\call_audit.jsonl" -Tail 10
Get-Item "D:\AgentOutput\architecture\middle-files\code_intelligence.sqlite" | Select-Object Length, LastWriteTime
```

An `architecture` stage marked `completed` while `suggested_investigations` is missing means the process has not reached the completion checkpoint for question generation. A large or updating `.sqlite` indicates indexing activity; it is not by itself proof that the process is healthy. The audit file logs *completed/failed* Ollama calls and may not yet exist while a call is in progress. A local Ollama ranking request can also be slow due to RAM limits.

**Benchmark (synthetic Java project, not the user's repository):** 500 files, ~162,500 lines: cold index 12.51 s → 2.57 s; warm index 0.56 s → 0.013 s. Performance on actual projects varies.

This patch affects static indexing and question ranking, not Java runtime type resolution. Candidate call relations remain heuristic and should not be treated as proven runtime links.


### Auto-run all investigations (CLI update)

`architecture --auto-investigate-top max` investigates every suggested question (up to 20). The maximum 13 local Qwen requests mentioned for ranking is a ranking-stage cost optimization, not the number of questions.
