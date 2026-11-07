"""P1.5 offline top-8 multi-window evidence opportunity test.

This script uses ONLY a saved embedding_compare.py report and pinned benchmark
gold labels. No Ollama, no repository reads, no source execution, no agent
runtime modifications. Existing Hybrid top-8 paths/windows are unchanged.
At most four additional DISTINCT Dense windows in those same files are
selected without accessing gold labels. Recall measured here is hypothetical
window overlap, NOT source observation or citation correctness.

Windows of Dense candidates ranked worse than 8 are not available in the
saved top8_diagnostics, so this is a LOWER-OPPORTUNITY diagnostic, not an
exhaustive multi-window test.
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


def window(row, *, max_lines=48):
    """A bounded source window from existing candidate navigation metadata."""
    path = row.get("path")
    # Hybrid metadata uses line_start/line_end; raw dense_search chunks use
    # start_line/end_line. Accept either without changing source coordinates.
    start = row.get("line_start")
    end = row.get("line_end")
    if start is None:
        start = row.get("start_line")
    if end is None:
        end = row.get("end_line")
    if (not isinstance(path, str) or not path
            or type(start) is not int or type(end) is not int
            or start < 1 or end < start):
        return None
    return (path, start, min(end, start + max_lines - 1))


def extra_lines(candidate, original_windows):
    """Newly exposed lines not already in a Hybrid top-8 window for that path."""
    path, start, end = candidate
    covered = set()
    for other_path, lower, upper in original_windows:
        if path == other_path:
            covered.update(range(max(start, lower), min(end, upper) + 1))
    return (end - start + 1) - len(covered)


def select_alternates(hybrid_top8, dense_top8, *, max_extra=4,
                      min_new_lines=8):
    """Gold-blind alternate selection, ordered by the Dense candidate rank.

    Only returns extra windows in an existing Hybrid top-8 file. The primary
    Hybrid windows and file rank order are immutable.
    """
    max_extra = max(0, min(8, int(max_extra)))
    originals = [w for r in hybrid_top8 if (w := window(r)) is not None]
    paths = {r.get("path") for r in hybrid_top8}
    alternates = []
    existing = list(originals)
    for dense_rank, row in enumerate(dense_top8, 1):
        if len(alternates) >= max_extra:
            break
        candidate = window(row)
        if candidate is None or candidate[0] not in paths:
            continue
        new_lines = extra_lines(candidate, existing)
        if new_lines < min_new_lines:
            continue
        alternates.append({
            "path": candidate[0], "start_line": candidate[1],
            "end_line": candidate[2], "dense_rank": dense_rank,
            "new_lines": new_lines, "citation": False,
        })
        existing.append(candidate)
    return alternates



def select_from_dense_windows(hybrid_top8, windows_by_path, *,
                              max_extra=4, min_new_lines=8):
    """Select alternate chunks from the same dense search's scored inventory.

    Existing Hybrid top8 windows are immutable. Rank candidates by original
    cosine similarity (not gold labels); never consider out-of-scope files.
    """
    allowed={r.get('path') for r in hybrid_top8}
    candidates=[]
    for path, windows in windows_by_path.items():
        if path not in allowed:
            continue
        for item in windows:
            if item.get('path') == path and window(item):
                candidates.append(item)
    candidates.sort(key=lambda row: (
        -float(row.get('similarity',0.0)), row['path'],
        row['start_line']))
    return select_alternates(
        hybrid_top8,candidates,max_extra=max_extra,
        min_new_lines=min_new_lines)

def diagnose_scored_inventory(hybrid_top8, windows_by_path, *,
                              min_new_lines=8):
    """Explain which same-query Dense chunks survive each selection gate.

    Does not select using gold labels and does not change retrieval. Limited
    examples permit a one-case debug run rather than another 20-case pass.
    """
    scope={r.get('path') for r in hybrid_top8}
    baseline=[w for r in hybrid_top8 if (w:=window(r)) is not None]
    eligible=[]
    valid=0
    candidates=0
    matched_paths=0
    multi_paths=0
    qualifying_paths=set()
    samples=[]
    for path in sorted(scope):
        if not isinstance(path,str):
            continue
        chunks=windows_by_path.get(path) or []
        if chunks:
            matched_paths+=1
        if len(chunks)>1:
            multi_paths+=1
        for chunk in chunks:
            candidates+=1
            candidate=window(chunk)
            if candidate is None or candidate[0]!=path:
                continue
            valid+=1
            new_lines=extra_lines(candidate,baseline)
            if new_lines>=min_new_lines:
                qualifying_paths.add(path)
                eligible.append((path,candidate[1],candidate[2],new_lines))
                if len(samples)<8:
                    samples.append({
                        'path':path,'start_line':candidate[1],
                        'end_line':candidate[2],
                        'new_lines':new_lines,
                        'similarity':chunk.get('similarity')
                    })
    return {
        'hybrid_top8_count':len(hybrid_top8),
        'dense_scored_paths_total':len(windows_by_path),
        'top8_paths_in_scored_dense':matched_paths,
        'top8_paths_with_multiple_scored_chunks':multi_paths,
        'scored_chunk_rows_in_top8':candidates,
        'valid_window_rows_in_top8':valid,
        'qualifying_chunk_rows_before_limit':len(eligible),
        'paths_with_qualifying_chunk':len(qualifying_paths),
        'qualifying_examples':samples,
    }


def overlapping_gold_ids(spans, windows):
    """Score windows after all navigation choices are frozen."""
    return {
        span.get("id", str(i + 1)) for i, span in enumerate(spans)
        if any(
            path == span["path"]
            and start <= span["end_line"] and end >= span["start_line"]
            for path, start, end in windows
        )
    }


def inspect_case(saved_case, source_case, *, max_extra=4):
    if saved_case.get("question") != source_case.get("question"):
        raise ValueError("Saved report question differs from benchmark source: "
                         + str(source_case.get("id")))
    variants = saved_case.get("variants") or {}
    hybrid_top8 = (variants.get("hybrid") or {}).get("top8_diagnostics")
    dense_top8 = (variants.get("dense") or {}).get("top8_diagnostics")
    if not isinstance(hybrid_top8, list) or not isinstance(dense_top8, list):
        raise ValueError("Missing Hybrid/Dense top8_diagnostics for " + source_case["id"])
    if len(hybrid_top8) > 8 or len(dense_top8) > 8:
        raise ValueError("top8_diagnostics exceeds 8 candidates")
    # All selection precedes gold access.
    original = [w for row in hybrid_top8 if (w := window(row)) is not None]
    alternate = select_alternates(
        hybrid_top8, dense_top8, max_extra=max_extra)
    extension = [(r["path"], r["start_line"], r["end_line"])
                 for r in alternate]
    # Gold labels are accessed only AFTER selecting alternate windows.
    spans = source_case.get("gold_spans") or []
    old_hits = overlapping_gold_ids(spans, original)
    new_hits = overlapping_gold_ids(spans, original + extension)
    return {
        "id": source_case["id"],
        "gold_span_count": len(spans),
        "hybrid_top8_files": len(hybrid_top8),
        "baseline_valid_windows": len(original),
        "alternates": alternate,
        "extra_window_count": len(alternate),
        "additional_source_lines": sum(r["new_lines"] for r in alternate),
        "hybrid_top8_span_ids": sorted(old_hits),
        "augmented_span_ids": sorted(new_hits),
        "new_span_ids": sorted(new_hits - old_hits),
        "lost_span_ids": sorted(old_hits - new_hits),
    }


def analyze_report(report, cases, *, max_extra=4):
    if not isinstance(report.get("cases"), list):
        raise ValueError("Missing cases array in ablation JSON")
    records = {c["id"]: c for c in cases if c["suite"] == report.get("suite")}
    seen = set()
    analyzed = []
    for item in report["cases"]:
        case_id = item["id"]
        if case_id in seen:
            raise ValueError("Duplicate saved case " + case_id)
        seen.add(case_id)
        case = records.get(case_id)
        if case is None:
            raise ValueError("Unknown benchmark case " + case_id)
        analyzed.append(inspect_case(item, case, max_extra=max_extra))
    baseline = sum(len(row["hybrid_top8_span_ids"]) for row in analyzed)
    augmented = sum(len(row["augmented_span_ids"]) for row in analyzed)
    return {
        "summary": {
            "case_count": len(analyzed),
            "gold_spans_total": sum(row["gold_span_count"] for row in analyzed),
            "hybrid_top8_window_gold_spans": baseline,
            "augmented_top8_window_gold_spans": augmented,
            "new_gold_span_window_hits": augmented - baseline,
            "cases_with_new_gold_span_windows": sum(
                bool(row["new_span_ids"]) for row in analyzed),
            "cases_with_alternates": sum(
                bool(row["extra_window_count"]) for row in analyzed),
            "extra_window_count": sum(row["extra_window_count"] for row in analyzed),
            "additional_source_lines": sum(
                row["additional_source_lines"] for row in analyzed),
            "candidate_files_added": 0,
            "case_gold_span_regressions": sum(
                bool(row["lost_span_ids"]) for row in analyzed),
        },
        "cases": analyzed,
        "limitations": [
            "Only Dense top-8 candidate windows are available in the saved report.",
            "Reads no source; extra_source_lines is a line-count estimate, not tokens.",
            "Window overlap is a hypothetical navigation opportunity, not cited evidence.",
            "Gold spans are read after alternate windows are selected.",
            "Never enables alternate windows in agent runtime.",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-report", type=Path, required=True)
    p.add_argument("--max-extra", type=int, default=4)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    if not args.from_report.is_file():
        p.error("Saved ablation JSON missing: " + str(args.from_report))
    if not 0 <= args.max_extra <= 8:
        p.error("--max-extra must be 0..8")
    saved = json.loads(args.from_report.read_text(encoding="utf-8"))
    suite = saved.get("suite")
    if suite not in run.REPOS:
        p.error("Unknown dataset suite")
    if ((saved.get("method") or {}).get("frozen_source_commit")
            != run.REPOS[suite][1]):
        p.error("Saved source commit does not match pinned benchmark")
    output = analyze_report(saved, run.read_cases(), max_extra=args.max_extra)
    output.update({
        "suite": suite,
        "from_report": str(args.from_report),
        "max_extra": args.max_extra,
    })
    out = args.out or (run.RESULTS / "_diagnostics" /
                       "top8_multiwindow_opportunity.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps(
        {"summary": output["summary"], "report": str(out)},
        ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
