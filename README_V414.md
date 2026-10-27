# v4.14 — Human-readable Investigation Reports & Annotated Draw.io

This release does not change the static graph algorithm or the Qwen planner. It changes how investigation findings are presented, and how existing architecture diagrams are annotated.

## Default workflow

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Nếu sửa saveOrder ảnh hưởng những màn hình nào?" --out "D:\AgentOutput\architecture"
```

`investigate` still uses local Qwen by default (`--non-ai` disables Qwen), but the terminal now prints the answer and artifact paths rather than raw JSON. Each investigation gets a deterministic directory:

- `investigations/INV-Q-<hash>/result.md`: question, Qwen answer, actual source file:line evidence, tool steps, unsupported citations, limitations.
- `investigations/INV-Q-<hash>/investigation.svg`: visual preview embedded directly in Markdown.
- `investigations/INV-Q-<hash>/investigation.drawio`: editable evidence diagram grouped by FE/BE/DB lanes; no fabricated runtime flow. For impact queries lane order is reversed to aid reading, but edges preserve observed static direction.
- `architecture.investigated.drawio` and other `.investigated.drawio` copies: existing matching nodes highlighted, and only matching source-backed static edges colored. Original `.drawio` files are kept intact by default.
- `middle-files/investigations/INV-Q-<hash>.json`: full structured result and source evidence.
- `middle-files/investigations/INV-Q-<hash>.evidence.csv`: verified source citations, snippets and origin.
- `middle-files/investigation_annotations.json`: audit registry for cumulative annotations, reset automatically if source inventory changes.

A citation must refer to a **real, allowed, existing source file and line**. References outside the scanned project, nonexistent files and invalid line numbers are excluded and recorded in JSON/Markdown. Qwen-generated prose alone never authorizes a graph edge.

## Automatic investigations

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 5 --out "D:\AgentOutput\architecture"
```

Produces `investigations/index.md` and individual `investigations/INV-001/result.md` / `investigation.drawio`. Structured per-question results, evidence CSV and `manifest.json` are all under **`middle-files/investigations/`**. Auto investigation failures are marked, not silently counted as completed. Suggested question `source_evidence` is labeled **question seed** and cannot be passed off as completed investigation evidence.

## Output switches (both commands when applicable)

- `--no-markdown`: disable each investigation Markdown file (but not the architecture Markdown report).
- `--no-diagram`: disable per-question Draw.io **and SVG preview**.
- `--no-update-drawio`: do not create/update annotated architecture copies.
- `--diagram-type auto|flow|impact|symbol`: choose evidence diagram layout intent; never change the graph evidence.
- `--overwrite-drawio`: *explicitly* overwrite original diagrams with annotations, backing up pristine originals in `middle-files/drawio-baselines/`. Do not combine with `--no-update-drawio`.

Only diagrams already present in the requested `--out` folder can be annotated. Generate them with `architecture` first. For long-lived output folders, regenerate architecture after changing source; this keeps base diagrams aligned with the latest graph.

## Accuracy and resource behavior

Draw.io colors signify **evidence relevance**, never runtime verification. Existing static edges are not necessarily business flows. Reference framework connections remain conceptual. Output drawing and Markdown do not require additional Qwen inference or dependencies beyond the Python standard library. Raw model/tool responses, CSV, XML backups and registry are kept outside the scanned source tree.
