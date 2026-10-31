"""Conservative multi-language declaration hints; never execute inspected code.

Language-adapter output identifies candidate declarations only. Not a full
semantic resolver; for ambiguous syntax, fall back to read_source evidence.
"""
from __future__ import annotations
import re
from pathlib import Path
from language_registry import language_for

PATTERNS = {
    "fortran": (
        ("module", re.compile(r"^\s*module\s+(?!procedure\b|function\b|subroutine\b)([A-Za-z_]\w*)\b", re.I)),
        ("subroutine", re.compile(r"^\s*(?:(?:recursive|pure|elemental|impure|module)\s+)*subroutine\s+([A-Za-z_]\w*)\s*\(",re.I)),
        ("function", re.compile(r"^\s*(?:(?:recursive|pure|elemental|impure|module|real|integer|logical|character|double\s+precision)\s+)*function\s+([A-Za-z_]\w*)\s*\(",re.I)),
        ("program", re.compile(r"^\s*program\s+([A-Za-z_]\w*)\b",re.I)),
        ("type", re.compile(r"^\s*type\s*(?:,\s*[^:]*)?::\s*([A-Za-z_]\w*)\b",re.I)),
    ),
    "go": (
        ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(")),
        ("type", re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface)\b")),
    ),
    "rust": (
        ("function", re.compile(r"^\s*(?:(?:pub(?:\([^)]*\))?|async|unsafe|const|extern\s+\"[^\"]+\")\s+)*fn\s+([A-Za-z_]\w*)\s*[<(]")),
        ("type", re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait|union)\s+([A-Za-z_]\w*)\b")),
    ),
    "cpp": (
        ("type", re.compile(r"^\s*(?:(?:template\s*<[^>]+>)\s*)?(?:class|struct|enum(?:\s+class)?)\s+([A-Za-z_]\w*)\b")),
    ),
    "c": (
        ("type", re.compile(r"^\s*(?:struct|enum|union)\s+([A-Za-z_]\w*)\s*\{")),
    ),
    "javascript": (
        ("function", re.compile(r"^\s*(?:(?:export|default|async)\s+)*function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(")),
        ("class", re.compile(r"^\s*(?:(?:export|default|abstract)\s+)*class\s+([A-Za-z_$][\w$]*)\b")),
        ("function", re.compile(r"^\s*(?:(?:export|declare)\s+)*(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
    ),
    "typescript": (
        ("function", re.compile(r"^\s*(?:(?:export|default|async|declare)\s+)*function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(")),
        ("type", re.compile(r"^\s*(?:(?:export|default|abstract|declare)\s+)*(?:class|interface|type|enum)\s+([A-Za-z_$][\w$]*)\b")),
    ),
    "kotlin": (
        ("function", re.compile(r"^\s*(?:(?:public|private|protected|internal|suspend|inline|override)\s+)*fun\s+(?:[\w.<>?]+\.)?([A-Za-z_]\w*)\s*\(")),
        ("type", re.compile(r"^\s*(?:(?:data|sealed|open|abstract|enum)\s+)*(?:class|interface|object)\s+([A-Za-z_]\w*)\b")),
    ),
    "swift": (
        ("function", re.compile(r"^\s*(?:(?:public|private|internal|static|class|override|mutating)\s+)*func\s+([A-Za-z_]\w*)\s*\(")),
        ("type", re.compile(r"^\s*(?:(?:public|private|internal|open|final)\s+)*(?:class|struct|enum|protocol)\s+([A-Za-z_]\w*)\b")),
    ),
    "php": (
        ("function", re.compile(r"^\s*(?:(?:public|protected|private|static|final|abstract)\s+)*function\s+&?([A-Za-z_]\w*)\s*\(")),
        ("class", re.compile(r"^\s*(?:(?:final|abstract)\s+)?class\s+([A-Za-z_]\w*)\b")),
    ),
    "ruby": (
        ("function", re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[!?=]?)\b")),
        ("class", re.compile(r"^\s*class\s+([A-Za-z_]\w*)\b")),
    ),
}

def lexical_symbols(path: str, source: str):
    """Return (kind,name,line) bounded candidate declarations; no call edges."""
    language=language_for(Path(path))
    if language == "typescript" and Path(path).suffix.lower() in (".tsx",):
        language="typescript"
    patterns=PATTERNS.get(language,())
    found=[]
    for line_no,line in enumerate(source.splitlines(),1):
        stripped=line.lstrip()
        if stripped.startswith(("//","/*","*","#","!","--")):
            continue
        for kind,pattern in patterns:
            match=pattern.search(line)
            if match:
                found.append((kind,match.group(1),line_no))
                break
    return found
