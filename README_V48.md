# Agent v4.8 — Draw.io layout and framework grouping

The CLI command has not changed:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --ai-summary --out "D:\AgentOutput\architecture"
```

This release improves **presentation only**; it does not change how dependencies or frameworks are detected.

- FE / BE / DB / Shared columns in `fe_be_architecture.drawio`, with dedicated colors.
- Reference diagrams put each detected framework in a separate column. Source-backed objects only; missing roles remain in the Markdown/JSON evidence tables.
- Observed diagrams place related source roles close together by static graph proximity.
- Draw.io arrows are larger (`endSize=24`, `strokeWidth=3`) and use orthogonal routing.
- Other existing diagrams retain the v4.7 typography improvements.

These files are fully editable Draw.io XML. A reference edge remains a framework *concept*, not a verified runtime call. Complex dependency graphs may still require manual re-routing of some connectors.
