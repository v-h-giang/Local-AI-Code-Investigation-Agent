# Local AI Code Investigation Agent

**v4.17 · Local-first codebase intelligence · Python + Ollama · Windows / VS Code · Read-only source analysis**

**Language:** English · [Tiếng Việt](README-VN.md)

## Universal Code Knowledge Base (V5.4–V5.8 foundation)

The agent now has a multi-language file registry, optional Tree-sitter and
conservative lexical declaration adapters, a versioned SQLite global programming
concept database, repository module profiles, and an opt-in import bridge for
pre-exported LSP symbol locations. The global KB has **31 curated seed concepts**,
not encyclopedic coverage. These are search hints, **never source citations**.

See [Universal Knowledge guide](README_UNIVERSAL_KNOWLEDGE.md) for the clickable
table of contents, knowledge pack format, offline commands, limitations and
benchmark instructions. `setup.ps1` retains `-OllamaMode Auto` by default.

## Quick start — one command

Open PowerShell in the repository folder (where `agent.py` lives). Replace the two Windows paths:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top --out "D:\AgentOutput\architecture"
```

**What it does:** scans the repository → produces architecture/FE–BE–DB diagrams → generates up to **20 source-backed questions** → uses local Qwen to rank them → investigates the **Top 5** → produces readable HTML/SVG/Draw.io reports → synthesizes a system-level report. Intermediate files, checkpoints and logs live under `middle-files/`.

**Default reports are HTML** (open `system_knowledge_report.html` in your browser). The agent renders a bundled HTML template with Python, **without extra Ollama calls or AI-generated HTML**. To change the output format, add `--report-format md` or `--report-format both` after the command name; `html` is the default. Draw.io arrows attach to independently distributed ports on each box, reusing a port only when the available perimeter slots are exhausted.

```powershell
# Generate Markdown and HTML together
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top max --report-format both --out "D:\AgentOutput\architecture"
```

**Investigate every generated question (up to 20):**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top max --out "D:\AgentOutput\architecture"
```

`max` means **all valid generated questions**, not necessarily 20. The default local Ollama call budget is 160 for Top 5 and 370 for `max`; these are limits, not target call counts. Processing a large repository or running all investigations can take substantial time.

**Read these files first:** `system_knowledge_report.html` (system summary), `suggested_investigations.html` (ranked questions), `investigations/index.html` (investigation reports), and `system_knowledge.drawio` (editable diagram).

### Five everyday commands

All commands below are run from the folder containing `agent.py`.

**1. Scan architecture and generate questions, without running Qwen:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

**2. Investigate one question with local Qwen (the default):**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Which screens could be affected if saveOrder changes?" --out "D:\AgentOutput\architecture"
```

**3. Automatically investigate the Top 10:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 10 --out "D:\AgentOutput\architecture"
```

**4. Investigate the Top 5 but skip final system synthesis:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top --non-synthesize --out "D:\AgentOutput\architecture"
```

**5. Rebuild only the final synthesis from existing reports:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" synthesize --out "D:\AgentOutput\architecture"
```

