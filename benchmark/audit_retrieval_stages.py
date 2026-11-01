"""Offline retrieval-stage audit for frozen benchmark machine records.

Gold labels are used for scoring only. This script makes no Ollama calls,
does not re-run retrieval and never modifies production search rankings.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import run


def audit(run_id, suite="repocontextbench"):
    run_id = run.check_run_id(run_id)
    folder = run.RESULTS / run_id
    if not folder.is_dir():
        raise FileNotFoundError(folder)
    cases = {c["id"]: c for c in run.read_cases() if c["suite"] == suite}
    project = run.CACHES / run.REPOS[suite][2]
    if not project.is_dir():
        raise FileNotFoundError(project)
    if run.git("rev-parse", "HEAD", cwd=project) != run.REPOS[suite][1]:
        raise ValueError("Benchmark checkout is not at the frozen commit")
    rows = []
    for case_id, case in sorted(cases.items()):
        case_dir = folder / case_id
        if not case_dir.is_dir():
            continue
        stdout_path = case_dir / "stdout.txt"
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
        try:
            machine = run.load_machine(case_dir, stdout)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            rows.append({"id": case_id, "error": type(exc).__name__ + ": " + str(exc)[:160]})
            continue
        investigation = machine.get("investigation") or {}
        discovery = investigation.get("file_discovery") or {}
        candidates = discovery.get("candidates") or []
        gold = {span["path"] for span in case.get("gold_spans") or []}
        valid_candidates = [
            (i + 1, path, item.get("candidate_origin", "original"))
            for i, item in enumerate(candidates)
            if isinstance(item, dict)
            if (path := run.valid_candidate_file(project, item.get("path")))
        ]
        original = {p for rank, p, origin in valid_candidates if origin != "qwen-plan-search"}
        secondary = {p for rank, p, origin in valid_candidates if origin == "qwen-plan-search"}
        ranked_8 = {p for rank, p, _ in valid_candidates if rank <= 8}
        ranked_12 = {p for rank, p, _ in valid_candidates if rank <= 12}
        observed = {p for p, _ in run.visible_tool_refs(project, investigation)}
        visited = {
            path for path in investigation.get("inspected_candidate_paths") or []
            if run.valid_candidate_file(project, path)
        }
        for step in investigation.get("steps") or []:
            if not isinstance(step, dict):
                continue
            observation = step.get("observation") or {}
            for field in ("path",):
                candidate = step.get(field)
                if isinstance(candidate, str) and run.valid_candidate_file(project, candidate):
                    visited.add(candidate)
                if isinstance(observation, dict):
                    candidate = observation.get(field)
                    if isinstance(candidate, str) and run.valid_candidate_file(project, candidate):
                        visited.add(candidate)
            for source in step.get("source_refs") or []:
                if isinstance(source, str) and ":" in source:
                    path = source.rpartition(":")[0]
                    if run.valid_candidate_file(project, path):
                        visited.add(path)
        rows.append({
            "id": case_id,
            "gold_files": len(gold),
            "candidate_at_8_hits": len(ranked_8 & gold),
            "candidate_at_12_hits": len(ranked_12 & gold),
            "original_all_hits": len(original & gold),
            "secondary_hits": len(secondary & gold),
            "secondary_novel_hits": len((secondary - original) & gold),
            "visited_gold_hits": len(visited & gold),
            "observed_gold_hits": len(observed & gold),
            "gold_candidate_not_visited": sorted((ranked_12 & gold) - visited),
            "gold_visited_not_observed": sorted((visited & gold) - observed),
            "gold_never_in_top12": sorted(gold - ranked_12),
            "original_candidate_count": len(original),
            "secondary_candidate_count": len(secondary),
            "candidate_ranked_paths": [
                {"rank": rank, "path": path, "origin": origin,
                 "is_gold": path in gold, "visited": path in visited,
                 "observed": path in observed}
                for rank, path, origin in valid_candidates[:12]
            ],
        })
    valid = [r for r in rows if "error" not in r]
    denominator = sum(r["gold_files"] for r in valid)
    totals = {key: sum(r[key] for r in valid) for key in
              ("candidate_at_8_hits", "candidate_at_12_hits", "original_all_hits",
               "secondary_hits", "secondary_novel_hits", "visited_gold_hits",
               "observed_gold_hits")}
    return {
        "run_id": run_id, "suite": suite, "cases": rows,
        "summary": {
            "scorable_cases": len(valid), "gold_files": denominator,
            **totals,
            "recall_at_8": round(totals["candidate_at_8_hits"] / denominator, 4) if denominator else None,
            "recall_at_12": round(totals["candidate_at_12_hits"] / denominator, 4) if denominator else None,
            "observed_recall": round(totals["observed_gold_hits"] / denominator, 4) if denominator else None,
            "cases_with_candidate_attrition": sum(bool(r["gold_candidate_not_visited"]) for r in valid),
            "cases_with_evidence_attrition": sum(bool(r["gold_visited_not_observed"]) for r in valid),
            "failure_categories": dict(Counter(
                "candidate-generation" if r["gold_never_in_top12"] else
                "selection-or-evidence" if r["gold_candidate_not_visited"] or r["gold_visited_not_observed"] else
                "no-visible-attrition" for r in valid)),
        },
        "note": "Post-hoc gold-only diagnostics; no gold in retrieval, Qwen or ranking.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-run", required=True)
    parser.add_argument("--suite", choices=sorted(run.REPOS), default="repocontextbench")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = audit(args.from_run, args.suite)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
