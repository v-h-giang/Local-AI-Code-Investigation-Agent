# v4.12 — Iterative Qwen Investigation (local, read-only)

In `investigate`, Qwen is ON by default. New workflow:

1. Qwen builds a bounded JSON plan (intent, search terms, candidate symbols).
2. Python executes an allowlisted local investigation tool based on that plan.
3. Qwen examines the previous tool observation and either selects another tool or finishes. Invalid JSON or denied tools use a deterministic, read-only fallback.
4. Qwen synthesizes the answer only when `file:line` evidence is available.

Allowed read-only tools: `search` (SQLite FTS5), `symbol`, `trace`, `impact`, `flows`, `history`, `clusters`. All graph-based relationships remain static/heuristic, not runtime proof. `history` uses the local Git repository only. No shell, arbitrary file access, writes, or external network tool is offered to Qwen.

## Usage

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" intelligence --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Nếu sửa saveOrder có ảnh hưởng màn hình nào?" --max-steps 4 --budget 1200 --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" investigate "OrderService" --non-ai --out "D:\AgentOutput\architecture"
```

`--max-steps`: 1–6 read-only tool calls, default 4. Source snippets are truncated and the cumulative evidence supplied to the model is bounded by `--budget`. Tool audit trail appears in JSON response under `steps`; `source_citations` lists evidence locations. Unsupported citations in the Qwen answer are separately flagged.

The Qwen API normally receives one initial planning call, a bounded number of decision calls and one synthesis call. There is no guarantee of runtime execution-flow accuracy, Java type/overload resolution, or complete source coverage. Tests use a mocked model, **not** a live Ollama benchmark.
