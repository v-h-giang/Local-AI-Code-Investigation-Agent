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
# After a previous failed run: recover machine JSON without rerunning Qwen
py -3 benchmark/run.py --suite all --mode ai --fetch-repos --run-id qwen30 --resume
# Only retry the cases still missing a machine result (will invoke Qwen)
py -3 benchmark/run.py --suite all --mode ai --fetch-repos --run-id qwen30 --resume --retry-failed
```

Targeted three-question regression (new run ID, no need to process all 30 questions):

```powershell
.\.venv\Scripts\python.exe benchmark\run.py --suite repocontextbench --mode ai --fetch-repos --run-id retrieval_v4_smoke --llm-timeout 600 --case-id repo_context_bench_agent_framework_practical_0001 --case-id repo_context_bench_agent_framework_practical_0011 --case-id repo_context_bench_agent_framework_practical_0018
```

`--case-id` is repeatable and selects only the specified frozen question IDs; unknown IDs are rejected before running the model.

Short offline-LLM baseline (requires downloaded source checkout but no Ollama):

```powershell
py -3 benchmark/run.py --suite repocontextbench --mode non-ai --limit 2 --fetch-repos --run-id retrieval2
```

You can specify existing frozen repositories via `--repocontextbench-path` and `--stackrepoqa-path`. Without `--fetch-repos`, no network access is initiated; missing or unfrozen source checkout is rejected.

Each case runs `agent.py --project <source> investigate "<question>" --out <benchmark/results/run-id/case-id>` with `--non-diagram --non-update-drawio --report-format md`. Timeout is per task. Use `--max-llm-calls`, `--max-steps`, `--model`, `--timeout`, `--host` as needed.

## Scoring

The report contains exit success/failure, status, seconds, existence and validity of source references and, for RepoContextBench cases only, a **gold-span overlap proxy**. These metrics are not equivalent to a semantic correctness score.

The runner now reports three **different retrieval stages** over the selected RepoContextBench gold files:

- `candidate_file_recall_at_8`: proportion of gold files appearing in the deterministic top-eight filename candidates before Qwen spends a tool step. A filename match is **not** a citation.
- `observed_file_recall` / `observed_span_recall`: overlap of validated source `file:line` references actually retained in tool observations.
- `gold_file_recall_proxy` / `gold_span_recall_proxy`: overlap of the final validated investigation evidence exported to the machine JSON.

Comparing these stages shows whether misses occur during file discovery, source inspection, or evidence selection. These are recall proxies against annotated evidence, **not answer correctness**. Old run results will not automatically acquire these new metrics until rescored or rerun.

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

## Windows Japanese locale troubleshooting

The runner now forces `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` for the `agent.py` child process. This prevents CP932 redirected stdout from rejecting Vietnamese Unicode text. Old `failed` records may have usable `middle-files/investigations/*.json` even if stdout printing failed. `--resume` recovers those records **without running Ollama again**, and leaves failures without machine JSON untouched. Inspect per-case `stderr.txt` and `runner_record.json` for remaining errors. Use `--resume --retry-failed` only to rerun the cases that have no recoverable record. A machine record being available is not the same as a correct answer.

## Preflight before spending AI time

Run `py -3 benchmark/run.py --preflight` before starting any new benchmark. The runner checks whether the current production source indexer can read the gold evidence file types; it requires no repository checkout, network, model or index initialization.

The original 20 RepoContextBench cases use evidence from `.py`, `.cs`, and `.md` files. Recent source-index updates add these formats to both access and inventory, so `--preflight` can now confirm coverage. This is a *file-type eligibility* check, not proof that all evidence can be retrieved correctly. The runner **blocks a new AI benchmark** instead of wasting tokens and reporting misleading scores. An explicit `--allow-unsupported` switch runs a *diagnostic only*, not a comparable official benchmark.

For diagnostics with supported source languages:

```powershell
py -3 benchmark/run.py --suite stackrepoqa --mode ai --limit 1 --fetch-repos --run-id jdbi-smoke
```

The runner now builds one Code Intelligence SQLite index per selected repository under `benchmark/results/<run-id>/_prepared_indexes/`, and copies it to the private output of each case so the existing `investigate` CLI can retrieve source. Its generated files never enter the production directory. Existing failed runs under `--resume` are still readable, but rerunning unsupported tasks requires an explicit `--allow-unsupported`.

**Metrics:** `machine_results_available` means saved JSON exists, not success. `failed_or_timed_out` also counts nonzero CLI exit codes. Zero source evidence yields a null recall score rather than implying that answer accuracy was measured. Read `stderr.txt` to diagnose a nonzero exit. Windows CP932 printing errors on old runs are avoided on newly spawned child processes by forcing UTF-8.

After upgrading code indexing, use a **new run ID**, e.g. `--run-id qwen30_multilang_v1`: `--resume` on the old `qwen30` will only reuse its insufficient-evidence records and will not measure the new indexer. Run `--preflight` and unit tests before creating the new run.
