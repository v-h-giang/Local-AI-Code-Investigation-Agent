# First-run setup for Windows PowerShell. Safe to run again.
# Creates a project-local .venv; does not install or start Ollama automatically.
[CmdletBinding()]
param(
    [switch]$PullModel,
    [switch]$WithTreeSitter,
    [switch]$RunTests,
    [ValidateSet('Auto','GPU','CPU','Skip')]
    [string]$OllamaMode = 'Auto',
    [switch]$ProcessOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
$venvDir = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

function Set-RecommendedEnv {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [AllowNull()][string]$Value
    )
    # A null value clears an old CPU mask or GPU override when switching modes.
    if ($null -eq $Value) {
        [Environment]::SetEnvironmentVariable($Name, $null, 'Process')
        if (-not $ProcessOnly) {
            [Environment]::SetEnvironmentVariable($Name, $null, 'User')
        }
        Write-Host "[Setup] $Name=(unset)"
    }
    else {
        [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
        if (-not $ProcessOnly) {
            [Environment]::SetEnvironmentVariable($Name, $Value, 'User')
        }
        Write-Host "[Setup] $Name=$Value"
    }
}

function Set-DefaultEnv {
    param([string]$Name, [string]$Value)
    # Do not overwrite a value deliberately configured outside setup.
    $existing = [Environment]::GetEnvironmentVariable($Name, 'User')
    if (-not $ProcessOnly -and -not [string]::IsNullOrWhiteSpace($existing)) {
        [Environment]::SetEnvironmentVariable($Name, $existing, 'Process')
        Write-Host "[Setup] $Name=$existing (existing User value retained)"
        return
    }
    $existing = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if (-not [string]::IsNullOrWhiteSpace($existing)) {
        Write-Host "[Setup] $Name=$existing (existing Process value retained)"
        return
    }
    Set-RecommendedEnv -Name $Name -Value $Value
}

function Get-LocalHardware {
    $names = @()
    $ramGiB = $null
    try {
        $names = @(Get-CimInstance Win32_VideoController -ErrorAction Stop |
                    ForEach-Object { $_.Name } |
                    Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
    catch {
        Write-Warning 'GPU detection unavailable. Ollama automatic GPU discovery will be used.'
    }
    try {
        $machine = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
        $ramGiB = [math]::Round($machine.TotalPhysicalMemory / 1GB, 1)
    }
    catch {
        Write-Warning 'RAM detection unavailable; conservative 2048-token context recommended.'
    }
    $vendor = 'Unknown'
    # A separate NVIDIA GPU should take precedence over shared-memory iGPU.
    if (@($names | Where-Object { $_ -match 'NVIDIA' }).Count -gt 0) {
        $vendor = 'NVIDIA'
    }
    elseif (@($names | Where-Object { $_ -match 'AMD|Radeon' }).Count -gt 0) {
        $vendor = 'AMD'
    }
    elseif (@($names | Where-Object { $_ -match 'Intel' }).Count -gt 0) {
        $vendor = 'Intel'
    }
    return [pscustomobject]@{
        Vendor = $vendor
        Names = $names
        RamGiB = $ramGiB
    }
}

function Configure-OllamaEnvironment {
    param([string]$Mode)
    Set-DefaultEnv -Name 'PYTHONUTF8' -Value '1'
    Set-DefaultEnv -Name 'PYTHONIOENCODING' -Value 'utf-8'
    if ($Mode -eq 'Skip') {
        Write-Host '[Setup] Ollama environment skipped. UTF-8 still configured.'
        return
    }

    $hardware = Get-LocalHardware
    Write-Host ('[Setup] Detected GPUs: ' + (($hardware.Names | ForEach-Object { $_ }) -join '; '))
    Write-Host "[Setup] Preferred GPU vendor: $($hardware.Vendor); RAM: $($hardware.RamGiB) GiB"
    $selected = $Mode
    if ($Mode -eq 'Auto') {
        $selected = if ($hardware.Vendor -eq 'Unknown') { 'NativeAuto' } else { 'GPU' }
    }
    if ($selected -eq 'GPU' -and $hardware.Vendor -eq 'Unknown') {
        Write-Warning 'GPU requested but no GPU vendor detected; preserving native Ollama auto detection.'
        $selected = 'NativeAuto'
    }

    # Always reset CPU-only masks when returning to Auto/GPU. These variables
    # affect the Ollama SERVER process, not just the Python API client.
    if ($selected -eq 'CPU') {
        Set-RecommendedEnv -Name 'OLLAMA_VULKAN' -Value '0'
        Set-RecommendedEnv -Name 'OLLAMA_IGPU_ENABLE' -Value '0'
        Set-RecommendedEnv -Name 'GGML_VK_VISIBLE_DEVICES' -Value '-1'
        Set-RecommendedEnv -Name 'CUDA_VISIBLE_DEVICES' -Value '-1'
        Set-RecommendedEnv -Name 'ROCR_VISIBLE_DEVICES' -Value '-1'
    }
    else {
        Set-RecommendedEnv -Name 'CUDA_VISIBLE_DEVICES' -Value $null
        Set-RecommendedEnv -Name 'ROCR_VISIBLE_DEVICES' -Value $null
        Set-RecommendedEnv -Name 'GGML_VK_VISIBLE_DEVICES' -Value $null
        if ($hardware.Vendor -eq 'Intel') {
            # Intel integrated graphics require an explicit iGPU opt-in on
            # affected Windows Ollama versions. Vulkan uses shared RAM.
            Set-RecommendedEnv -Name 'OLLAMA_VULKAN' -Value '1'
            Set-RecommendedEnv -Name 'OLLAMA_IGPU_ENABLE' -Value '1'
        }
        elseif ($hardware.Vendor -eq 'NVIDIA') {
            # Prefer CUDA and avoid shared-memory Vulkan iGPU selection in
            # hybrid Intel/NVIDIA laptops.
            Set-RecommendedEnv -Name 'OLLAMA_VULKAN' -Value '0'
            Set-RecommendedEnv -Name 'OLLAMA_IGPU_ENABLE' -Value $null
        }
        else {
            # AMD and unknown vendors retain Ollama's own native/Vulkan
            # detection rather than forcing an unverified compute backend.
            Set-RecommendedEnv -Name 'OLLAMA_VULKAN' -Value $null
            Set-RecommendedEnv -Name 'OLLAMA_IGPU_ENABLE' -Value $null
        }
    }

    # Conservative defaults for memory-constrained code investigation.
    # Preserve existing user overrides; agent.py sends num_ctx=2048 anyway.
    if ($null -eq $hardware.RamGiB -or $hardware.RamGiB -le 24) {
        $defaultContext = '2048'
    }
    elseif ($hardware.RamGiB -le 48) {
        $defaultContext = '4096'
    }
    else {
        $defaultContext = '8192'
    }
    Set-DefaultEnv -Name 'OLLAMA_CONTEXT_LENGTH' -Value $defaultContext
    Set-DefaultEnv -Name 'OLLAMA_NUM_PARALLEL' -Value '1'
    Set-DefaultEnv -Name 'OLLAMA_MAX_LOADED_MODELS' -Value '1'
    $scope = if ($ProcessOnly) { 'Process only' } else { 'User + current Process' }
    Write-Host "[Setup] Ollama mode: $selected; scope: $scope"
    Write-Warning 'GPU detection is heuristic. Stop Ollama via system tray, restart it from Start menu, then run: ollama run qwen3:8b "hello"; ollama ps'
    if ($ProcessOnly) {
        Write-Warning 'ProcessOnly settings are not inherited by an already-running Ollama desktop server. For persistent Windows GUI settings, run setup without -ProcessOnly.'
    }
}

Push-Location $repoRoot
try {
    # Configure before running child Python/test processes.
    Configure-OllamaEnvironment -Mode $OllamaMode

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

    # Offline curated programming knowledge is independent from any project.
    # A failed user-profile write must never prevent source search or setup.
    Write-Host '[Setup] Initializing local universal programming knowledge ...'
    & $venvPython -c 'from knowledge_base import build_knowledge; print(build_knowledge())'
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Knowledge Base initialization failed. Basic source indexing still works; retry with: python agent.py --project . knowledge build'
    }

    if ($RunTests) {
        # unittest writes progress to stderr even on success; preserve its raw
        # output in files instead of treating normal output as PowerShell errors.
        $logDir = Join-Path $venvDir 'setup-logs'
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $failedSuites = @()
        foreach ($suite in @('tests', 'benchmark/tests')) {
            $label = if ($suite -eq 'tests') { 'production' } else { 'benchmark' }
            $stdoutLog = Join-Path $logDir ($label + '.stdout.log')
            $stderrLog = Join-Path $logDir ($label + '.stderr.log')
            Write-Host "[Setup] Running $label tests; full logs: $stderrLog"
            $process = Start-Process -FilePath $venvPython -NoNewWindow -Wait -PassThru -ArgumentList @('-m', 'unittest', 'discover', '-s', $suite, '-v') -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
            $exitCode = $process.ExitCode
            $tail = @(Get-Content -LiteralPath $stderrLog -Tail 12 -ErrorAction SilentlyContinue)
            foreach ($line in $tail) { Write-Host $line }
            if ($exitCode -ne 0) {
                $failedSuites += $label
                Write-Warning "$label tests failed (exit code $exitCode). See $stderrLog"
            }
            else {
                Write-Host "[Setup] $label tests passed."
            }
        }
        if ($failedSuites.Count -gt 0) {
            throw ('Unit tests failed: ' + ($failedSuites -join ', ') +
                   ". Setup succeeded; send *.stderr.log from $logDir for diagnosis.")
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
    Write-Host 'Backend override examples: .\setup.ps1 -OllamaMode CPU | .\setup.ps1 -OllamaMode GPU'
    Write-Host 'Restart Ollama after changing backend. ollama ps verifies actual CPU/GPU use.'
}
finally {
    Pop-Location
}
