"""P1.6: explain prefetch wins/losses without rerunning retrieval or Ollama.

Analyze SAVED source-backed Evidence Acquisition A/B and corresponding
source-window opportunity report. Does not read source or rerank, and never
uses gold annotations for a retrieval decision.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _as_ids(value, key):
    ids=value.get(key)
    if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids):
        raise ValueError("Missing/invalid "+key)
    return set(ids)


def inspect(prefetch, opportunities):
    if not isinstance(prefetch.get("cases"),list) or not prefetch["cases"]:
        raise ValueError("Missing prefetch cases")
    if not isinstance(opportunities.get("cases"),list):
        raise ValueError("Missing multiwindow cases")
    if prefetch.get("suite")!=opportunities.get("suite"):
        raise ValueError("Benchmark suite mismatch")
    opportunity_rows={r["id"]:r for r in opportunities["cases"]}
    if len(opportunity_rows)!=len(opportunities["cases"]):
        raise ValueError("Duplicate IDs in opportunity report")
    seen=set()
    detail=[]
    for case in prefetch["cases"]:
        ident=case["id"]
        if ident in seen or ident not in opportunity_rows:
            raise ValueError("Duplicate or unmatched case ID: "+ident)
        seen.add(ident)
        variants=case.get("variants") or {}
        if any(k not in variants for k in ("0","1","2")):
            raise ValueError("Missing budget in case "+ident)
        candidate=(opportunity_rows[ident].get("multiwindow_diagnostics") or {})
        opportunities_ids=set(candidate.get("new_gold_span_ids") or [])
        baseline=variants["0"]
        baseline_citable=_as_ids(baseline,"gold_citable_ids")
        budget_deltas={}
        for k in ("1","2"):
            variant=variants[k]
            current=_as_ids(variant,"gold_citable_ids")
            visible=_as_ids(variant,"gold_visible_ids")
            if not current <= visible:
                raise ValueError("Citable gold IDs are not visible for "+ident)
            gained=current-baseline_citable
            lost=baseline_citable-current
            budget_deltas[k]={
                "gained_gold_span_ids":sorted(gained),
                "lost_gold_span_ids":sorted(lost),
                "net_gold_span_change":len(gained)-len(lost),
                "opportunity_span_ids":sorted(opportunities_ids),
                "opportunity_spans_newly_citable":sorted(
                    gained & opportunities_ids),
                "opportunity_spans_still_missing":sorted(
                    opportunities_ids-current),
                "baseline_serialized_chars":baseline["serialized_chars"],
                "variant_serialized_chars":variant["serialized_chars"],
                "delta_serialized_chars":(
                    variant["serialized_chars"]-baseline["serialized_chars"]),
                "baseline_displayed_lines":baseline["displayed_source_lines"],
                "variant_displayed_lines":variant["displayed_source_lines"],
                "requested_alternates":variant["alternate_windows_requested"],
                "emitted_alternates":variant["alternate_windows_emitted"],
                "skipped_alternates":variant["alternate_windows_skipped"],
            }
        if any(d["gained_gold_span_ids"] or d["lost_gold_span_ids"]
               for d in budget_deltas.values()):
            detail.append({"id":ident,"budgets":budget_deltas})
    summary={}
    for k in ("1","2"):
        rows=[r["budgets"][k] for r in detail]
        summary[k]={
            "changed_cases":sum(bool(r["gained_gold_span_ids"] or
                                      r["lost_gold_span_ids"]) for r in rows),
            "cases_with_gains":sum(bool(r["gained_gold_span_ids"]) for r in rows),
            "cases_with_losses":sum(bool(r["lost_gold_span_ids"]) for r in rows),
            "gross_gained_gold_spans":sum(len(r["gained_gold_span_ids"]) for r in rows),
            "gross_lost_gold_spans":sum(len(r["lost_gold_span_ids"]) for r in rows),
            "opportunity_gold_spans_gained":sum(
                len(r["opportunity_spans_newly_citable"]) for r in rows),
        }
    total_opportunities=sum(
        len((r.get("multiwindow_diagnostics") or {}).get("new_gold_span_ids") or [])
        for r in opportunities["cases"] if r["id"] in seen)
    return {
        "summary":{
            "case_count":len(prefetch["cases"]),
            "window_overlap_gold_span_opportunities":total_opportunities,
            "by_budget":summary,
            "case_ids_with_changed_gold_evidence":[row["id"] for row in detail],
        },
        "changed_cases":detail,
        "notes":[
            "Saved refs are counted only if present in previously returned prefetch excerpts.",
            "Window-overlap opportunities are not observed source evidence.",
            "Char-budget reservation may cause regressions; diagnosis is correlational.",
            "No model call, source read, or gold-based retrieval decision takes place.",
        ],
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence-report",type=Path,required=True)
    p.add_argument("--multiwindow-report",type=Path,required=True)
    p.add_argument("--out",type=Path)
    args=p.parse_args(argv)
    for file in (args.evidence_report,args.multiwindow_report):
        if not file.is_file():
            p.error("Missing saved report: "+str(file))
    evidence=json.loads(args.evidence_report.read_text(encoding="utf-8"))
    multiwindow=json.loads(args.multiwindow_report.read_text(encoding="utf-8"))
    result=inspect(evidence,multiwindow)
    out=args.out
    if out:
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                       encoding="utf-8")
    print(json.dumps({
        "summary":result["summary"],
        "changed_cases":result["changed_cases"],
        "report":str(out) if out else None,
    },ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
