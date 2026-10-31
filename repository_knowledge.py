"""Repository-specific technology/module inventory computed from indexed files.

Distinct from the global knowledge base. All profiles are deterministic,
source-derived metadata; no inference about runtime behavior is implied.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from language_registry import language_for

def module_key(path):
    parts=path.replace("\\","/").split("/")
    if len(parts)>=3 and parts[0]=="dotnet" and parts[1]=="src":
        return "/".join(parts[:3])
    if len(parts)>=3 and parts[0]=="python" and parts[1]=="packages":
        return "/".join(parts[:3])
    if len(parts)>=4 and parts[0]=="python" and parts[1]=="samples":
        return "/".join(parts[:4])
    return "/".join(parts[:2]) if len(parts)>=2 else "(root)"

def ensure_module_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS module_profiles(
        module TEXT NOT NULL,
        language TEXT NOT NULL,
        file_count INTEGER NOT NULL,
        symbol_count INTEGER NOT NULL,
        PRIMARY KEY(module,language)
    )""")

def refresh_module_profiles(conn):
    """Refresh a compact module summary in the same SQLite transaction."""
    ensure_module_schema(conn)
    symbol_counts=dict(conn.execute("SELECT path,COUNT(*) FROM symbols GROUP BY path"))
    counts=Counter()
    symbol_totals=Counter()
    for (path,) in conn.execute("SELECT path FROM files"):
        key=(module_key(path),language_for(path))
        counts[key]+=1
        symbol_totals[key]+=symbol_counts.get(path,0)
    conn.execute("DELETE FROM module_profiles")
    conn.executemany(
        "INSERT INTO module_profiles(module,language,file_count,symbol_count) VALUES(?,?,?,?)",
        [(module,language,n,symbol_totals[(module,language)])
         for (module,language),n in sorted(counts.items())])
    return len(counts)

def technology_overview(conn, limit=60):
    ensure_module_schema(conn)
    return [dict(module=module,language=language,files=files,symbols=symbols)
            for module,language,files,symbols in conn.execute(
                "SELECT module,language,file_count,symbol_count "
                "FROM module_profiles ORDER BY file_count DESC,module,language LIMIT ?",
                (max(1,min(500,int(limit))),))]
