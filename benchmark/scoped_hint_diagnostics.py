"""Score scoped-symbol annotations from a SAVED retrieval ablation; no Ollama.

Usage:
  py -3 benchmark/scoped_hint_diagnostics.py ^
    --from-report benchmark/results/_diagnostics/scoped_symbol_ablation.json

Only the saved hybrid top-8 paths are replayed. Source symbol definitions come
from the saved frozen SQLite. Gold spans are loaded AFTER hint resolution.
The plus/minus-eight-line window is an upper-bound navigation opportunity;
neither window overlap nor a matching file constitutes verified source evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import run
from scoped_symbol_resolution import scoped_symbol_resolve


def overlapping_ids(gold, candidates):
    """Evaluate path/windows against gold labels AFTER retrieval is complete.

    Each candidate is (path, start, end); a span is hit by ANY overlap.
    This does not mean a source line was read, validated or cited.
    """
    return {
        span.get("id", str(i + 1))
        for i, span in enumerate(gold)
        if any(
            path == span["path"]
            and isinstance(begin, int) and isinstance(end, int)
            and begin <= span["end_line"] and end >= span["start_line"]
            for path, begin, end in candidates
        )
    }


def diagnose_case(case, saved_case, repo, *, radius=8):
    """Replay top-8 scoped annotation without changing ranked candidates."""
    if saved_case.get("question") != case["question"]:
        raise ValueError("Benchmark question differs from saved report: " + case["id"])
    prior = (saved_case.get("variants") or {}).get("hybrid") or {}
    top = prior.get("top8_diagnostics")
    if not isinstance(top, list) or len(top) > 8:
        raise ValueError("Missing or invalid hybrid top8_diagnostics: " + case["id"])
    original_paths = [row.get("path") for row in top]
    if not all(isinstance(path, str) for path in original_paths):
        raise ValueError("Malformed path in saved top8: " + case["id"])

    rows = [
        {
            "path": row["path"],
            "line_start": row.get("line_start"),
            "line_end": row.get("line_end"),
            "retrieval_views": row.get("retrieval_views") or [],
            "citation": False,
        } for row in top
    ]
    # Explicit-name rescue is intentionally excluded here: evaluate existing
    # top-8 scoped annotations only, not new global candidate ranking.
    annotated = scoped_symbol_resolve(
        repo, case["question"], rows, scope_limit=8,
        limit=8, max_rescue=0)
    if [row["path"] for row in annotated] != original_paths:
        raise RuntimeError("Scoped diagnosis unexpectedly changed top8 paths")

    hints = []
    for row in annotated:
        for hint in row.get("symbol_hints") or []:
            if hint["path"] != row["path"]:
                raise ValueError("Inconsistent scoped symbol hint path")
            hints.append({
                "path": hint["path"],
                "line": hint["line"],
                "end_line": hint.get("end_line", hint["line"]),
                "name": hint["name"],
                "kind": hint["kind"],
                "matched_tokens": hint.get("matched_tokens") or [],
            })

    # Make the gold comparison ONLY after all symbol decisions are finalized.
    gold = case.get("gold_spans") or []
    gold_paths = {span["path"] for span in gold}
    base_windows = [
        (row["path"], row.get("line_start"), row.get("line_end"))
        for row in rows
    ]
    hint_points = [(h["path"], h["line"], h["line"]) for h in hints]
    hint_windows = [
        (h["path"], max(1, h["line"] - radius), h["line"] + radius)
        for h in hints
    ]
    old = overlapping_ids(gold, base_windows)
    by_point = overlapping_ids(gold, hint_points)
    by_window = overlapping_ids(gold, hint_windows)
    combined = overlapping_ids(gold, base_windows + hint_windows)
    return {
        "id": case["id"],
        "hint_count": len(hints),
        "hinted_file_count": len({h["path"] for h in hints}),
        "hints_on_gold_file": sum(h["path"] in gold_paths for h in hints),
        "exact_line_overlap_ids": sorted(by_point),
        "hint_window_overlap_ids": sorted(by_window),
        "hybrid_window_overlap_ids": sorted(old),
        "union_window_overlap_ids": sorted(combined),
        "new_window_overlap_ids": sorted(combined - old),
        "hints": [
            {
                **h,
                "on_gold_file": h["path"] in gold_paths,
                "exact_line_overlaps_gold": bool(overlapping_ids(
                    gold, [(h["path"], h["line"], h["line"])])),
                "window_overlaps_gold": bool(overlapping_ids(
                    gold, [(h["path"], max(1, h["line"] - radius),
                            h["line"] + radius)])),
            } for h in hints
        ],
    }


def summarize(rows):
    return {
        "case_count": len(rows),
        "cases_with_hints": sum(x["hint_count"] > 0 for x in rows),
        "symbol_hints_total": sum(x["hint_count"] for x in rows),
        "cases_with_hints_in_gold_file": sum(x["hints_on_gold_file"] > 0
                                              for x in rows),
        "cases_with_exact_line_gold_overlap": sum(
            bool(x["exact_line_overlap_ids"]) for x in rows),
        "cases_with_hint_window_gold_overlap": sum(
            bool(x["hint_window_overlap_ids"]) for x in rows),
        "cases_with_new_gold_span_window_coverage": sum(
            bool(x["new_window_overlap_ids"]) for x in rows),
        "hybrid_top8_window_gold_span_hits": sum(
            len(x["hybrid_window_overlap_ids"]) for x in rows),
        "union_with_scoped_hint_window_gold_span_hits": sum(
            len(x["union_window_overlap_ids"]) for x in rows),
        "new_gold_span_window_hits": sum(
            len(x["new_window_overlap_ids"]) for x in rows),
        "cases_with_hints_but_no_gold_window_overlap": sum(
            bool(x["hint_count"]) and not x["hint_window_overlap_ids"]
            for x in rows),
    }


def diagnose(saved, repo, case_records, *, radius=8):
    if not isinstance(saved.get("cases"), list):
        raise ValueError("Saved report is missing cases array")
    by_id = {item["id"]: item for item in case_records}
    ids = [x["id"] for x in saved["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case ID in saved report")
    results = []
    for item in saved["cases"]:
        case = by_id.get(item["id"])
        if case is None:
            raise ValueError("Unknown case ID: " + str(item["id"]))
        if case["suite"] != saved["suite"]:
            raise ValueError("Dataset suite mismatch")
        results.append(diagnose_case(case, item, repo, radius=radius))
    return {
        "suite": saved["suite"],
        "from_run": saved["run_id"],
        "radius": radius,
        "summary": summarize(results),
        "cases": results,
        "limitations": [
            "Replays only saved Hybrid top-8 candidates; no exact-name rescue.",
            "Reconstructed from saved top8_diagnostics; does not rerun ranking.",
            "A +/-8-line hint window is a hypothetical read, not observed evidence.",
            "Gold labels are used solely after choosing candidate symbols.",
            "No LLM, no embeddings and no source code execution.",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-report", type=Path, required=True)
    p.add_argument("--intelligence-index", type=Path)
    p.add_argument("--radius", type=int, default=8)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    if not args.from_report.is_file():
        p.error("Saved ablation JSON missing: " + str(args.from_report))
    if not 0 <= args.radius <= 24:
        p.error("radius must be between 0 and 24")
    saved = json.loads(args.from_report.read_text(encoding="utf-8"))
    if saved.get("suite") not in run.REPOS:
        p.error("Unknown benchmark suite in saved report")
    if saved.get("method", {}).get("frozen_source_commit") != run.REPOS[saved["suite"]][1]:
        p.error("Saved report frozen commit does not match dataset")
    run_id = run.check_run_id(saved.get("run_id", ""))
    index = (args.intelligence_index.expanduser().resolve()
             if args.intelligence_index else
             run.RESULTS / run_id / "_prepared_indexes" / saved["suite"] /
             "middle-files" / "code_intelligence.sqlite")
    if not index.is_file():
        p.error("Read-only SQLite index not found: " + str(index))
    result = diagnose(saved, SimpleNamespace(intelligence_db=index),
                      run.read_cases(), radius=args.radius)
    output = args.out or (
        run.RESULTS / "_diagnostics" / "scoped_hint_evidence_opportunity.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({"summary": result["summary"],
                      "report": str(output)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
