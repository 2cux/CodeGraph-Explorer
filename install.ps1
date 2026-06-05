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

function Write-Info  { Write-Host "[info] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[warn] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[error] $args" -ForegroundColor Red }

function Die {
    Write-Err $args
    exit 1
}

# --- python detection ----------------------------------------------------

function Detect-Python {
    $candidates = @()
    if ($env:PYTHON) { $candidates += $env:PYTHON }
    $candidates += "py"
    $candidates += "python3"
    $candidates += "python"

    foreach ($c in $candidates) {
        if ($c -eq "py") {
            try {
                $null = & py -3 --version 2>&1
                Write-Info "Using py -3"
                return @("py", "-3")
            } catch { continue }
        }
        try {
            $null = & $c --version 2>&1
            Write-Info "Using $c"
            return @($c)
        } catch { continue }
    }

    Die "Python not found. Install Python $REQUIRED_PYTHON_MAJOR.$REQUIRED_PYTHON_MINOR+ from https://python.org and retry."
}

# --- version check -------------------------------------------------------

function Check-PythonVersion {
    param($PythonCmd)

    $verStr = & $PythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Die "Failed to query Python version."
    }

    $parts = $verStr.Trim() -split '\.'
    $major = [int]$parts[0]
    $minor = [int]$parts[1]

    if ($major -lt $REQUIRED_PYTHON_MAJOR -or ($major -eq $REQUIRED_PYTHON_MAJOR -and $minor -lt $REQUIRED_PYTHON_MINOR)) {
        Die "Python $verStr detected — need $REQUIRED_PYTHON_MAJOR.$REQUIRED_PYTHON_MINOR+."
    }
    Write-Info "Python $verStr — ok"
}

# --- pipx -----------------------------------------------------------------

function Ensure-Pipx {
    param($PythonCmd)

    $pipxFound = $false
    try {
        $null = Get-Command pipx -ErrorAction Stop
        $pipxFound = $true
    } catch {
        $pipxFound = $false
    }

    if ($pipxFound) {
        $pipxVer = & pipx --version 2>&1 | Select-Object -First 1
        Write-Info "pipx found: $pipxVer"
        return $false
    }

    Write-Warn "pipx not found — installing via pip."
    & $PythonCmd -m pip install --user pipx
    if ($LASTEXITCODE -ne 0) {
        Die "Failed to install pipx."
    }

    & $PythonCmd -m pipx ensurepath
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
        Write-Warn "pipx still not on PATH. Using python -m pipx."
    }

    return $true
}

# --- install --------------------------------------------------------------

function Install-CodeGraph {
    param($PythonCmd, $UseModulePipx)

    if ($env:CODEGRAPH_VERSION) {
        $installUrl = "git+$REPO@$env:CODEGRAPH_VERSION"
        Write-Info "Installing CodeGraph Explorer ($env:CODEGRAPH_VERSION) …"
    } else {
        $installUrl = "git+$REPO"
        Write-Info "Installing CodeGraph Explorer (latest) …"
    }

    if ($UseModulePipx) {
        & $PythonCmd -m pipx install --force $installUrl
    } else {
        & pipx install --force $installUrl
    }

    if ($LASTEXITCODE -ne 0) {
        Die "pipx install failed."
    }
}

# --- verify ---------------------------------------------------------------

function Verify-Install {
    Write-Info "Verifying installation …"

    try {
        $null = Get-Command codegraph -ErrorAction Stop
        & codegraph --version
        if ($LASTEXITCODE -ne 0) { Write-Warn "codegraph --version returned non-zero." }

        $null = & codegraph doctor --help 2>&1
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
    Write-Host ""
    Write-Host "codegraph is installed but not on your current PATH." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Run this to update your PATH:"
    Write-Host "    python -m pipx ensurepath"
    Write-Host ""
    Write-Host "  Then restart your terminal (close and reopen), and verify with:"
    Write-Host "    codegraph --version"
}

# --- main -----------------------------------------------------------------

function Main {
    Write-Host ""
    Write-Host "CodeGraph Explorer — Installer"
    Write-Host "================================"
    Write-Host ""

    $pythonCmd = Detect-Python
    Check-PythonVersion $pythonCmd

    $useModulePipx = Ensure-Pipx $pythonCmd

    Install-CodeGraph $pythonCmd $useModulePipx
    Verify-Install
}

Main
