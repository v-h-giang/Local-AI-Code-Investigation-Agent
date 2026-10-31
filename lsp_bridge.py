"""Optional import of pre-exported Language Server Protocol symbol locations.

Never launches a language server, executes project code, trusts arbitrary
file:// paths, or treats LSP guesses as source citations. Input is JSON
containing [{symbol,uri,range}] (LSP Location shape plus symbol name).
"""
from __future__ import annotations
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit,unquote
from codebase import Repo

SYMBOL_RE=re.compile(r"^[^\s\0\r\n]{1,160}$")

def _relative_uri(repo:Repo,uri):
    if not isinstance(uri,str) or len(uri)>2000:
        return None
    parts=urlsplit(uri)
    if parts.scheme!="file" or parts.query or parts.fragment:
        return None
    if parts.netloc not in ("","localhost"):
        return None
    raw=unquote(parts.path)
    if re.match(r"^/[A-Za-z]:/",raw):
        raw=raw[1:]  # Windows file URI
    try:
        resolved=Path(raw).resolve(strict=True)
        if not resolved.is_relative_to(repo.root):
            return None
        relative=resolved.relative_to(repo.root).as_posix()
        repo._safe(relative)  # reject unreadable or disallowed source extensions
        return relative
    except (OSError,ValueError):
        return None

def import_lsp_locations(repo:Repo, data_path, *, db_path=None):
    """Import locations to an auxiliary DB table, provenance='external-lsp'.

    This is a safe bridge for exported LSP results, not an LSP client.
    """
    source=Path(data_path).expanduser().resolve(strict=True)
    if source.stat().st_size>2_000_000:
        raise ValueError("LSP export exceeds 2MB")
    data=json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data,list) or len(data)>10000:
        raise ValueError("LSP export must be a JSON array of <=10000 objects")
    target=Path(db_path or getattr(repo,"intelligence_db",None) or repo.db_path)
    if not target.is_file():
        raise ValueError("Build the code intelligence index before importing LSP data")
    accepted=set();rejected=0
    for item in data:
        if not isinstance(item,dict) or not SYMBOL_RE.fullmatch(str(item.get("symbol",""))):
            rejected+=1;continue
        relative=_relative_uri(repo,item.get("uri"))
        start=item.get("range",{}).get("start",{}) if isinstance(item.get("range"),dict) else {}
        line=start.get("line") if isinstance(start,dict) else None
        if relative is None or not isinstance(line,int) or isinstance(line,bool) or line<0:
            rejected+=1;continue
        try:
            lines=repo._read(repo._safe(relative)).splitlines()
            if line>=len(lines):
                rejected+=1;continue
        except (OSError,ValueError):
            rejected+=1;continue
        accepted.add((str(item["symbol"]),relative,line+1))
    with closing(sqlite3.connect(target)) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS lsp_locations(
            symbol TEXT NOT NULL,path TEXT NOT NULL,line INTEGER NOT NULL,
            provenance TEXT NOT NULL,PRIMARY KEY(symbol,path,line)
        )""")
        with conn:
            conn.execute("DELETE FROM lsp_locations")
            conn.executemany(
                "INSERT INTO lsp_locations VALUES (?,?,?,'external-lsp')",
                sorted(accepted))
    return {"imported":len(accepted),"rejected":rejected,
            "database":str(target),"source":str(source),
            "note":"Untrusted external symbol leads only; verify real source lines"}

def lookup_lsp_locations(repo:Repo,symbol,*,db_path=None,limit=30):
    if not isinstance(symbol,str) or not SYMBOL_RE.fullmatch(symbol):
        return []
    target=Path(db_path or getattr(repo,"intelligence_db",None) or repo.db_path)
    if not target.is_file():
        return []
    with closing(sqlite3.connect(target)) as conn:
        tables={x[0] for x in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "lsp_locations" not in tables:
            return []
        rows=conn.execute(
            "SELECT path,line FROM lsp_locations WHERE symbol=? ORDER BY path,line LIMIT ?",
            (symbol,max(1,min(100,int(limit))))).fetchall()
    out=[]
    for path,line in rows:
        try:
            text=repo._read(repo._safe(path)).splitlines()
            if 0<line<=len(text):
                out.append({"path":path,"line":line,"content":text[line-1][:300],
                            "provenance":"external-lsp","citation":False})
        except (OSError,ValueError):
            pass
    return out
