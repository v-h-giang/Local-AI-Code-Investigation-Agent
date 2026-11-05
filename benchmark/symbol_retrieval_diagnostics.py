"""Offline diagnostic for Dense vs Hybrid+Symbol saved benchmark investigations.

No Ollama, vector search, benchmark rerun or source mutation. Gold spans are
read ONLY for analysis, never for selecting symbols or retrieval candidates.

Usage:
  py -3 benchmark/symbol_retrieval_diagnostics.py \
    --baseline structure_mmr_nemotron_dense_clean \
    --variant hybrid_symbol_4step_01
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import run
from codebase import Repo
from semantic_retrieval import symbol_candidates


def load_machine(run_dir, case_id):
    case_dir = run_dir / case_id
    if not (case_dir / "runner_record.json").is_file():
        raise FileNotFoundError("Missing runner_record.json: " + str(case_dir))
    record = json.loads((case_dir / "runner_record.json").read_text(encoding="utf-8"))
    if not record.get("machine_result_available"):
        raise RuntimeError("Machine result unavailable for " + str(case_dir))
    stdout = case_dir / "stdout.txt"
    raw = stdout.read_text(encoding="utf-8", errors="replace") if stdout.is_file() else ""
    machine = run.load_machine(case_dir, raw)
    return record, machine


def validated_evidence(project, machine):
    evidence = machine.get("evidence") or []
    return {
        ref for row in evidence
        if isinstance(row, dict) and row.get("provenance") == "investigation"
        if (ref := run.valid_ref(project, row))
    }


def candidate_details(project, machine):
    investigation = machine.get("investigation") or {}
    candidates = (investigation.get("file_discovery") or {}).get("candidates") or []
    output = []
    for rank, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict):
            continue
        path = run.valid_candidate_file(project, candidate.get("path"))
        if not path:
            continue
        output.append({
            "rank": rank, "path": path,
            "retrieval_views": candidate.get("retrieval_views") or [],
            "candidate_origin": candidate.get("candidate_origin"),
            "line_hint": candidate.get("line_hint"),
            "line_start": candidate.get("line_start", candidate.get("start_line")),
            "line_end": candidate.get("line_end", candidate.get("end_line")),
            "line_hint_source": candidate.get("line_hint_source"),
        })
    return output


def evidence_hit_sets(case, refs):
    gold = case.get("gold_spans") or []
    files = {span["path"] for span in gold}
    hit_files = {path for path, _ in refs} & files
    hit_spans = {
        span.get("id", str(i + 1))
        for i, span in enumerate(gold)
        if any(path == span["path"] and span["start_line"] <= line <= span["end_line"]
               for path, line in refs)
    }
    return hit_files, hit_spans


def analyze_case(case, project, baseline, variant, matched_symbols):
    _, b = baseline
    _, v = variant
    b_refs = validated_evidence(project, b)
    v_refs = validated_evidence(project, v)
    b_observed = run.visible_tool_refs(project, b.get("investigation") or {})
    v_observed = run.visible_tool_refs(project, v.get("investigation") or {})
    b_file, b_span = evidence_hit_sets(case, b_refs)
    v_file, v_span = evidence_hit_sets(case, v_refs)
    b_obs_file, b_obs_span = evidence_hit_sets(case, b_observed)
    v_obs_file, v_obs_span = evidence_hit_sets(case, v_observed)
    b_candidates = candidate_details(project, b)
    v_candidates = candidate_details(project, v)
    gold_files = {x["path"] for x in case.get("gold_spans") or []}
    symbols = [s for s in matched_symbols if run.valid_candidate_file(project, s["path"])]
    symbol_files = {s["path"] for s in symbols}
    var_top8 = {c["path"] for c in v_candidates[:8]}
    base_top8 = {c["path"] for c in b_candidates[:8]}
    introduced = var_top8 - base_top8
    displaced = base_top8 - var_top8
    symbol_ranks = [
        c for c in v_candidates
        if "exact-symbol" in c["retrieval_views"] or
           c["line_hint_source"] == "exact-symbol"
    ]
    gold_symbol_matches = gold_files & symbol_files
    lost = b_span - v_span
    # These are diagnostic flags, not proven causal explanations.
    flags = []
    if not symbols:
        flags.append("no_exact_symbol_match")
    if symbols and not symbol_ranks:
        flags.append("matched_symbol_not_visible_in_saved_candidates")
    if gold_symbol_matches and not (gold_symbol_matches & var_top8):
        flags.append("gold_symbol_match_not_in_variant_top8")
    if lost and b_obs_span - v_obs_span:
        flags.append("lost_span_not_observed")
    if lost and (b_obs_span & v_obs_span):
        flags.append("some_lost_spans_observed_but_not_in_final_evidence")
    if lost and displaced & gold_files:
        flags.append("gold_file_displaced_from_top8")
    if introduced & gold_files:
        flags.append("gold_file_introduced_into_top8")
    if not lost and v_span - b_span:
        flags.append("new_span_hit")
    return {
        "id": case["id"],
        "question": case["question"],
        "gold_file_paths": sorted(gold_files),
        "gold_spans": case.get("gold_spans") or [],
        "baseline": {
            "candidate_top8": b_candidates[:8],
            "evidence_gold_files": sorted(b_file),
            "evidence_gold_spans": sorted(b_span),
            "observed_gold_files": sorted(b_obs_file),
            "observed_gold_spans": sorted(b_obs_span),
            "steps_used": (b.get("investigation") or {}).get("steps_used"),
        },
        "variant": {
            "candidate_top8": v_candidates[:8],
            "evidence_gold_files": sorted(v_file),
            "evidence_gold_spans": sorted(v_span),
            "observed_gold_files": sorted(v_obs_file),
            "observed_gold_spans": sorted(v_obs_span),
            "steps_used": (v.get("investigation") or {}).get("steps_used"),
            "symbol_view_candidates": symbol_ranks,
        },
        "symbol_inventory": {
            "exact_matches": symbols,
            "matched_gold_file_paths": sorted(gold_symbol_matches),
            "match_count": len(symbols),
        },
        "delta": {
            "lost_gold_files": sorted(b_file - v_file),
            "gained_gold_files": sorted(v_file - b_file),
            "lost_gold_spans": sorted(lost),
            "gained_gold_spans": sorted(v_span - b_span),
            "introduced_top8_files": sorted(introduced),
            "displaced_top8_files": sorted(displaced),
            "flags": flags,
        }
    }


def diagnose(baseline_id, variant_id, suite="repocontextbench", case_ids=()):
    run.check_run_id(baseline_id)
    run.check_run_id(variant_id)
    base_dir = run.RESULTS / baseline_id
    variant_dir = run.RESULTS / variant_id
    if not base_dir.is_dir() or not variant_dir.is_dir():
        raise FileNotFoundError(
            "Saved benchmark run directory missing. Expected: " +
            str(base_dir) + " and " + str(variant_dir))
    configs = []
    for directory in (base_dir, variant_dir):
        file = directory / "run_config.json"
        if not file.is_file():
            raise FileNotFoundError("Missing run_config.json: " + str(file))
        configs.append(json.loads(file.read_text(encoding="utf-8")))
    for field in ("suite", "mode", "model", "host", "repository_commits"):
        if configs[0].get(field) != configs[1].get(field):
            raise RuntimeError("Cannot compare runs with different " + field)
    if configs[1].get("semantic_settings", {}).get("retrieval_mode") != "hybrid_symbol":
        raise RuntimeError("Variant run is not configured for hybrid_symbol")
    for field in ("compression_mode", "prefetch", "embedding_model", "embedding_dimensions",
                  "context_compaction", "claim_audit"):
        b = configs[0].get("semantic_settings") or {}
        v = configs[1].get("semantic_settings") or {}
        if field in b and field in v and b[field] != v[field]:
            raise RuntimeError("Confounding semantic configuration difference: " + field)
    checkout = run.CACHES / run.REPOS[suite][2]
    if not checkout.is_dir():
        raise FileNotFoundError("Frozen source checkout missing: " + str(checkout))
    if run.git("rev-parse", "HEAD", cwd=checkout) != run.REPOS[suite][1]:
        raise RuntimeError("Frozen source checkout is not at expected commit")
    index = variant_dir / "_prepared_indexes" / suite / "middle-files" / "code_intelligence.sqlite"
    if not index.is_file():
        raise FileNotFoundError(
            "Symbol SQLite missing: " + str(index) +
            "\nRecovery: rerun the benchmark with a NEW run-id or rebuild using " +
            "'py -3 agent.py --project benchmark/repositories/" + checkout.name +
            " intelligence --out benchmark/results/<diagnostic-index-folder>'. " +
            "Use --intelligence-index to point this diagnostic at the new index.")
    repo = Repo(checkout)
    repo.intelligence_db = index
    cases = [c for c in run.read_cases() if c["suite"] == suite and
             (not case_ids or c["id"] in case_ids)]
    rows = []
    for case in cases:
        matched = symbol_candidates(repo, case["question"], limit=30)
        rows.append(analyze_case(case, checkout,
                                 load_machine(base_dir, case["id"]),
                                 load_machine(variant_dir, case["id"]),
                                 matched))
    lost_files = sorted({(r["id"], p) for r in rows for p in r["delta"]["lost_gold_files"]})
    lost_spans = sorted({(r["id"], p) for r in rows for p in r["delta"]["lost_gold_spans"]})
    gained_files = sorted({(r["id"], p) for r in rows for p in r["delta"]["gained_gold_files"]})
    gained_spans = sorted({(r["id"], p) for r in rows for p in r["delta"]["gained_gold_spans"]})
    flags = sorted({flag for r in rows for flag in r["delta"]["flags"]})
    summary = {
        "case_count": len(rows),
        "cases_with_exact_symbol_match": sum(bool(r["symbol_inventory"]["exact_matches"]) for r in rows),
        "cases_with_gold_file_symbol_match": sum(bool(r["symbol_inventory"]["matched_gold_file_paths"]) for r in rows),
        "cases_with_symbol_view_candidate": sum(bool(r["variant"]["symbol_view_candidates"]) for r in rows),
        "lost_gold_file_cases": len({case for case, _ in lost_files}),
        "lost_gold_span_cases": len({case for case, _ in lost_spans}),
        "net_gold_file_delta": len(gained_files) - len(lost_files),
        "net_gold_span_delta": len(gained_spans) - len(lost_spans),
        "lost_gold_files": len(lost_files), "gained_gold_files": len(gained_files),
        "lost_gold_spans": len(lost_spans), "gained_gold_spans": len(gained_spans),
        "flag_counts": {flag: sum(flag in r["delta"]["flags"] for r in rows) for flag in flags},
    }
    return {
        "baseline": baseline_id, "variant": variant_id, "suite": suite,
        "configs": configs, "summary": summary, "cases": rows,
        "limitations": [
            "Symbol matches are reconstructed from the stored pinned SQLite index, not logged tool invocations.",
            "A candidate absent from saved top-8 cannot prove that its underlying retrieval view was empty.",
            "Candidate ranks and gold-overlap are observational, not causal attribution.",
            "Gold labels were read for this diagnostic report only; never during agent inference.",
            "Observed refs may be wider than final cited evidence; neither proves semantic answer correctness.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--suite", choices=sorted(run.REPOS), default="repocontextbench")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--intelligence-index", type=Path,
                        help="Optional replacement pinned symbol SQLite when original was deleted")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    # Optional external path is strictly for diagnostic symbol inventory.
    # Do not write to or update the index here.
    if args.intelligence_index:
        raise SystemExit("--intelligence-index is not yet supported; use the stored variant index")
    report = diagnose(args.baseline, args.variant, args.suite, args.case_id)
    out = args.out or (run.RESULTS / "_diagnostics" /
                       (args.baseline + "__vs__" + args.variant + ".json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "report": str(out)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
