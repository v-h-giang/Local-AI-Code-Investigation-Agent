# Standalone 30-question integration benchmark

[Contents](#contents) · [Isolation](#isolation) · [Dataset](#dataset) · [Running](#running) · [Scoring](#scoring) · [Tests-and-removal](#tests-and-removal)

## Contents

The entire benchmark is under `benchmark/`; it is optional and fully removable.

- `run.py`: CLI-only integration harness. Invokes `../agent.py` as a subprocess.
- `datasets/benchmark_30.jsonl`: 30 frozen, source-backed questions.
- `tests/test_runner.py`: standalone unit tests.
- `repositories/`: local frozen source checkouts, created only on request and gitignored.
- `results/`: generated results, logs, review template, gitignored.

No imports from benchmark are made by the production application; there is no production dependency on benchmark datasets or libraries. No external package is required for the runner, beyond the existing application requirements. No code changes to `agent.py` or other production files are necessary.

## Isolation

The runner never modifies the application source. All reports, temporary output and local benchmark repositories are created below `benchmark/`. It uses the existing public `investigate` CLI. With default settings it calls local Ollama, but ONLY if the benchmark command is explicitly launched. The runner never starts automatically.

The benchmark checks out external reference repositories at pinned commits. Do not use a pre-existing source folder with uncommitted changes; it will reject a dirty checkout when it needs to change commits.

## Dataset

Exactly 30 tasks:
- 20 RepoContextBench Agent Framework tasks, repository `microsoft/agent-framework` frozen at commit `47fa59f8e9d7b91e382834b42ecff45e22e2d890`. Gold claims and evidence spans are preserved.
- 10 StackRepoQA questions from the `jdbi/jdbi` rows in the [StackRepoQA dataset](https://github.com/code-world-no-blanket/StackRepoQA/blob/main/data/questions.csv); source answer HTML and relevance labels are preserved. This is an integration-test subset, **not** an official StackRepoQA score. The checked-out JDBI reference revision is locked at `567155b46a00ac131fb51e2ffbce92ebe843a639`; the original StackRepoQA questions are not guaranteed to refer to that historical version.

Dataset references:
- https://github.com/CodeAlive-AI/repo-context-bench/blob/main/dataset/agent-framework/v1/tasks.jsonl
- https://github.com/code-world-no-blanket/StackRepoQA/blob/main/data/questions.csv

## Running

From project root on Windows (PowerShell):

```powershell
py -3 benchmark/run.py --list
py -3 benchmark/run.py --suite all --mode ai --fetch-repos --run-id qwen30
py -3 benchmark/run.py --suite all --mode ai --fetch-repos --run-id qwen30 --resume
```

Short offline-LLM baseline (requires downloaded source checkout but no Ollama):

```powershell
py -3 benchmark/run.py --suite repocontextbench --mode non-ai --limit 2 --fetch-repos --run-id retrieval2
```

You can specify existing frozen repositories via `--repocontextbench-path` and `--stackrepoqa-path`. Without `--fetch-repos`, no network access is initiated; missing or unfrozen source checkout is rejected.

Each case runs `agent.py --project <source> investigate "<question>" --out <benchmark/results/run-id/case-id>` with `--non-diagram --non-update-drawio --report-format md`. Timeout is per task. Use `--max-llm-calls`, `--max-steps`, `--model`, `--timeout`, `--host` as needed.

## Scoring

The report contains exit success/failure, status, seconds, existence and validity of source references and, for RepoContextBench cases only, a **gold-span overlap proxy**. These metrics are not equivalent to a semantic correctness score.

A `review_template.csv` is provided for manual answer correctness review. No unsupported automatic correctness grade is claimed. Memory use, token counts and actual LLM calls are not measured unless separately instrumented.

Generated results live under `benchmark/results/<run-id>/` and are not committed.

## Tests and removal

```powershell
py -3 -m unittest discover -s benchmark/tests -v
py -3 -m unittest discover -s tests -v
```

To remove the entire optional suite:
```powershell
Remove-Item -Recurse -Force .\benchmark
```

The main app continues to work as before; its source and test files are unchanged by this integration.
