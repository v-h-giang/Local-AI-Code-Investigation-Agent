"""Inspect per-case evidence overlap from a completed P1.9 report.

Compares line-reference coverage reported by baseline, adaptive, and merges.
This reads saved diagnostic results and does not produce retrieval candidates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MODES = ("baseline", "adaptive_1", "merge_balanced", "merge_anchored")
MERGES = ("merge_balanced", "merge_anchored")


def _ids(case, mode):
    item = (case.get("modes") or {}).get(mode)
    if not isinstance(item, dict):
        raise ValueError(f"Missing mode {mode} for {case.get('id')}")
    ids = item.get("gold_citable_ids")
    if not isinstance(ids, list) or any(not isinstance(s, str) for s in ids):
        raise ValueError(f"Invalid gold IDs in {case.get('id')}:{mode}")
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate gold IDs in {case.get('id')}:{mode}")
    for key in ("serialized_chars", "displayed_source_lines"):
        if type(item.get(key)) is not int or item[key] < 0:
            raise ValueError(f"Invalid {key} in {case.get('id')}:{mode}")
    return set(ids), item


def inspect(report):
    header = report.get("summary") or {}
    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Missing P1.9 case records")
    max_chars = header.get("max_chars_per_case")
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("Invalid per-case character budget")
    if header.get("case_count") != len(cases):
        raise ValueError("Case count differs from report summary")

    observed = set()
    detail = []
    totals = {name: {"spans": 0, "missed_union_spans": 0,
                     "cases_with_baseline_losses": 0,
                     "cases_with_adaptive_losses": 0}
              for name in MERGES}
    union_total = 0
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in observed:
            raise ValueError("Missing or duplicate case ID")
        observed.add(case_id)
        items = {name: _ids(case, name) for name in MODES}
        if any(part["serialized_chars"] > max_chars for _, part in items.values()):
            raise ValueError(f"Context budget exceeded in {case_id}")
        baseline, adaptive = (items[name][0] for name in MODES[:2])
        union = baseline | adaptive
        reported_union = case.get("gold_union_ceiling_ids")
        if (not isinstance(reported_union, list)
                or len(set(reported_union)) != len(reported_union)
                or set(reported_union) != union):
            raise ValueError(f"Union ceiling mismatch for {case_id}")
        union_total += len(union)
        row = {"id": case_id, "baseline": sorted(baseline),
               "adaptive_1": sorted(adaptive),
               "union_ceiling": sorted(union), "merges": {}}
        for name in MERGES:
            actual, info = items[name]
            if not actual <= union:
                raise ValueError(f"Merge has IDs outside its inputs in {case_id}")
            missing_baseline = baseline - actual
            missing_adaptive = adaptive - actual
            row["merges"][name] = {
                "covered": sorted(actual),
                "new_vs_baseline": sorted(actual - baseline),
                "lost_vs_baseline": sorted(missing_baseline),
                "new_vs_adaptive": sorted(actual - adaptive),
                "lost_vs_adaptive": sorted(missing_adaptive),
                "missing_union": sorted(union - actual),
                "used_chars": info["serialized_chars"],
                "unused_chars": max_chars - info["serialized_chars"],
                "displayed_lines": info["displayed_source_lines"],
                "lost_baseline_source_lines": info.get("lost_baseline_source_lines"),
                "added_adaptive_source_lines": info.get("added_adaptive_source_lines"),
            }
            totals[name]["spans"] += len(actual)
            totals[name]["missed_union_spans"] += len(union - actual)
            totals[name]["cases_with_baseline_losses"] += bool(missing_baseline)
            totals[name]["cases_with_adaptive_losses"] += bool(missing_adaptive)
        detail.append(row)

    if header.get("unbudgeted_union_ceiling") != union_total:
        raise ValueError("Overall union ceiling differs from saved summary")
    summary_modes = header.get("modes") or {}
    for name in MERGES:
        if totals[name]["spans"] != (summary_modes.get(name) or {}).get(
                "gold_spans_citable"):
            raise ValueError(f"Summary coverage mismatch for {name}")

    return {
        "summary": {
            "case_count": len(detail),
            "max_chars_per_case": max_chars,
            "union_ceiling_gold_spans": union_total,
            "merges": totals,
            "cases_with_any_merge_baseline_loss": [
                row["id"] for row in detail
                if any(row["merges"][m]["lost_vs_baseline"] for m in MERGES)],
            "cases_with_any_unrecovered_union_span": [
                row["id"] for row in detail
                if any(row["merges"][m]["missing_union"] for m in MERGES)],
        },
        "focus_cases": [
            row for row in detail if row["id"].endswith(("_0013", "_0016"))],
        "cases": detail,
        "notes": [
            "Coverage is measured from saved source_refs, not generated answers.",
            "The union ceiling ignores character and excerpt budgets.",
            "The report supports retrospective comparisons only.",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-report", required=True, type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--summary-only", action="store_true")
    args = p.parse_args(argv)
    if not args.from_report.is_file():
        p.error("P1.9 saved report not found: " + str(args.from_report))
    data = json.loads(args.from_report.read_text(encoding="utf-8"))
    output = inspect(data)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    shown = {"summary": output["summary"],
             "focus_cases": output["focus_cases"],
             "report": str(args.out) if args.out else None}
    if not args.summary_only:
        shown["cases_with_unrecovered_union"] = [
            row for row in output["cases"]
            if any(row["merges"][m]["missing_union"] for m in MERGES)]
    print(json.dumps(shown, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
