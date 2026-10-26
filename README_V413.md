# v4.13 — Suggested Investigations

`architecture` now produces up to 20 source-backed, ranked investigation prompts in **exactly two groups**:

1. Business Flows
2. Technical Architecture

Questions are generated deterministically from indexed symbols, entrypoints, SQL references, and static graph edges. Each question carries `path:line` evidence and a reason. The list is a **maximum of 20**, not a mandatory count: if source evidence is sparse it contains fewer. The ranking is heuristic, **not a Qwen evaluation**. Questions about flows, calls, impact and transaction behavior are suggestions for investigation, not established conclusions.

## Commands

Generate diagrams, module summary, code intelligence index and the Top 20 question list, **without invoking Qwen by default**:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

Execute the highest-ranked 5 questions with local Qwen (iterative read-only investigation), saving each result separately:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 5 --out "D:\AgentOutput\architecture"
```

`--auto-investigate-top N` accepts 1–20. `--ai-summary` independently enables Qwen for module summaries; it is not required to generate suggestions. The default agent/model remain `qwen3:8b` and `num_ctx=2048`.

## Files

- `suggested_investigations.md`: two grouped sections, ranked investigation prompts and `path:line` evidence.
- `middle-files/suggested_investigations.json`: machine-readable questions and source citations.
- `investigations/INV-001.json` etc.: per-question Qwen investigation output, only with `--auto-investigate-top`.
- `investigations/manifest.json`: attempted/completed/failed status and links to artifacts.

A failed investigation returns CLI exit code 2 and remains explicitly marked `failed` in the manifest. File-index errors are reported by the intelligence index. Existing diagrams and command names are retained.

## Accuracy and resource considerations

`architecture` now builds/refreshes `code_intelligence.sqlite` as an additional local scan/index step, reusing unchanged file metadata. No local model is required unless `--ai-summary` or `--auto-investigate-top` is enabled. Automatic investigations may make multiple Ollama calls per question, so start with a low N on constrained hardware.
