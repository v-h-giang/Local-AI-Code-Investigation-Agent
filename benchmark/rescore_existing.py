"""Rescore an existing benchmark run from machine JSON, without Qwen.

This tool never runs the agent, modifies benchmark evidence, or changes a
frozen checkout. Gold labels are used ONLY when computing metrics. The saved
machine JSON (not the old summary) is the source of candidate observations.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import run


def rescore(run_id, *, suite=None):
    run_id=run.check_run_id(run_id)
    folder=run.RESULTS/run_id
    if not folder.is_dir():
        raise FileNotFoundError("Benchmark run not found: "+str(folder))
    cases={item["id"]:item for item in run.read_cases()
           if suite is None or item["suite"]==suite}
    metrics=[]
    for path in sorted(folder.iterdir()):
        if not path.is_dir() or path.name not in cases:
            continue
        case=cases[path.name]
        project=run.CACHES/run.REPOS[case["suite"]][2]
        if not project.is_dir():
            raise FileNotFoundError("Pinned repository missing: "+str(project))
        if run.git("rev-parse","HEAD",cwd=project)!=run.REPOS[case["suite"]][1]:
            raise ValueError("Pinned repository checkout changed: "+str(project))
        stdout_file=path/"stdout.txt"
        stdout=(stdout_file.read_text(encoding="utf-8",errors="replace")
                if stdout_file.is_file() else "")
        try:
            machine=run.load_machine(path,stdout)
            row=run.score_evidence(project,case,machine)
        except (OSError,RuntimeError,ValueError,TypeError,KeyError,
                json.JSONDecodeError) as exc:
            metrics.append({"id":case["id"],"error":type(exc).__name__+": "+str(exc)[:160]})
            continue
        metrics.append({
            "id":case["id"],
            "gold_files":row["gold_files"],
            "original_candidate_hits_at_8":row["candidate_gold_file_hits"],
            "ai_assisted_candidate_hits_at_12":row["ai_assisted_candidate_gold_hits_at_12"],
            "qwen_secondary_candidates":row["qwen_secondary_candidates"],
            "qwen_secondary_gold_hits":row["qwen_secondary_gold_hits"],
            "observed_gold_file_hits":row["observed_gold_file_hits"],
            "observed_gold_span_hits":row["observed_gold_span_hits"],
        })
    valid=[r for r in metrics if "error" not in r]
    total=sum(r["gold_files"] for r in valid)
    def recall(field):
        return round(sum(r[field] for r in valid)/total,4) if total else None
    return {
        "run_id":run_id,"suite":suite or "all",
        "cases_found":len(metrics),"scorable_cases":len(valid),
        "gold_files":total,
        "original_candidate_recall_at_8":recall("original_candidate_hits_at_8"),
        "ai_assisted_candidate_recall_at_12":recall("ai_assisted_candidate_hits_at_12"),
        "qwen_secondary_candidates":sum(r["qwen_secondary_candidates"] for r in valid),
        "qwen_secondary_gold_hits":sum(r["qwen_secondary_gold_hits"] for r in valid),
        "observed_file_recall":recall("observed_gold_file_hits"),
        "cases":metrics,
        "note":"Offline rescore of existing machine JSON. No Qwen, no code execution, no gold-based retrieval."
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-run",required=True)
    p.add_argument("--suite",choices=["repocontextbench","stackrepoqa"],default=None)
    args=p.parse_args(argv)
    print(json.dumps(rescore(args.from_run,suite=args.suite),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
