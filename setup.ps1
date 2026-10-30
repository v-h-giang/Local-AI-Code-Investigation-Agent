# First-run setup for Windows PowerShell. Safe to run again.
# Creates a project-local .venv; does not install or start Ollama automatically.
[CmdletBinding()]
param(
    [switch]$PullModel,
    [switch]$WithTreeSitter,
    [switch]$RunTests
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
$venvDir = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

Push-Location $repoRoot
try {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Python launcher (py.exe) not found. Install Python 3.11+ for Windows and enable the Python launcher.'
    }

    # Avoid quoted Python string literals in -c: Windows PowerShell 5.1 may
    # strip embedded double quotes when invoking native commands.
    & py -3 --version
    & py -3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 3.11 or newer is required.'
    }

    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host '[Setup] Creating .venv ...'
        & py -3 -m venv $venvDir
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to create .venv. Check your Python installation.'
        }
    }
    else {
        Write-Host '[Setup] Existing .venv found; keeping installed packages.'
    }

    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw '.venv was created but Scripts\python.exe was not found.'
    }

    & $venvPython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) and sys.prefix != sys.base_prefix else 1)'
    if ($LASTEXITCODE -ne 0) {
        throw 'Invalid or outdated .venv. Rename/remove .venv and run setup again.'
    }
    Write-Host "[Setup] Virtual environment: $venvDir"

    # The application uses Python's standard library by default.
    # Tree-sitter language pack is an optional AST enhancement.
    if ($WithTreeSitter) {
        Write-Host '[Setup] Installing optional Tree-sitter language pack ...'
        & $venvPython -m pip install tree-sitter-language-pack
        if ($LASTEXITCODE -ne 0) {
            throw 'Optional Tree-sitter installation failed.'
        }
    }

    Write-Host '[Setup] Verifying core module imports ...'
    & $venvPython -c 'import agent, codebase, architecture, code_intelligence, investigation_loop'
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to import the application modules.'
    }
    Write-Host '[Setup] Core Python modules: OK'

    if ($RunTests) {
        Write-Host '[Setup] Running production tests ...'
        & $venvPython -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            throw 'Production tests failed.'
        }
        Write-Host '[Setup] Running optional benchmark runner tests ...'
        & $venvPython -m unittest discover -s benchmark/tests -v
        if ($LASTEXITCODE -ne 0) {
            throw 'Benchmark runner tests failed.'
        }
    }

    $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
    if ($PullModel) {
        if (-not $ollamaCommand) {
            throw 'Ollama is not installed or not on PATH. Install Ollama for Windows first.'
        }
        Write-Host '[Setup] Downloading qwen3:8b (explicitly requested) ...'
        & ollama pull qwen3:8b
        if ($LASTEXITCODE -ne 0) {
            throw 'Ollama model download failed. Check the Ollama service and network.'
        }
    }
    elseif (-not $ollamaCommand) {
        Write-Warning 'Ollama was not found. Static analysis works without it; AI workflows need a running Ollama service and qwen3:8b.'
    }
    else {
        Write-Host '[Setup] Ollama command found. Model download skipped; use -PullModel if needed.'
    }

    Write-Host ''
    Write-Host '[Setup] Complete. Use the virtual environment directly (no activation required):'
    Write-Host '  .\.venv\Scripts\python.exe agent.py --project ".\sample_project" architecture --out ".\output\sample-architecture"'
    Write-Host '  .\.venv\Scripts\python.exe -m unittest discover -s tests -v'
    Write-Host '  .\.venv\Scripts\python.exe benchmark\run.py --preflight'
    Write-Host 'Optional activation: .\.venv\Scripts\Activate.ps1'
}
finally {
    Pop-Location
}
