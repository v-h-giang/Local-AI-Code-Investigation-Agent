"""Automatic knowledge + source intelligence initialization for main CLI flows.

Both `architecture` and `investigate` call this helper so the user never
needs separate knowledge/intelligence/technologies commands. No Ollama calls.
Missing optional global knowledge degrades retrieval hints, not source analysis.
"""
from __future__ import annotations
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from code_intelligence import build_intelligence
from knowledge_base import build_knowledge, knowledge_status
from repository_knowledge import technology_overview


def prepare_source_context(repo, out, *, verbose=True):
    """Initialize/update global concepts; index source; summarize technologies.

    Return (public status, index result). Do not return general KB concepts as
    source evidence. The manifest is saved under OUTPUT/middle-files/.
    """
    destination=Path(out).expanduser().resolve()
    destination.mkdir(parents=True,exist_ok=True)
    try:
        kb=build_knowledge()
        knowledge={
            "status":"ready",
            "database":kb["database"],
            "concepts":kb["concepts"],
            "updated_packs":kb["updated_packs"],
            "unchanged_packs":kb["unchanged_packs"],
        }
    except (OSError, ValueError, sqlite3.Error, UnicodeError) as exc:
        # Global concepts are advisory only: never prevent source evidence
        # retrieval when the KB directory cannot be written on this machine.
        knowledge={
            "status":"unavailable",
            "error":type(exc).__name__+": "+str(exc)[:160],
        }
        if verbose:
            print("[Source context] Knowledge base unavailable; continuing with source index.",flush=True)

    index=build_intelligence(repo,destination,verbose=verbose)
    with closing(sqlite3.connect(index["index"])) as conn:
        profile_rows=technology_overview(conn,limit=500)
        languages=Counter()
        for row in profile_rows:
            languages[row["language"]]+=row["files"]
        module_count=conn.execute("SELECT COUNT(DISTINCT module) FROM module_profiles").fetchone()[0]

    summary={
        "schema_version":1,
        "knowledge":knowledge,
        "intelligence":{
            "database":index["index"],
            "files":index["files"],
            "changed_files":index["changed_files"],
            "deleted_files":index["deleted_files"],
            "symbols":index["symbols"],
            "relations":index["relations"],
            "graph_rebuilt":index["graph_rebuilt"],
        },
        "technologies":{
            "module_count":module_count,
            "languages":[{"language":name,"files":count}
                         for name,count in sorted(languages.items(),key=lambda row:(-row[1],row[0]))],
            "note":"Detected from source file types; not proof of runtime use or full AST support.",
        },
    }
    state_file=destination/"middle-files"/"source_context.json"
    state_file.parent.mkdir(parents=True,exist_ok=True)
    state_file.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",
                          encoding="utf-8")
    summary["manifest"]=str(state_file)
    return summary,index