> **First-time setup:** Install [Python 3.11+](https://www.python.org/downloads/windows/) and [Ollama for Windows](https://ollama.com/download/windows), then run `ollama pull qwen3:8b`. No Node.js, cloud LLM or external AI API is needed. Plain `architecture` runs without Qwen.

## First-run Python environment (Windows PowerShell)

Create a local virtual environment once (safe to repeat):

```powershell
.\setup.ps1
```

If PowerShell blocks local scripts, use `powershell -ExecutionPolicy Bypass -File .\setup.ps1` from the project directory. The script requires Python 3.11+, verifies core module imports, and **does not** download models or require Ollama for static analysis. No third-party pip dependencies are required by default.

Optional flags: `-PullModel` (download `qwen3:8b`, requires installed/running Ollama), `-WithTreeSitter` (optional language parser), and `-RunTests`.

### Hardware-aware Ollama environment (Windows)

`setup.ps1` now detects available GPU vendor (Intel, NVIDIA or AMD) and system RAM with Windows CIM, and configures UTF-8 plus conservative Ollama environment settings. This does **not** install graphics drivers or guarantee a supported GPU backend. It does not restart Ollama automatically.

```powershell
.\setup.ps1                        # Auto: prefer supported GPU; fallback to native Ollama detection
.\setup.ps1 -OllamaMode GPU         # Request GPU settings for detected hardware
.\setup.ps1 -OllamaMode CPU         # Disable GPU backends (diagnostic / comparison)
.\setup.ps1 -OllamaMode Skip        # Set UTF-8 only; leave Ollama settings untouched
.\setup.ps1 -ProcessOnly           # Current PowerShell process only; no persistent User changes
.\setup.ps1 -RunTests -OllamaMode Auto
```

Default mode `Auto` prefers CUDA on NVIDIA, enables Vulkan + `OLLAMA_IGPU_ENABLE=1` on Intel integrated graphics, and preserves Ollama's native backend discovery for AMD/unknown devices. `CPU` sets `CUDA_VISIBLE_DEVICES=-1`, `ROCR_VISIBLE_DEVICES=-1`, `GGML_VK_VISIBLE_DEVICES=-1`, `OLLAMA_VULKAN=0` and `OLLAMA_IGPU_ENABLE=0`; switching back to Auto/GPU **clears** those device masks. Python Unicode defaults: `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`. Memory-friendly Ollama defaults: one parallel request, one loaded model, and default context 2048 for machines with <=24 GiB RAM; explicit pre-existing user context overrides are retained. `agent.py` separately supplies `--num-ctx 2048` by default; increase it explicitly only if resources allow.

**Important:** the Ollama desktop application reads environment variables at startup. After changing setup modes, quit Ollama completely from the system tray, restart it, run `ollama run qwen3:8b "hello"`, and verify placement with `ollama ps`. A `100% GPU` placement indicator does not imply a particular inference speed; compare tokens/second. CPU/GPU variables do not retroactively affect an already-running Ollama service. GPU detection is heuristic and on Intel Iris Xe uses shared system memory.

Official docs: [Ollama environment variables on Windows](https://docs.ollama.com/faq#setting-environment-variables-on-windows) · [Ollama GPU support](https://docs.ollama.com/gpu).


Run without activating:

```powershell
.\.venv\Scripts\python.exe agent.py --project ".\sample_project" architecture --out ".\output\sample-architecture"
.\.venv\Scripts\python.exe benchmark\run.py --preflight
```

The `.venv/` folder is gitignored. To recreate it, delete the folder and rerun setup.

## Installation (Windows)

```powershell
# Get the agent
git clone https://github.com/v-h-giang/Local-AI-Code-Investigation-Agent.git
cd Local-AI-Code-Investigation-Agent
py -3 --version

# Only needed for AI-powered workflows
ollama pull qwen3:8b
ollama list

# Check the connection and run a tiny generation
py -3 agent.py --project ".\sample_project" doctor --probe
```

Start the Ollama desktop application if the local service is not running. `doctor --probe` loads the model and makes a real inference call; `doctor` without `--probe` only checks availability. You can try the included sample without an LLM:

```powershell
py -3 agent.py --project ".\sample_project" architecture --out ".\output\sample-architecture"
```

To update a previous clone, run `git pull origin main`. The **project** supplied to `--project` is a local source directory, not a GitHub URL. Place the **output** outside the analyzed project if you do not want generated files mixed with its source.

## Workflow modes and defaults

| Command | What happens | Ollama needed? |
|---|---|---|
| `architecture` | Static architecture diagrams, module overview, intelligence index, up to 20 questions | No |
| `architecture --auto-investigate-top` | Full pipeline: local ranking, Top 5 investigations, diagrams, synthesis | Yes |
| `architecture --auto-investigate-top N` | Full pipeline for Top N (`1`–`20`) | Yes |
| `architecture --auto-investigate-top max` | Full pipeline for all generated questions (up to 20) | Yes |
| `architecture --ai-suggestions` | Qwen ranking/review of source-backed question candidates, without auto-investigating | Yes |
| `architecture --ai-summary` | Local AI summaries for individual modules | Yes |
| `investigate "question"` | Iterative tool-based investigation, human-readable outputs | Yes, by default |
| `investigate "question" --non-ai` | Lexical/source evidence retrieval only | No |
| `synthesize` | Hierarchical synthesis of existing architecture and investigation results | Yes |

Generated questions are divided into **Business Flows** and **Technical Architecture**. The generator never pads a short list with invented questions. Graph and source evidence are used for candidate selection; Qwen ranks existing candidates when AI ranking is enabled.

### Disable optional steps with `--non-*`

The full automatic workflow enables its recommended stages by default. Disable only what you do not need:

| Flag | Effect |
|---|---|
| `--non-synthesize` | Skip final system synthesis |
| `--non-ai-suggestions` | Skip Qwen question ranking; keep static grounded ordering |
| `--non-review` | Skip extra critique passes across ranking, investigation and synthesis |
| `--non-investigation-review` | Skip the investigation evidence reviewer |
| `--non-synthesis-review` | Skip final synthesis review |
| `--non-markdown` | Skip individual Markdown reports in `md` mode; HTML remains available in HTML mode |
| `--non-diagram` | Skip individual investigation Draw.io diagrams |
| `--non-update-drawio` | Skip annotated versions of architecture diagrams |

For a **single** `investigate` command, use `--non-ai` to avoid Qwen altogether. These options do not imply that the plain `architecture` command calls the model.

### Useful tuning options

```powershell
# Increase the number of tool steps for one question (1–6)
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Trace order submission through FE, BE and SQL" --max-steps 6 --budget 1200 --out "D:\AgentOutput\architecture"

# Turn off the individual diagram generation, but still run automatic investigations
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 5 --non-diagram --out "D:\AgentOutput\architecture"
```

Global options go **before** the command: `--model` (default `qwen3:8b`), `--host` (default `http://127.0.0.1:11434`), `--num-ctx` (default `2048`), and `--timeout` (default `240` seconds). Command-specific options such as `--out`, `--budget`, `--max-steps`, `--max-llm-calls` go **after** the command.

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 architecture --auto-investigate-top max --out "D:\AgentOutput\architecture"
```

A single investigation defaults to `--max-steps 4`, `--review-rounds 1`, and `--max-llm-calls 80`. Question ranking defaults to 2 passes and final synthesis review to 2 passes. The automatic workflow runs local model calls sequentially and uses resumable checkpoints and cached results where supported.

## Where the results go

```text
D:\AgentOutput\architecture\
├── architecture.html
├── architecture.drawio
├── architecture.investigated.drawio
├── module_summary.html
├── stack_architecture.html
├── frontend_architecture.drawio
├── backend_architecture.drawio
├── fe_be_architecture.drawio
├── frontend_reference.drawio
├── backend_reference.drawio
├── suggested_investigations.html
├── system_knowledge_report.html
├── system_knowledge.drawio
├── system_knowledge.svg
├── investigations\
│   ├── index.html
│   ├── INV-001\
│   │   ├── result.html
│   │   ├── investigation.drawio
│   │   └── investigation.svg
│   └── ...
└── middle-files\
    ├── architecture.json
    ├── code_intelligence.sqlite
    ├── suggested_investigations.json
    ├── investigation_annotations.json
    ├── investigations\          # technical JSON / evidence CSV / manifest
    ├── workflow\                # settings / state / audit / LLM cache
    ├── synthesis\               # claims / intermediate summaries / checkpoints
    ├── report-sources\          # Markdown inputs cached when HTML-only
    ├── drawio-baselines\        # only if overwriting original diagrams
    └── .module_summary_cache\
```

This is an illustrative tree; **files only appear when the corresponding stage is enabled and has output**. Some FE/BE diagrams also have `.investigated.drawio` variants when a source-matched architecture diagram exists. Human-facing HTML reports/diagrams stay outside `middle-files/`; raw Markdown used for later synthesis is retained under `middle-files/report-sources/` in HTML-only mode.

To open and edit `.drawio` files, use [diagrams.net](https://app.diagrams.net) or a compatible VS Code extension. Investigation diagrams only show relationships supported by available static graph evidence. By default, original architecture diagrams are preserved; annotated copies use `.investigated.drawio`. `--overwrite-drawio` is an explicit opt-in that backs up originals under `middle-files/drawio-baselines/`.

## Advanced investigation commands

After running `architecture` or `intelligence` with the **same `--out`**, these commands query the local intelligence index:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" symbol OrderService --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" trace processOrder --depth 3 --direction out --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" impact saveOrder --depth 4 --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" flows --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" clusters --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" history --file backend/OrderService.java --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" diff-impact --base HEAD~1 --head HEAD --out "D:\AgentOutput\architecture"
```

Additional commands include `search`, `refs`, `read`, `index`, `ask`, `chat`, `report`, `overview`, and `design`. `vectorize` and `semantic` use an **optional local embedding model** (for example `nomic-embed-text`); they do not require cloud embeddings. See [Code Intelligence](README_CODE_INTELLIGENCE.md) for details.

## How the agent works

```text
Source files (Java / SQL / ActionScript / MXML / XML / configuration)
      |
      +--> static architecture scanner --> modules + editable Draw.io
      |
      +--> incremental SQLite symbol/search/dependency index
                                              |
             source-backed question generator--+
                                              |
                                    local Qwen ranking & review
                                              |
                            bounded tool-driven investigations
                                              |
                         evidence verification + readable reports
                                              |
                              hierarchical local synthesis
                                              |
                          system_knowledge_report.html + Draw.io
```

Python handles indexing, graph traversal, file/line evidence, checkpoints and stopping conditions. Qwen handles short planning, ranking, interpretation and summarization tasks. The software uses a bounded, local multi-loop workflow rather than attempting to stuff an entire codebase into one prompt.

**Evidence limitations:** Symbol extraction uses optional Tree-sitter support with a lexical fallback; this is not a full Java/ActionScript language server. Candidate call edges, dependency injection, overloads, dynamic dispatch, `RemoteObject` mappings, and FE → BE → SQL flows are **not verified runtime execution traces**. Source citations and diagrams help inspection but do not turn heuristics into proof. If evidence is missing, the agent should report uncertainty rather than invent behavior.

**Privacy and safety:** AI calls are directed to an HTTP loopback Ollama endpoint. The investigation tools do not give Qwen arbitrary shell commands, source writes or SQL execution. Outputs, SQLite databases and logs can still contain sensitive material derived from source code; do not publish them without review. `git clone`/`git pull` are separate network operations for obtaining agent source, not AI inference.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Ollama unreachable | Start Ollama; run `ollama list` and `doctor --probe` |
| Model not installed | Run `ollama pull qwen3:8b` or select a locally installed `--model` |
| Slow after FE/BE/DB diagrams | Check `[Suggestions]`, `[Intelligence]` and Qwen-ranking progress logs. v4.16.1 optimizes FTS cleanup and graph reuse |
| Out of memory / very slow inference | Keep `--num-ctx 2048`; start with Top 1 or Top 5 instead of `max` |
| Intelligence index missing | Run `architecture` or `intelligence` using the same `--out` |
| Source changes not detected | Re-run indexing; if file size and mtime were preserved, rebuild the affected index |
| Partial auto-investigation | Check `middle-files/investigations/manifest.json` and workflow state/logs |
| No evidence for a relationship | Treat it as unresolved; inspect `symbol`, `trace`, `flows` and the cited source |

Typical exit codes: `0` for success, `1` for handled input/Ollama/I/O errors, and `2` for partially failed automatic workflows or incomplete long-running tasks. Consult the actual error/report rather than the code alone.

```powershell
# Test suite
py -3 -m unittest discover -s tests -v

# CLI reference
py -3 agent.py --help
py -3 agent.py --project ".\sample_project" architecture --help
```

## Version-specific and technical documentation

These documents remain in their existing languages and are **not replaced or translated** by this README:

- [v4.17 — HTML reports and distributed Draw.io ports](README_V417.md)
- [v4.16 — Smart workflow defaults](README_V416.md)
- [v4.16.1 — Performance hotfix](README_V4161_PERFORMANCE.md)
- [v4.15 — Local multi-loop workflow](README_V415.md)
- [v4.14 — Readable reports and annotated Draw.io](README_V414.md)
- [v4.13 — Suggested Investigations](README_V413.md)
- [v4.12 — Iterative Qwen Investigation](README_V412.md)
- [v4.11 — CLI default AI behavior](README_V411.md)
- [Code Intelligence reference](README_CODE_INTELLIGENCE.md)
- [Architecture and Module Summary](README_ARCHITECTURE.md)
- [FE/BE/DB Stack Architecture](README_STACK_ARCHITECTURE.md)
- [v4.8 Draw.io layouts](README_V48.md)
- [v4 legacy overview/design workflow](README_V4.md)

**Current guide:** v4.17. If older version notes conflict with the current CLI, use `py -3 agent.py --help` and the command-specific `--help` output as the source of truth.
