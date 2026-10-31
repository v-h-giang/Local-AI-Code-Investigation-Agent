"""Versioned, offline, read-only-query global programming knowledge base.

The DB stores curated CONCEPT hints, not facts about the inspected repository.
Only verified source lines can be cited as evidence. All connections explicitly
close (important for Windows TemporaryDirectory cleanup).
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

DEFAULT_PACK_DIR = Path(__file__).resolve().parent / "knowledge" / "packs"
ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,119}$")
SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS knowledge_packs(
    pack_id TEXT PRIMARY KEY, version TEXT NOT NULL, sha256 TEXT NOT NULL,
    license TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS concepts(
    concept_id TEXT PRIMARY KEY, pack_id TEXT NOT NULL,
    domain TEXT NOT NULL, label TEXT NOT NULL,
    description TEXT NOT NULL, provenance TEXT NOT NULL,
    FOREIGN KEY(pack_id) REFERENCES knowledge_packs(pack_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS aliases(
    concept_id TEXT NOT NULL, alias TEXT NOT NULL, normalized TEXT NOT NULL,
    PRIMARY KEY(concept_id,normalized),
    FOREIGN KEY(concept_id) REFERENCES concepts(concept_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS aliases_normalized ON aliases(normalized);
CREATE TABLE IF NOT EXISTS concept_relations(
    source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL,
    PRIMARY KEY(source_id,target_id,kind),
    FOREIGN KEY(source_id) REFERENCES concepts(concept_id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES concepts(concept_id) ON DELETE CASCADE
);
"""

def database_path(db_path=None) -> Path:
    if db_path is not None:
        return Path(db_path).expanduser().resolve()
    env=os.environ.get("LOCAL_CODE_AGENT_KB_PATH")
    return (Path(env).expanduser().resolve() if env
            else Path.home()/".local_code_agent"/"knowledge"/"global_code_knowledge.sqlite")

def _normalize(text):
    return re.sub(r"\s+", " ", str(text).casefold().strip())

def _validate_pack(raw):
    if not isinstance(raw,dict) or raw.get("schema_version")!=1:
        raise ValueError("Knowledge pack requires schema_version=1")
    pack_id=raw.get("pack_id")
    if not isinstance(pack_id,str) or not ID_RE.fullmatch(pack_id):
        raise ValueError("Invalid knowledge pack id")
    if not isinstance(raw.get("version"),str) or len(raw["version"])>40:
        raise ValueError("Invalid knowledge pack version")
    if not isinstance(raw.get("license"),str) or len(raw["license"])>100:
        raise ValueError("Knowledge pack must declare a license")
    records=raw.get("concepts")
    if not isinstance(records,list) or len(records)>3000:
        raise ValueError("Invalid knowledge concept list")
    known=set()
    for item in records:
        if not isinstance(item,dict):
            raise ValueError("Invalid concept entry")
        cid=item.get("id")
        if not isinstance(cid,str) or not ID_RE.fullmatch(cid) or cid in known:
            raise ValueError("Duplicate or invalid concept id")
        known.add(cid)
        for key in ("domain","label","description","source"):
            if not isinstance(item.get(key),str) or not item[key].strip() or len(item[key])>1200:
                raise ValueError("Invalid concept field: "+key)
        aliases=item.get("aliases")
        if not isinstance(aliases,list) or not aliases or len(aliases)>50:
            raise ValueError("A concept needs 1..50 aliases")
        if any(not isinstance(a,str) or not a.strip() or len(a)>120 for a in aliases):
            raise ValueError("Invalid concept alias")
    relations=raw.get("relations",[])
    if not isinstance(relations,list) or len(relations)>10000:
        raise ValueError("Invalid concept relations")
    for edge in relations:
        if (not isinstance(edge,dict)
            or edge.get("from") not in known or edge.get("to") not in known
            or edge.get("kind") not in ("related","equivalent","prerequisite")):
            raise ValueError("Invalid or cross-pack concept relation")
    return raw

