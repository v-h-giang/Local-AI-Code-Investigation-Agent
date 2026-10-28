# v4.17 — HTML Reports by Default and Distributed Draw.io Anchors

## Quick start

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top max --out "D:\AgentOutput\architecture"
```

The command uses **Ollama locally** for ranking, investigation, review and synthesis. **HTML formatting does not use the model**: Python converts source-backed Markdown into standalone pages using `templates/report.html`. No third-party Markdown renderer, Jinja2, browser service, JavaScript or network request is required.

### Report formats

| Option | User-facing output | Internal storage |
|---|---|---|
| *(omitted)* or `--report-format html` | `.html` only | Source Markdown in `middle-files/report-sources/` |
| `--report-format md` | `.md` only | No HTML generated |
| `--report-format both` | `.html` and `.md` | Checkpoints/JSON unchanged |

Applies to `architecture`, `investigate`, and `synthesize`. Other legacy commands (`design`, `overview`, `report`) retain their existing formats. The report format is a **subcommand option**, so put it after `architecture`, `investigate` or `synthesize`.

```powershell
# Markdown instead of HTML
py -3 agent.py --project "D:\Work\LegacyProject" architecture --report-format md --out "D:\AgentOutput\architecture"

# Both HTML and Markdown
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top max --report-format both --out "D:\AgentOutput\architecture"

# Single investigation as HTML
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Which screens call saveOrder?" --out "D:\AgentOutput\architecture"

# Re-run synthesis using existing intermediate evidence, no need to re-run scans
py -3 agent.py --project "D:\Work\LegacyProject" synthesize --out "D:\AgentOutput\architecture"
```

The same output folder can be reused. In HTML-only mode Markdown files are **restored before each command** for checkpoint reuse and citation parsing, then retained within `middle-files/report-sources/` after publication. Existing source files are never changed.

### HTML reports

| HTML file | Contents |
|---|---|
| `architecture.html` | Module graph inventory, static dependencies |
| `module_summary.html` | Per-module summary |
| `stack_architecture.html` | FE/BE/DB framework evidence |
| `suggested_investigations.html` | Up to 20 source-backed investigation questions |
| `investigations/index.html` | Investigation status and links |
| `investigations/INV-XXX/result.html` | Result, source evidence, SVG and Draw.io links |
| `system_knowledge_report.html` | Hierarchical system synthesis |

The shared HTML template includes a section index, tables, fenced code blocks, source references and SVG links. The generated report is a static page: opening a report does not send any data to a cloud server. Note that the Markdown renderer deliberately supports the **Markdown subset** produced by this agent; it is not a complete CommonMark engine.

### Draw.io endpoint distribution

`drawio_ports.py` walks **existing** Draw.io XML edges and vertex geometry. For every input/output endpoint it selects a side of its box (left/right/top/bottom), then assigns a position separate from other endpoints, including those with opposite arrow directions. When a side fills up, it tries other sides. **An anchor is reused only when all available slots are occupied.** The approximate minimum spacing is 22 pixels per side, configurable in code.

The pass is applied to `architecture.drawio`, FE/BE/DB diagrams, annotated `.investigated.drawio`, investigation-specific diagrams and `system_knowledge.drawio`. It never invents or reverses edges. Existing XML vertex and edge IDs, source/target attributes and arrow labels remain intact. Compressed/non-XML diagrams are not modified by this pass.

### Backward compatibility and limitations

- `--auto-investigate-top` alone remains **Top 5**; `--auto-investigate-top max` still means **all generated questions (up to 20)**.
- No cloud LLM; Ollama is called only through its local loopback endpoint.
- Original Markdown reports remain available with `--report-format md` or `both`.
- All JSON/CSV, SQLite, checkpoints, code-index and intermediate Markdown remain in `middle-files/`.
- A static code-reference graph **does not prove runtime execution**, even when drawn with arrows.
- `--non-markdown` is a legacy flag for suppressing individual Markdown artifacts. In default HTML mode, a Markdown intermediate is still needed to render HTML; it is moved into `middle-files/`.

Run regression tests from the agent root:

```powershell
py -3 -m unittest discover -s tests -v
```
