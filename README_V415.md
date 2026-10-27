# v4.15 — Local multi-loop workflow across all phases

> **Lưu ý:** Tài liệu này mô tả hành vi của bản v4.15. Từ v4.16, `architecture --auto-investigate-top` không cần số và tự bật synthesis; xem [README_V416.md](README_V416.md).

**All inference is local via Ollama** (`http://127.0.0.1:11434` by default). There is no cloud provider, new server, Node.js requirement, execution tool, or database connection. The read-only tools continue to operate on source files; local reports/checkpoints are written only to the chosen `--out` directory. Python standard library is sufficient.

## What changed

`architecture` → *optional Qwen-backed* question ranking → `investigate` → *local evidence critic loop* → recursive `synthesize`.

- **Question discovery:** Python identifies candidate questions from symbols, endpoints, SQL and dependency relations. With `--ai-suggestions`, Qwen reviews batches of **four candidates**, for up to **three passes** (two by default). The model can score only the candidate IDs supplied by Python; it **cannot invent new source paths, classes, or questions**. Python balances the final list into the same two groups: **Business Flows** and **Technical Architecture**, with at most 20 final questions. No evidence means no question. Ranking failures fall back to evidence-based ordering and are recorded in JSON.
- **Automatic investigation:** `architecture --auto-investigate-top N` now automatically enables local Qwen ranking before selecting the top N, unless `--no-ai-suggestions` is supplied. Each investigation uses the v4.14 diagrams and a bounded Qwen planner/tool loop plus **one evidence reviewer pass by default**, which can request an additional allowlisted read-only tool, provided the existing `--max-steps` budget is not exceeded.
- **Final synthesis:** `synthesize` loads source-backed architecture/module summaries plus completed investigation results. Python validates every `file:line` to a real file *and a valid line number*. Qwen extracts small chunks, reduces by module, groups modules by **static graph connected components** and combines group summaries. Two configurable critic passes review the outcome. Existing code-derived relationships are **not claimed as runtime proof**.
- **Global model budget and resumability:** a single Ollama model is called sequentially. `--max-llm-calls 80` (default) is a hard cap for actual uncached calls **within a CLI run**. Repeat calls/checkpoints are cached locally using a content/model/context hash. A new source inventory uses new synthesis snapshots. The persisted stage registry is at `middle-files/workflow/state.json`.

## Recommended end-to-end command

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 architecture --auto-investigate-top 5 --synthesize --max-llm-calls 80 --out "D:\AgentOutput\architecture"
```

This combines four steps: create static architecture + index, rank up to 20 evidence-backed questions with local Qwen, execute Top 5 investigations and export readable reports/annotated Draw.io, then synthesize an overall report.

The limit of 80 calls may be insufficient for complex repositories or `--auto-investigate-top 20`; in that case the process saves partial results and can be re-run with a larger budget. A **cache hit is not counted as a new model call**. You may use `--max-llm-calls 160` on a later run; calls remain sequential, not parallel, to limit RAM pressure.

### Phase-by-phase commands

```powershell
# 1. Static architecture and 20 questions; NEVER calls Ollama by default
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"

# 2. Architecture + Qwen review of question priority (no investigations)
py -3 agent.py --project "D:\Work\LegacyProject" architecture --ai-suggestions --question-review-rounds 2 --out "D:\AgentOutput\architecture"

# 3. Investigate a natural-language question, including one Qwen evidence review
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Nếu sửa saveOrder thì ảnh hưởng màn hình nào?" --review-rounds 1 --max-steps 4 --out "D:\AgentOutput\architecture"

# 4. Synthesize already available architecture + investigation reports
py -3 agent.py --project "D:\Work\LegacyProject" synthesize --review-rounds 2 --max-llm-calls 80 --out "D:\AgentOutput\architecture"
```

`investigate --non-ai` is unchanged. `architecture --auto-investigate-top 5 --no-ai-suggestions` disables Qwen question ranking while still using Qwen for the five actual investigations. To skip Qwen entirely, run `architecture` without `--ai-*`, `--synthesize`, or `--auto-investigate-top`.

### Tuning and limits

| Option | Default | Meaning |
|---|---:|---|
| `--model qwen3:8b` | Qwen3:8b | One locally installed Ollama model |
| `--num-ctx 2048` | 2048 | Memory-conscious context setting |
| `architecture --ai-suggestions` | Off | Enable Qwen multi-pass question ranking |
| `architecture --question-review-rounds` | 2 | 1–3 ranking passes |
| `architecture --auto-investigate-top` | 0 | Up to 20 automatic investigations; enables AI ranking unless disabled |
| `architecture --investigation-review-rounds` | 1 | 0–2 evidence critic passes per auto investigation |
| `investigate --review-rounds` | 1 | 0–2 evidence critic passes |
| `synthesize --review-rounds` | 2 | 0–2 hierarchical synthesis critic passes |
| `--max-llm-calls` | 80 | Hard quota for **new** local inference calls in that CLI run |
| `synthesize --fresh` | Off | Ignore stage checkpoints and prompt cache for this synthesis |

## Outputs (v4.15)

```text
output/architecture/
├── architecture.md
├── architecture.drawio
├── module_summary.md
├── stack_architecture.md
├── suggested_investigations.md
├── system_knowledge_report.md              # final, easy to read
├── system_knowledge.drawio                 # actual static module links only
├── system_knowledge.svg                    # simple preview
├── investigations/                        # human-readable reports and graphics
│   ├── index.md
│   └── INV-001/result.md + investigation.drawio + investigation.svg
└── middle-files/                          # ALL machine intermediate data
    ├── architecture.json
    ├── code_intelligence.sqlite
    ├── suggested_investigations.json       # candidate ranking audit
    ├── investigations/INV-001.json + manifest.json
    ├── workflow/state.json + call_audit.jsonl + llm_cache/
    └── synthesis/
        ├── claim_ledger.json
        ├── community_summaries/
        ├── module_summaries/
        ├── review_logs.json
        ├── manifest.json
        └── snapshots/<source-hash>/checkpoints/
```

Raw LLM output/prompt caches can contain proprietary source-derived information. Treat the entire `middle-files/` directory as sensitive; **do not commit or upload it to GitHub**. Source files and report data are never sent to an external inference API by this workflow. Git history tools read the local repository only.

## Accuracy and failure handling

- **Valid citations do not validate the claim itself.** Python verifies that cited paths and line numbers exist and strips unapproved citation references. It cannot prove the model's semantic interpretation.
- Graph edges and mappings are **static/heuristic**, not validated runtime calls. Generated Draw.io arrows only show indexed static edges.
- A failure in a question-ranking Qwen call retains deterministic ranking and logs the failure; the report never manufactures objects or evidence.
- A synthesis that cannot finish due to the call limit or other model error returns **partial** and saves usable module summaries. Re-run with the same `--out` to resume from checkpoints.
- Model calls are synchronous/sequential; each prompt uses short bounded evidence. Total processing time can still be long on a CPU-only computer.
- Tests exercise scripted/mock Ollama, not a large live repository benchmark. Review results against original source before using them for changes.
