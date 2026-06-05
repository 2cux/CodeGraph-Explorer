# CodeGraph Explorer — one-line installer (Windows PowerShell)
# irm https://raw.githubusercontent.com/2cux/CodeGraph-Explorer/main/install.ps1 | iex
#
# Optional version pin:
#   $env:CODEGRAPH_VERSION="v1.0.0-rc.1"; irm https://... | iex

param()

$REPO = "https://github.com/2cux/CodeGraph-Explorer.git"
$PACKAGE = "codegraph"
$REQUIRED_PYTHON_MAJOR = 3
$REQUIRED_PYTHON_MINOR = 10

$ErrorActionPreference = "Stop"

# --- helpers -------------------------------------------------------------

function Write-Info  { Write-Host "[info]" $args -ForegroundColor Green }
function Write-Warn  { Write-Host "[warn]" $args -ForegroundColor Yellow }
function Write-Err   { Write-Host "[error]" $args -ForegroundColor Red }

function Die {
    Write-Err @args
    exit 1
}

# Run a command and return its combined stdout+stderr as a clean string.
# Usage: Run-Command py -3 -c "print('hello')"
function Run-Command {
    $cmd = $args[0]
    $cmdArgs = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = & $cmd @cmdArgs 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                $_.Exception.Message
            } else {
                $_.ToString()
            }
        }
        return ($lines -join "`n").Trim()
    } finally {
        $ErrorActionPreference = $prevEAP
    }
}

# --- python detection ----------------------------------------------------
# Returns the path to a working Python executable (string).

function Detect-PythonExe {
    # 1. Try py -3 (Windows Python launcher)
    $null = Run-Command py -3 --version
    if ($LASTEXITCODE -eq 0) {
        Write-Info "Using py -3"
        return "py"
    }

    # 2. Try $env:PYTHON if explicitly set
    if ($env:PYTHON) {
        $null = Run-Command $env:PYTHON --version
        if ($LASTEXITCODE -eq 0) {
            Write-Info "Using `$env:PYTHON ($($env:PYTHON))"
            return $env:PYTHON
        }
    }

    # 3. Try python3 and python from PATH
    foreach ($candidate in @("python3", "python")) {
        $found = $null
        try { $found = (Get-Command $candidate -ErrorAction Stop | Select-Object -First 1).Source } catch { }
        if ($found) {
            $null = Run-Command $candidate --version
            if ($LASTEXITCODE -eq 0) {
                Write-Info "Using $candidate ($found)"
                return $candidate
            }
        }
    }

    Die "Python not found. Install Python $REQUIRED_PYTHON_MAJOR.$REQUIRED_PYTHON_MINOR+ from https://python.org and retry."
}

# --- version check -------------------------------------------------------

function Check-PythonVersion {
    param([string]$PythonExe)

    if ($PythonExe -eq "py") {
        $verStr = Run-Command py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    } else {
        $verStr = Run-Command $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    }

    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($verStr)) {
        Die "Failed to query Python version from '$PythonExe'."
    }

    $firstLine = ($verStr -split "`n")[0].Trim()
    $parts = $firstLine -split '\.'
    if ($parts.Count -lt 2) {
        Die "Unexpected Python version format: $verStr"
    }
    $major = [int]$parts[0]
    $minor = [int]$parts[1]

    if ($major -lt $REQUIRED_PYTHON_MAJOR -or ($major -eq $REQUIRED_PYTHON_MAJOR -and $minor -lt $REQUIRED_PYTHON_MINOR)) {
        Die "Python $firstLine detected — need $REQUIRED_PYTHON_MAJOR.$REQUIRED_PYTHON_MINOR+."
    }
    Write-Info "Python $firstLine — ok"
}

# --- pipx -----------------------------------------------------------------

