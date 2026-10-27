# v4.16 — One-switch automatic local workflow

The `architecture --auto-investigate-top` command now starts a **complete local-only investigation pipeline with one flag**. You no longer need to specify the number of investigations, `--ai-suggestions`, `--synthesize`, review counts, or LLM-call budget for the recommended workflow.

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top --out "D:\AgentOutput\architecture"
```

This command invokes, in order:

1. **Static architecture scan** and incremental code-intelligence index.
2. **Up to 20 grounded question candidates** in exactly two groups: Business Flows and Technical Architecture. Local Qwen reviews/ranks the candidates (two passes); it may not invent new source symbols or citations.
3. **Top five investigations** by default, with one bounded Qwen evidence-review pass each. Each investigation produces human-readable Markdown, SVG and Draw.io, and annotated architecture diagrams when originals exist.
4. **Hierarchical local synthesis**, including two evidence-review passes, producing `system_knowledge_report.md`, `system_knowledge.drawio` and `system_knowledge.svg`.

Everything uses the local `qwen3:8b` Ollama instance at `127.0.0.1:11434` by default. Model calls are **sequential** and cacheable; the automatic workflow defaults to **160 uncached model calls per run**, with the existing on-disk checkpoints. Set `--max-llm-calls N` explicitly to override this cap. The `--num-ctx 2048` global default is unchanged to limit RAM pressure. No cloud AI, Node.js or new runtime dependency is introduced.

The command with an explicit number still works:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 10 --out "D:\AgentOutput\architecture"
```

`N` may be 1–20; five is the default when the flag is supplied without a number. If the source provides fewer valid candidates, only those candidates are investigated. `architecture` **without** `--auto-investigate-top` remains a deterministic, non-AI scan with a maximum of 20 source-backed suggestions. The legacy `architecture --synthesize` and `architecture --ai-suggestions` options remain valid.

## Disable individual steps with `--non-*`

| Flag after `architecture` | Effect |
|---|---|
| `--non-synthesize` | Disable the final system-wide synthesis (and its LLM calls). Alias: `--non-synthesis`. |
| `--non-ai-suggestions` | Disable local Qwen ranking/review of the 20 source-grounded candidate questions; use deterministic ranking. |
| `--non-review` | Skip all extra reviewer/critic passes; initial question ranking still runs once, investigations and synthesis still execute. |
| `--non-investigation-review` | Skip only the Qwen review after each investigation. |
| `--non-synthesis-review` | Skip only the final synthesis critique. |
| `--non-markdown` | Skip per-investigation `result.md` (does not suppress architecture or final synthesis reports). |
| `--non-diagram` | Skip per-investigation diagram generation (does not suppress the architecture and synthesis diagrams). |
| `--non-update-drawio` | Do not generate annotated `.investigated.drawio` variants. Original Draw.io files are always left intact unless `--overwrite-drawio` is explicitly requested. |

Old `--no-ai-suggestions`, `--no-markdown`, `--no-diagram`, `--no-update-drawio` remain compatible aliases. Advanced numeric settings such as `--question-review-rounds`, `--investigation-review-rounds`, `--synthesis-review-rounds`, `--max-llm-calls`, `--model` and `--num-ctx` are still accepted.

**Example: scan, rank and investigate without final synthesis or any diagram updates:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top --non-synthesize --non-update-drawio --out "D:\AgentOutput\architecture"
```

**Example: Top 3, local AI ranking but no extra Qwen critic passes:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 3 --non-review --out "D:\AgentOutput\architecture"
```

**Example: fully static survey (no Ollama needed):**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

The automatic mode does **not** activate `--ai-summary` per module by default: it already performs hierarchical AI synthesis downstream, and eager LLM summarization of every module can exhaust the bounded call budget on very large repositories. You can opt into it with `--ai-summary` when needed.

## Outputs and failure behavior

Human-facing reports and editable diagrams remain in the output root and `investigations/`. **All JSON, CSV, SQLite, caches, state manifests and checkpoints remain under `middle-files/`**, including:

- `middle-files/investigations/*.json` and `manifest.json`;
- `middle-files/workflow/config.json`, `state.json`, `call_audit.jsonl`, `llm_cache/`;
- `middle-files/synthesis/` with the claim ledger, checkpoints and review logs.

The CLI JSON now includes `workflow_settings` for automatic investigation so the actual defaults/negative overrides are auditable. A failed investigation or incomplete synthesis remains visible; exit code 2 indicates a partial or unsuccessful automatic run. Checkpoints permit resuming. Citations and diagram edges refer to source-backed static evidence; they **do not prove runtime execution**.

Tests use a mocked local model rather than a live benchmark on a large legacy repository. Protect the output directory as sensitive source-derived material and do not commit `middle-files/` to a repository.
