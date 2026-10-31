"""Language/file registry for safe, read-only repository discovery.

File recognition is independent from parser availability. Unsupported grammars
are still indexed as plain text; they must never be called fully parsed.
"""
from __future__ import annotations
from pathlib import Path

LANGUAGE_EXTENSIONS = {
    "fortran": (".f", ".for", ".ftn", ".f77", ".f90", ".f95", ".f03", ".f08", ".f18"),
    "c": (".c", ".h"),
    "cpp": (".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".h++", ".ipp"),
    "cuda": (".cu", ".cuh"),
    "python": (".py", ".pyi"),
    "java": (".java",),
    "csharp": (".cs", ".csx"),
    "go": (".go",),
    "rust": (".rs",),
    "kotlin": (".kt", ".kts"),
    "swift": (".swift",),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
    "php": (".php",),
    "ruby": (".rb", ".rake"),
    "scala": (".scala", ".sc"),
    "dart": (".dart",),
    "lua": (".lua",),
    "r": (".r", ".rmd"),
    "julia": (".jl",),
    "bash": (".sh", ".bash", ".zsh"),
    "powershell": (".ps1", ".psm1", ".psd1"),
    "sql": (".sql",),
    "html": (".html", ".htm", ".jsp", ".jspx", ".xhtml"),
    "css": (".css", ".scss", ".sass", ".less"),
    "xml": (".xml", ".mxml", ".fxml", ".hbm"),
    "yaml": (".yaml", ".yml"),
    "json": (".json", ".jsonl"),
    "toml": (".toml",),
    "markdown": (".md", ".mdx"),
    "config": (".properties", ".gradle", ".conf", ".ini", ".cfg", ".env.example", ".proto", ".tf", ".tfvars", ".hcl"),
    "actionscript": (".as", ".actionscript"),
    "text": (".txt",),
    "cobol": (".cob", ".cbl", ".cpy"),
    "assembly": (".asm", ".s"),
    "protobuf": (".proto",),
}
SOURCE_EXTENSIONS = frozenset(ext for variants in LANGUAGE_EXTENSIONS.values() for ext in variants)
SPECIAL_FILENAMES = frozenset({
    "Dockerfile", "Containerfile", "Makefile", "GNUmakefile",
    "CMakeLists.txt", "Jenkinsfile", "Gemfile", "Rakefile",
    "go.mod", "go.sum", "Cargo.lock", "Pipfile", "Procfile",
    "BUILD", "BUILD.bazel", "WORKSPACE", "WORKSPACE.bazel",
    ".gitignore", ".editorconfig",
})
# The adapter covers declarations only; no language is claimed semantically resolved.
TREE_SITTER_GRAMMARS = {
    ".java": "java", ".cs": "c_sharp", ".go": "go", ".rs": "rust",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "tsx", ".kt": "kotlin", ".swift": "swift",
    ".php": "php", ".rb": "ruby", ".f90": "fortran", ".f95": "fortran",
    ".f03": "fortran", ".f08": "fortran", ".f": "fortran",
}

def is_source_file(path: str | Path) -> bool:
    item = Path(path)
    return item.suffix.lower() in SOURCE_EXTENSIONS or item.name in SPECIAL_FILENAMES

def language_for(path: str | Path) -> str:
    item = Path(path)
    if item.name in ("Dockerfile", "Containerfile"):
        return "docker"
    if item.name in ("Makefile", "GNUmakefile"):
        return "make"
    if item.name == "CMakeLists.txt":
        return "cmake"
    for language, extensions in LANGUAGE_EXTENSIONS.items():
        if item.suffix.lower() in extensions:
            return language
    return "config" if item.name in SPECIAL_FILENAMES else "unknown"

def grammar_for(path: str | Path) -> str | None:
    return TREE_SITTER_GRAMMARS.get(Path(path).suffix.lower())
