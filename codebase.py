"""Read-only, local source-code discovery. Python standard library only."""
from __future__ import annotations
import fnmatch
import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

EXTENSIONS = {'.java', '.sql', '.as', '.mxml', '.xml', '.properties', '.jsp', '.jspx', '.xhtml', '.gradle', '.yaml', '.yml', '.json', '.md', '.txt', '.fxml', '.actionscript', '.hbm', '.conf'}
EXCLUDE_DIRS = {'.git', '.svn', '.hg', '.idea', '.vscode', 'node_modules', 'target', 'build', 'dist', 'out', 'bin', '.gradle', '.settings', '__pycache__', '.venv', 'venv', 'coverage', '.next'}
MAX_BYTES = 1_000_000
MAX_FILES = 25000

@dataclass
class SourceFile:
    path: str
    fullpath: Path

class Repo:
    def __init__(self, project: str | Path, db_path: str | Path | None = None):
        self.root = Path(project).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('Project must be a directory')
        # Index is stored outside the scanned repository by default.
        self.db_path = Path(db_path).expanduser().resolve() if db_path else (Path.home() / '.local_code_agent' / 'index' / (self.root.name + '-' + hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:12] + '.sqlite'))

    def _safe(self, relpath: str) -> Path:
        if not isinstance(relpath, str) or not relpath.strip():
            raise ValueError('A relative source path is required')
        # Reject absolute/parent traversal on both Windows and POSIX.
        if Path(relpath).is_absolute() or PureWindowsPath(relpath).is_absolute() or ".." in PureWindowsPath(relpath).parts:
            raise ValueError("Only paths relative to the project are allowed")
        p = (self.root / relpath).resolve(strict=False)
        if not p.is_relative_to(self.root) or not p.is_file() or p.suffix.lower() not in EXTENSIONS:
            raise ValueError('Path is not a permitted source file in the project')
        if p.stat().st_size > MAX_BYTES:
            raise ValueError('File is too large')
        return p

    def _read(self, p: Path) -> str:
        raw = p.read_bytes()
        if b'\x00' in raw:
            raise ValueError('Binary file is not supported')
        for enc in ('utf-8-sig', 'cp932', 'utf-16'):
            try:
                return raw.decode(enc)
            except UnicodeError:
                pass
        return raw.decode('utf-8', errors='replace')

    def files(self, pattern: str = '*', limit: int = 250) -> list[SourceFile]:
        found = []
        count = 0
        for base, dirs, filenames in __import__('os').walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS and not (Path(base) / d).is_symlink())
            for name in sorted(filenames):
                p = Path(base) / name
                if p.is_symlink() or p.suffix.lower() not in EXTENSIONS:
                    continue
                try:
                    if p.stat().st_size > MAX_BYTES:
                        continue
                    rel = p.relative_to(self.root).as_posix()
                except (OSError, ValueError):
                    continue
                count += 1
                if count > MAX_FILES:
                    return found
                if fnmatch.fnmatch(rel.lower(), pattern.lower()) or fnmatch.fnmatch(name.lower(), pattern.lower()):
                    found.append(SourceFile(rel, p))
                    if len(found) >= limit:
                        return found
        return found

    def list_files(self, pattern: str = '*', limit: int = 100) -> str:
        items = self.files(pattern, min(max(limit, 1), 200))
        return '\n'.join(f.path for f in items) or '(No matching source files)'

    def read_file(self, path: str, start_line: int = 1, end_line: int = 120) -> str:
        p = self._safe(path)
        lines = self._read(p).splitlines()
        start = max(1, int(start_line)); end = min(len(lines), max(start, int(end_line)), start + 199)
        return '\n'.join(f'{i:5d} | {lines[i-1]}' for i in range(start, end + 1)) or '(Empty file)'

    def search_code(self, query: str, pattern: str = '*', limit: int = 30, regex: bool = False) -> str:
        if not query or len(query) > 200:
            return 'Specify a non-empty query, maximum 200 characters.'
        try:
            matcher = re.compile(query if regex else re.escape(query), re.I)
        except re.error as e:
            return f'Invalid regular expression: {e}'
        result = []
        for sf in self.files(pattern, limit=MAX_FILES):
            try:
                for i, line in enumerate(self._read(sf.fullpath).splitlines(), 1):
                    if matcher.search(line):
                        result.append(f'{sf.path}:{i}: {line.strip()[:240]}')
                        if len(result) >= min(max(limit, 1), 100):
                            return '\n'.join(result)
            except (OSError, ValueError):
                continue
        return '\n'.join(result) if result else '(No matches)'

    def find_symbol(self, symbol: str, limit: int = 40) -> str:
        if not re.fullmatch(r'[\w.$-]{1,120}', symbol):
            return 'Invalid identifier.'
        return self.search_code(r'(?<![\w])' + re.escape(symbol) + r'(?![\w])', limit=limit, regex=True)

    def outline_file(self, path: str) -> str:
        p = self._safe(path); ext = p.suffix.lower()
        lines = self._read(p).splitlines()
        candidates = []
        if ext in ('.java', '.as'):
            patt = re.compile(r'\b(class|interface|enum|record|function|public|protected|private|static|override)\b|\b(?:void|int|String|boolean|Boolean|List|ArrayCollection)\s+\w+\s*\(')
        elif ext in ('.sql', '.xml', '.mxml'):
            patt = re.compile(r'(?i)\b(select|insert\s+into|update|delete\s+from|create\s+table|id=|<mx:|<s:|<fx:|<select|<insert|<update|<delete)')
        else:
            patt = re.compile(r'^\s*(\w[\w.-]*\s*[=:]|#{1,4} )')
        for i, line in enumerate(lines, 1):
            if patt.search(line):
                candidates.append(f'{path}:{i}: {line.strip()[:180]}')
            if len(candidates) >= 75:
                break
        return '\n'.join(candidates) or '(No outline markers found; use read_file)'

    def sql_usage(self, table: str, limit: int = 60) -> str:
        if not re.fullmatch(r'[\w.]{1,128}', table):
            return 'Invalid table identifier.'
        return self.find_symbol(table, limit)

    def _index_signature(self) -> tuple[str, int]:
        """Fingerprint indexed source metadata; no file contents or secrets stored here."""
        digest = hashlib.sha256()
        files = self.files(limit=MAX_FILES)
        for sf in files:
            try:
                stat = sf.fullpath.stat()
                digest.update(f'{sf.path}\0{stat.st_size}\0{stat.st_mtime_ns}\n'.encode('utf-8'))
            except OSError:
                digest.update(f'{sf.path}\0missing\n'.encode('utf-8'))
        return digest.hexdigest(), len(files)

    def ensure_index(self) -> dict:
        """Create or refresh SQLite FTS5 only when repository source metadata changes."""
        signature, count = self._index_signature()
        if self.db_path.is_file():
            try:
                with sqlite3.connect(self.db_path) as conn:
                    old = conn.execute("SELECT value FROM index_metadata WHERE key='signature'").fetchone()
                    if old and old[0] == signature:
                        return {'status':'up-to-date','files':count,'database':str(self.db_path)}
            except sqlite3.DatabaseError:
                pass  # Legacy v3 index has no metadata: rebuild once.
        detail = self.index()
        detail['status'] = 'created-or-refreshed'
        return detail

    def index(self) -> dict:
        """Build FTS index; simple full reset guarantees no stale matches."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(path UNINDEXED, start_line UNINDEXED, end_line UNINDEXED, content, tokenize="unicode61")')
            conn.execute('DELETE FROM code_fts')
            files = self.files(limit=MAX_FILES)
            chunks = 0
            for sf in files:
                try:
                    lines = self._read(sf.fullpath).splitlines()
                except (OSError, ValueError):
                    continue
                for i in range(0, len(lines), 65):
                    part = '\n'.join(lines[i:i + 80])[:14000]
                    conn.execute('INSERT INTO code_fts(path,start_line,end_line,content) VALUES(?,?,?,?)',
                                 (sf.path, i + 1, min(len(lines), i + 80), part))
                    chunks += 1
            conn.execute('CREATE TABLE IF NOT EXISTS index_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            signature, _ = self._index_signature()
            conn.execute("INSERT OR REPLACE INTO index_metadata(key,value) VALUES ('signature',?)", (signature,))
            conn.commit()
            return {'files': len(files), 'chunks': chunks, 'database': str(self.db_path)}
        finally:
            conn.close()

    def semantic_search(self, query: str, limit: int = 10) -> str:
        """FTS lexical retrieval (not vector embeddings)."""
        if not self.db_path.is_file():
            return 'Index not found. Run: python agent.py --project PROJECT index'
        tokens = re.findall(r'[^\W_]+', query, flags=re.UNICODE)
        if not tokens:
            return 'No searchable terms.'
        # OR improves recall for identifiers and Japanese/English combinations.
        expression = ' OR '.join('"' + t.replace('"', '') + '"' for t in tokens[:10])
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute('SELECT path, start_line, end_line, snippet(code_fts,3,"[","]"," … ",16) FROM code_fts WHERE code_fts MATCH ? ORDER BY bm25(code_fts) LIMIT ?', (expression, min(max(limit, 1), 30))).fetchall()
        except sqlite3.Error as e:
            return f'FTS query error: {e}'
        finally:
            conn.close()
        return '\n'.join(f'{p}:{s}-{e}: {snippet}' for p,s,e,snippet in rows) or '(No indexed matches)'
