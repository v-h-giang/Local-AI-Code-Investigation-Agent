"""P1.5: replay saved gold-blind Dense alternate windows at fixed budgets.

Consumes a completed --collect-multiwindow report. NO embedding/model calls,
source reads, source execution or runtime agent modifications.
Budgets 0, 1, 2, 3, 4 replay prefixes of ALREADY SELECTED Dense windows.
Gold spans are consulted only after each window prefix is determined.
A window overlapping a gold span is NOT a cited/read evidence span.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import run
from benchmark.top8_multiwindow_diagnostics import (
    extra_lines, overlapping_gold_ids, window,
)

BUDGETS = (0, 1, 2, 3, 4)


def evaluate_case(saved_case, benchmark_case):
    """Validate saved top-8 windows then score gold-blind selected prefixes."""
    if saved_case.get("id") != benchmark_case["id"]:
        raise ValueError("Case ID mismatch")
    if saved_case.get("question") != benchmark_case["question"]:
        raise ValueError("Question mismatch for " + benchmark_case["id"])
    top = ((saved_case.get("variants") or {}).get("hybrid") or {}).get(
        "top8_diagnostics")
    if not isinstance(top, list) or len(top) > 8:
        raise ValueError("Missing Hybrid top8 diagnostics")
    original = [part for row in top if (part := window(row)) is not None]
    if len(original) != len(top):
        raise ValueError("Invalid original Hybrid top8 window")
    multi = saved_case.get("multiwindow_diagnostics")
    if not isinstance(multi, dict):
        raise ValueError("Missing multiwindow diagnostics")
    alternates = multi.get("alternates")
    if not isinstance(alternates, list) or len(alternates) > 4:
        raise ValueError("Missing/invalid selected alternate windows")

    allowed = {row["path"] for row in top}
    selected = list(original)
    candidates = []
    extra_costs = []
    for row in alternates:
        part = window(row)
        if part is None or part[0] not in allowed:
            raise ValueError("Invalid/out-of-scope alternate: " + benchmark_case["id"])
        added = extra_lines(part, selected)
        if added < 8:
            raise ValueError("Alternate adds fewer than 8 lines")
        if added != row.get("new_lines"):
            raise ValueError("Saved new_lines inconsistent for " + benchmark_case["id"])
        candidates.append(part)
        extra_costs.append(added)
        selected.append(part)

    # Gold read ONLY after candidate windows and original costs are established.
    gold = benchmark_case.get("gold_spans") or []
    baseline = overlapping_gold_ids(gold, original)
    results = {}
    for budget in BUDGETS:
        chosen = candidates[:budget]
        hits = overlapping_gold_ids(gold, original + chosen)
        results[str(budget)] = {
            "gold_span_window_hits": len(hits),
            "new_gold_span_ids": sorted(hits - baseline),
            "gold_span_ids": sorted(hits),
            "extra_windows": len(chosen),
            "extra_source_lines": sum(extra_costs[:budget]),
        }
    if len(candidates) == 4:
        stored_hits = multi.get("augmented_top8_window_span_ids")
        if stored_hits is not None and sorted(stored_hits) != results["4"]["gold_span_ids"]:
            raise ValueError("Saved full-budget span coverage mismatch")
    return {
        "id": benchmark_case["id"],
        "gold_spans": len(gold),
        "alternate_count": len(candidates),
        "by_budget": results,
    }


def analyze(report, cases):
    suite = report.get("suite")
    if not isinstance(report.get("cases"), list) or not report["cases"]:
        raise ValueError("Missing saved cases")
    relevant = {c["id"]: c for c in cases if c["suite"] == suite}
    seen = set()
    detail = []
    for saved_case in report["cases"]:
        case_id = saved_case.get("id")
        if case_id in seen:
            raise ValueError("Duplicate case " + str(case_id))
        seen.add(case_id)
        source = relevant.get(case_id)
        if source is None:
            raise ValueError("Unknown benchmark case " + str(case_id))
        detail.append(evaluate_case(saved_case, source))

    total_gold = sum(row["gold_spans"] for row in detail)
    baseline = sum(row["by_budget"]["0"]["gold_span_window_hits"]
                   for row in detail)
    budgets = {}
    for budget in BUDGETS:
        records = [row["by_budget"][str(budget)] for row in detail]
        hits = sum(row["gold_span_window_hits"] for row in records)
        windows = sum(row["extra_windows"] for row in records)
        lines = sum(row["extra_source_lines"] for row in records)
        added = hits - baseline
        budgets[str(budget)] = {
            "gold_span_window_hits": hits,
            "gold_span_window_ratio": round(hits / total_gold, 4)
                                       if total_gold else None,
            "new_gold_spans_vs_baseline": added,
            "cases_with_new_span": sum(bool(row["new_gold_span_ids"])
                                        for row in records),
            "extra_windows": windows,
            "extra_source_lines": lines,
            "source_lines_per_new_gold_span": round(lines / added, 1)
                                              if added else None,
        }
    marginal = {}
    for budget in BUDGETS[1:]:
        previous, current = budgets[str(budget-1)], budgets[str(budget)]
        marginal[str(budget)] = {
            "new_gold_spans_at_this_window": (
                current["gold_span_window_hits"] - previous["gold_span_window_hits"]),
            "additional_windows": current["extra_windows"] - previous["extra_windows"],
            "additional_source_lines": (
                current["extra_source_lines"] - previous["extra_source_lines"]),
        }
    return {
        "summary": {
            "case_count": len(detail),
            "gold_spans_total": total_gold,
            "hybrid_top8_window_gold_spans": baseline,
            "budgets": budgets,
            "marginal": marginal,
        },
        "cases": detail,
        "limitations": [
            "Replays prefixes of previously chosen windows, no re-ranking.",
            "Uses pinned gold spans only after the windows are fixed.",
            "Costs count newly exposed source lines, NOT tokens or actual reads.",
            "This is hypothetical span overlap, NOT agent evidence/citations.",
            "Reusing a diagnostic benchmark is exploratory, not held-out validation.",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-report", type=Path, required=True)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    if not args.from_report.is_file():
        p.error("Saved multiwindow report not found: " + str(args.from_report))
    saved = json.loads(args.from_report.read_text(encoding="utf-8"))
    suite = saved.get("suite")
    if suite not in run.REPOS:
        p.error("Unrecognized benchmark suite")
    method = saved.get("method") or {}
    if method.get("frozen_source_commit") != run.REPOS[suite][1]:
        p.error("Frozen benchmark revision does not match")
    if not isinstance((saved.get("summary") or {}).get("multiwindow_diagnostics"), dict):
        p.error("Requires --collect-multiwindow report")
    report = analyze(saved, run.read_cases())
    report["suite"] = suite
    report["from_report"] = str(args.from_report)
    out = (args.out or
           run.RESULTS / "_diagnostics" / "multiwindow_budget_ablation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "report": str(out)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
