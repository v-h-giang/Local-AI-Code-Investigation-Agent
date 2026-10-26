# v4.8 — Draw.io lanes, framework columns, and larger connectors

Run:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --ai-summary --out "D:\AgentOutput\architecture"
```

- `fe_be_architecture.drawio`: FE → BE → DB → Shared/Unknown lanes, with different colors and larger arrows.
- `frontend_reference.drawio` and `backend_reference.drawio`: framework-specific columns. Only source-backed roles are shown; reference edges remain conceptual and dashed.
- `frontend_architecture.drawio` and `backend_architecture.drawio`: related roles are placed near each other using known static dependency links.
- `architecture.drawio`, source maps and overview diagrams: larger node labels, spacing and connectors.
- Existing Qwen and architecture graph behavior is unchanged.

Visual layout does not prove runtime calls. Complex graphs may retain edge crossings.