def build_knowledge(*, db_path=None, pack_dir=None):
    """Install/update local JSON packs transactionally; no external requests."""
    dest=database_path(db_path)
    folder=Path(pack_dir).expanduser().resolve() if pack_dir else DEFAULT_PACK_DIR
    packs=sorted(folder.glob("*.json"))
    if not packs:
        raise ValueError("No knowledge packs in "+str(folder))
    if len(packs)>100:
        raise ValueError("Too many packs")
    dest.parent.mkdir(parents=True,exist_ok=True)
    updated=[];skipped=[]
    with closing(sqlite3.connect(dest)) as conn:
        conn.executescript(SCHEMA)
        for path in packs:
            if path.is_symlink() or path.stat().st_size>2_000_000:
                raise ValueError("Knowledge pack is symlinked or too large")
            contents=path.read_bytes()
            raw=_validate_pack(json.loads(contents.decode("utf-8-sig")))
            sha=hashlib.sha256(contents).hexdigest()
            old=conn.execute("SELECT sha256 FROM knowledge_packs WHERE pack_id=?",
                             (raw["pack_id"],)).fetchone()
            if old and old[0]==sha:
                skipped.append(raw["pack_id"])
                continue
            with conn:
                # FK cascades remove stale aliases and relationships.
                conn.execute("DELETE FROM knowledge_packs WHERE pack_id=?",(raw["pack_id"],))
                conn.execute("INSERT INTO knowledge_packs VALUES (?,?,?,?)",
                    (raw["pack_id"],raw["version"],sha,raw["license"]))
                for item in raw["concepts"]:
                    conn.execute("INSERT INTO concepts VALUES (?,?,?,?,?,?)",
                        (item["id"],raw["pack_id"],item["domain"],item["label"],
                         item["description"],item["source"]))
                    for alias in dict.fromkeys([item["label"],*item["aliases"]]):
                        conn.execute("INSERT OR IGNORE INTO aliases VALUES (?,?,?)",
                            (item["id"],alias,_normalize(alias)))
                for edge in raw.get("relations",[]):
                    conn.execute("INSERT INTO concept_relations VALUES (?,?,?)",
                        (edge["from"],edge["to"],edge["kind"]))
            updated.append(raw["pack_id"])
        count=conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
    return {"database":str(dest),"updated_packs":updated,
            "unchanged_packs":skipped,"concepts":count}

def _bootstrap(db_path=None):
    path=database_path(db_path)
    if not path.is_file():
        build_knowledge(db_path=path)
    return path

def query_knowledge(question, *, db_path=None, limit=8):
    """Exact alias/phrase matching with word boundaries and known provenance.

    Returns general conceptual hints, never source citations.
    """
    if not isinstance(question,str) or not question.strip():
        return []
    path=_bootstrap(db_path)
    query=_normalize(question)
    hits={}
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory=sqlite3.Row
        rows=conn.execute("""
            SELECT c.concept_id,c.domain,c.label,c.description,c.provenance,
                   a.alias,a.normalized
            FROM concepts c JOIN aliases a ON c.concept_id=a.concept_id
            WHERE length(a.normalized)>=3
        """)
        for r in rows:
            alias=r["normalized"]
            if not re.search(r"(?<!\w)"+re.escape(alias)+r"(?!\w)",query):
                continue
            cid=r["concept_id"]
            quality=len(alias)+ (20 if " " in alias else 0)
            prev=hits.get(cid)
            if prev is None or quality>prev["score"]:
                hits[cid]={"concept_id":cid,"domain":r["domain"],
                    "label":r["label"],"description":r["description"],
                    "provenance":r["provenance"],"matched_alias":r["alias"],
                    "score":quality,"citation":False}
    return sorted(hits.values(),key=lambda x:(-x["score"],x["concept_id"]))[:max(1,min(30,int(limit)))]

def expand_query_terms(question, *, db_path=None, max_terms=6):
    """Bounded KB aliases to enrich lexical retrieval; no network or Qwen."""
    try:
        matched=query_knowledge(question,db_path=db_path,limit=4)
        if not matched:
            return []
        ids=[row["concept_id"] for row in matched]
        path=database_path(db_path)
        expanded=[]
        with closing(sqlite3.connect(path)) as conn:
            for cid in ids:
                aliases=conn.execute(
                    "SELECT normalized FROM aliases WHERE concept_id=? ORDER BY length(normalized) DESC",
                    (cid,)).fetchall()
                for (alias,) in aliases:
                    # FTS words are single tokens. Multiword aliases are useful
                    # for matching but not injected as broad FTS OR phrases.
                    if " " in alias or len(alias)<4 or not re.fullmatch(r"[a-z][a-z0-9_]*",alias):
                        continue
                    if alias not in question.casefold() and alias not in expanded:
                        expanded.append(alias)
                    if len(expanded)>=max_terms:
                        return expanded
        return expanded
    except (OSError,sqlite3.Error,ValueError,UnicodeError):
        # A missing/unwritable KB never disables existing code search.
        return []

def knowledge_status(*,db_path=None):
    path=database_path(db_path)
    if not path.is_file():
        return {"database":str(path),"exists":False,"packs":0,"concepts":0}
    with closing(sqlite3.connect(path)) as conn:
        return {"database":str(path),"exists":True,
                "packs":conn.execute("SELECT COUNT(*) FROM knowledge_packs").fetchone()[0],
                "concepts":conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]}