function Ensure-Pipx {
    param([string]$PythonExe)

    # Check if pipx is already on PATH
    try {
        $pipxPath = (Get-Command pipx -ErrorAction Stop | Select-Object -First 1).Source
        $pipxVer = Run-Command pipx --version
        Write-Info "pipx found: $(($pipxVer -split "`n")[0])"
        return $false  # useModulePipx = false
    } catch {
        # pipx not on PATH — install it
    }

    Write-Warn "pipx not found — installing via pip."
    if ($PythonExe -eq "py") {
        Run-Command py -3 -m pip install --user pipx
    } else {
        Run-Command $PythonExe -m pip install --user pipx
    }
    if ($LASTEXITCODE -ne 0) {
        Die "Failed to install pipx."
    }

    if ($PythonExe -eq "py") {
        Run-Command py -3 -m pipx ensurepath
    } else {
        Run-Command $PythonExe -m pipx ensurepath
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "pipx ensurepath returned non-zero (PATH may need a terminal restart)."
    }

    # Refresh PATH for current session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")

    try {
        $null = Get-Command pipx -ErrorAction Stop
        Write-Info "pipx is now available."
        return $false
    } catch {
        Write-Warn "pipx still not on PATH. Will use python -m pipx for installation."
    }

    return $true
}

# --- install --------------------------------------------------------------

function Install-CodeGraph {
    param([string]$PythonExe, [bool]$UseModulePipx)

    if ($env:CODEGRAPH_VERSION) {
        $installUrl = "git+$REPO@$env:CODEGRAPH_VERSION"
        Write-Info "Installing CodeGraph Explorer ($env:CODEGRAPH_VERSION) ..."
    } else {
        $installUrl = "git+$REPO"
        Write-Info "Installing CodeGraph Explorer (latest) ..."
    }

    if ($UseModulePipx) {
        if ($PythonExe -eq "py") {
            Run-Command py -3 -m pipx install --force $installUrl
        } else {
            Run-Command $PythonExe -m pipx install --force $installUrl
        }
    } else {
        Run-Command pipx install --force $installUrl
    }

    if ($LASTEXITCODE -ne 0) {
        Die "pipx install failed."
    }
}

# --- verify ---------------------------------------------------------------

function Verify-Install {
    Write-Info "Verifying installation ..."

    try {
        $null = Get-Command codegraph -ErrorAction Stop
        Run-Command codegraph --help
        if ($LASTEXITCODE -ne 0) { Write-Warn "codegraph --help returned non-zero." }

        $null = Run-Command codegraph doctor --help
        if ($LASTEXITCODE -ne 0) { Write-Warn "codegraph doctor --help returned non-zero." }

        Write-Host ""
        Write-Host "CodeGraph Explorer installed successfully." -ForegroundColor Green
        Write-Host ""
        Write-Host "  Next steps:"
        Write-Host "    cd your-project"
        Write-Host "    codegraph init"
        Write-Host "    codegraph configure all"
        Write-Host "    codegraph doctor"
        return
    } catch {
        # codegraph not on PATH
    }

    # Not on PATH — give clear guidance
    $pipxBin = "$env:USERPROFILE\.local\bin"
    Write-Host ""
    Write-Host "codegraph is installed but not on your current PATH." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Option 1 — Refresh PATH in this terminal:"
    Write-Host '    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" + [System.Environment]::GetEnvironmentVariable("Path","Machine")'
    Write-Host ""
    Write-Host "  Option 2 — Restart PowerShell, then verify with:"
    Write-Host "    codegraph --help"
    Write-Host ""
    Write-Host "  If it still isn't found, check that $pipxBin is listed in:"
    Write-Host '    [Environment]::GetEnvironmentVariable("Path","User")'
    Write-Host ""
    Write-Host "  You may need to run:"
    Write-Host "    python -m pipx ensurepath"
    Write-Host "    # then restart PowerShell"
}

# --- main -----------------------------------------------------------------

function Main {
    Write-Host ""
    Write-Host "CodeGraph Explorer — Installer"
    Write-Host "================================"
    Write-Host ""

    $pythonExe = Detect-PythonExe
    Check-PythonVersion $pythonExe

    $useModulePipx = Ensure-Pipx $pythonExe

    Install-CodeGraph $pythonExe $useModulePipx
    Verify-Install
}

Main
