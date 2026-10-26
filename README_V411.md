# v4.11 — Qwen investigation by default

`investigate` automatically uses local Qwen (`qwen3:8b`, `num_ctx=2048`) for a plan → Python evidence retrieval → grounded answer pipeline. The previous `--ai` flag is replaced with `--non-ai` to explicitly disable the AI stages. Other commands are unchanged.

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Chức năng xử lý đơn hàng ở đâu?" --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" investigate "OrderService" --non-ai --out "D:\AgentOutput\architecture"
```

When Qwen is unavailable, normal investigate returns an error rather than silently changing to non-AI mode. `--non-ai` never instantiates Ollama. Index with `intelligence` first.
