# CodeGraph Explorer — one-line installer (Windows PowerShell)
# irm https://raw.githubusercontent.com/2cux/CodeGraph-Explorer/main/install.ps1 | iex
#
# Optional version pin:
#   $env:CODEGRAPH_VERSION="v1.0.0-rc.1"; irm https://... | iex
#
# Verbose mode:
#   $env:CODEGRAPH_INSTALL_VERBOSE="1"; irm https://... | iex

param()

$REPO = "https://github.com/2cux/CodeGraph-Explorer.git"
$PACKAGE = "codegraph"
$REQUIRED_PYTHON_MAJOR = 3
$REQUIRED_PYTHON_MINOR = 10

$ErrorActionPreference = "Stop"

# --- helpers -------------------------------------------------------------

$Script:Verbose = [bool]$env:CODEGRAPH_INSTALL_VERBOSE

function Write-Info  { Write-Host "[info]" $args -ForegroundColor Green }
function Write-Warn  { Write-Host "[warn]" $args -ForegroundColor Yellow }
function Write-Err   { Write-Host "[error]" $args -ForegroundColor Red }
function Write-Step  { Write-Host $args -NoNewline }
function Write-StepOk {
    Write-Host " ok" -ForegroundColor Green
}
function Write-StepSkip {
    Write-Host " skip (already present)" -ForegroundColor Gray
}
function Write-StepFail {
    Write-Host " FAILED" -ForegroundColor Red
}

function Die {
    Write-Err @args
    exit 1
}

# Run an external command with optional timeout.
# Returns a hashtable: { ExitCode, Stdout, Stderr, TimedOut }
function Run-Command {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Exe,
        [string[]]$Args = @(),
        [int]$TimeoutSec = 60,
        [string]$Description = ""
    )

    if ($Script:Verbose) {
        $cmdLine = "$Exe $($Args -join ' ')"
        Write-Host "  [cmd] $cmdLine" -ForegroundColor Gray
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = $Args -join ' '
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    # Ensure child process does not prompt for input
    $psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1"
    $psi.EnvironmentVariables["PIP_NO_INPUT"] = "1"
    $psi.EnvironmentVariables["PIP_PROGRESS_BAR"] = "off"

    $proc = $null
    try {
        $proc = [System.Diagnostics.Process]::Start($psi)
    } catch {
        Write-Err "  Failed to start: $Exe $($Args -join ' ')"
        Write-Err "  $_"
        return @{ ExitCode = -1; Stdout = ""; Stderr = $_; TimedOut = $false }
    }

    $finished = $proc.WaitForExit($TimeoutSec * 1000)

    if (-not $finished -or -not $proc.HasExited) {
        try { $proc.Kill() } catch {}
        Write-Err "  Command timed out after ${TimeoutSec}s: $Exe $($Args -join ' ')"
        return @{ ExitCode = -1; Stdout = ""; Stderr = "Timed out after ${TimeoutSec}s"; TimedOut = $true }
    }

    $stdout = $proc.StandardOutput.ReadToEnd().Trim()
    $stderr = $proc.StandardError.ReadToEnd().Trim()

    if ($Script:Verbose) {
        if ($stdout) { Write-Host "  [out] $stdout" -ForegroundColor Gray }
        if ($stderr) { Write-Host "  [err] $stderr" -ForegroundColor DarkYellow }
    }

    return @{
        ExitCode = $proc.ExitCode
        Stdout   = $stdout
        Stderr   = $stderr
        TimedOut = $false
    }
}

function Run-CommandOrDie {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Exe,
        [string[]]$Args = @(),
        [int]$TimeoutSec = 60,
        [string]$Description = "",
        [string]$FixSuggestion = ""
    )

    $result = Run-Command -Exe $Exe -Args $Args -TimeoutSec $TimeoutSec -Description $Description

    if ($result.TimedOut) {
        Write-StepFail
        Write-Err "  Step timed out: $Description"
        Write-Err "  Possible causes:"
        Write-Err "    - Network is unreachable"
        Write-Err "    - $Exe is waiting for input"
        Write-Err "    - Python environment is broken"
        if ($FixSuggestion) {
            Write-Host "  Try:" -ForegroundColor Yellow
            Write-Host "    $FixSuggestion" -ForegroundColor Yellow
        }
        exit 1
    }

    if ($result.ExitCode -ne 0) {
        Write-StepFail
        Write-Err "  Command failed (exit=$($result.ExitCode)): $Exe $($Args -join ' ')"
        if ($result.Stderr) { Write-Err "  $($result.Stderr)" }
        if ($FixSuggestion) {
            Write-Host "  Try:" -ForegroundColor Yellow
            Write-Host "    $FixSuggestion" -ForegroundColor Yellow
        }
        exit 1
    }

    return $result
}

# --- step 1: python detection --------------------------------------------

function Detect-PythonExe {
    Write-Step "[1/6] Checking Python..."

    # 1. Try py -3 (Windows Python launcher)
    $result = Run-Command -Exe py -Args @("-3", "--version") -TimeoutSec 30 -Description "py -3 --version"
    if ($result.ExitCode -eq 0) {
        if ($Script:Verbose) {
            Write-Host "  [ver] $($result.Stdout)" -ForegroundColor Gray
        }
        Write-StepOk
        return "py"
    }

    # 2. Try $env:PYTHON if explicitly set
    if ($env:PYTHON) {
        $result = Run-Command -Exe $env:PYTHON -Args @("--version") -TimeoutSec 30 -Description "$env:PYTHON --version"
        if ($result.ExitCode -eq 0) {
            if ($Script:Verbose) {
                Write-Host "  [ver] $($result.Stdout)" -ForegroundColor Gray
            }
            Write-StepOk
            return $env:PYTHON
        }
    }

    # 3. Try python3 and python from PATH
    foreach ($candidate in @("python3", "python")) {
        $found = $null
        try { $found = (Get-Command $candidate -ErrorAction Stop | Select-Object -First 1).Source } catch {}
        if ($found) {
            $result = Run-Command -Exe $candidate -Args @("--version") -TimeoutSec 30 -Description "$candidate --version"
            if ($result.ExitCode -eq 0) {
                if ($Script:Verbose) {
                    Write-Host "  [ver] $($result.Stdout)" -ForegroundColor Gray
                    Write-Host "  [path] $found" -ForegroundColor Gray
                }
                Write-StepOk
                return $candidate
            }
        }
    }

    Write-StepFail
    Die "Python not found. Install Python $REQUIRED_PYTHON_MAJOR.$REQUIRED_PYTHON_MINOR+ from https://python.org and retry."
}

# --- step 2: python version check ----------------------------------------

function Check-PythonVersion {
    param([string]$PythonExe)

    Write-Step "[2/6] Checking Python version..."

    $pyArgs = if ($PythonExe -eq "py") { @("-3") } else { @() }
    $code = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $result = Run-CommandOrDie -Exe $PythonExe -Args ($pyArgs + @("-c", $code)) `
        -TimeoutSec 30 `
        -Description "Python version check" `
        -FixSuggestion "Verify your Python installation: python --version"

    $verStr = ($result.Stdout -split "`n")[0].Trim()
    if ([string]::IsNullOrWhiteSpace($verStr)) {
        Write-StepFail
        Die "Failed to query Python version from '$PythonExe'."
    }

    $parts = $verStr -split '\.'
    if ($parts.Count -lt 2) {
        Write-StepFail
        Die "Unexpected Python version format: $verStr"
    }
    $major = [int]$parts[0]
    $minor = [int]$parts[1]

    if ($major -lt $REQUIRED_PYTHON_MAJOR -or ($major -eq $REQUIRED_PYTHON_MAJOR -and $minor -lt $REQUIRED_PYTHON_MINOR)) {
        Write-StepFail
        Die "Python $verStr detected — need $REQUIRED_PYTHON_MAJOR.$REQUIRED_PYTHON_MINOR+. Install from https://python.org"
    }

    if ($Script:Verbose) {
        Write-Host "  [ver] Python $verStr (>= $REQUIRED_PYTHON_MAJOR.$REQUIRED_PYTHON_MINOR)" -ForegroundColor Gray
    }
    Write-StepOk
}

# --- step 3: git check ---------------------------------------------------

function Check-Git {
    Write-Step "[3/6] Checking Git..."

    try {
        $gitFound = (Get-Command git -ErrorAction Stop | Select-Object -First 1).Source
    } catch {
        $gitFound = $null
    }

    if ($gitFound) {
        $result = Run-Command -Exe git -Args @("--version") -TimeoutSec 15 -Description "git --version"
        if ($result.ExitCode -eq 0) {
            if ($Script:Verbose) {
                Write-Host "  [ver] $($result.Stdout)" -ForegroundColor Gray
                Write-Host "  [path] $gitFound" -ForegroundColor Gray
            }
            Write-StepOk
            return
        }
    }

    Write-StepFail
    Write-Err "  Git is required to install from git+https://..."
    Write-Err "  Install Git from https://git-scm.com/download/win"
    Write-Err "  After installing, restart PowerShell and run this script again."
    exit 1
}

# --- step 4: pipx --------------------------------------------------------

function Ensure-Pipx {
    param([string]$PythonExe)

    Write-Step "[4/6] Checking pipx..."

    # Check if pipx is already on PATH
    try {
        $pipxPath = (Get-Command pipx -ErrorAction Stop | Select-Object -First 1).Source
        $result = Run-Command -Exe pipx -Args @("--version") -TimeoutSec 30 -Description "pipx --version"
        if ($result.ExitCode -eq 0) {
            if ($Script:Verbose) {
                Write-Host "  [ver] $(($result.Stdout -split "`n")[0])" -ForegroundColor Gray
                Write-Host "  [path] $pipxPath" -ForegroundColor Gray
            }
            Write-StepSkip
            return $false  # useModulePipx = false
        }
    } catch {
        # pipx not on PATH — will install below
    }

    Write-Host ""  # newline after "Checking pipx..."
    Write-Warn "  pipx not found — installing via pip..."

    $pyArgs = if ($PythonExe -eq "py") { @("-3") } else { @() }
    Run-CommandOrDie -Exe $PythonExe -Args ($pyArgs + @("-m", "pip", "install", "--user", "pipx")) `
        -TimeoutSec 180 `
        -Description "pip install pipx" `
        -FixSuggestion "Check your internet connection and retry. If behind a proxy, set `$env:HTTP_PROXY and `$env:HTTPS_PROXY."

    Run-CommandOrDie -Exe $PythonExe -Args ($pyArgs + @("-m", "pipx", "ensurepath")) `
        -TimeoutSec 30 `
        -Description "pipx ensurepath" `
        -FixSuggestion "Run manually: python -m pipx ensurepath"

    # Refresh PATH for current session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")

    try {
        $null = Get-Command pipx -ErrorAction Stop
        Write-Info "  pipx is now available."
        Write-StepOk
        return $false
    } catch {
        Write-Warn "  pipx still not on PATH. Will use python -m pipx for installation."
        Write-Host "  After this install completes, run: python -m pipx ensurepath" -ForegroundColor Yellow
    }

    # reprint step line since we added output
    Write-StepOk
    return $true
}

# --- step 5: install -----------------------------------------------------

function Install-CodeGraph {
    param([string]$PythonExe, [bool]$UseModulePipx)

    Write-Step "[5/6] Installing CodeGraph Explorer..."

    if ($env:CODEGRAPH_VERSION) {
        $installUrl = "git+$REPO@$env:CODEGRAPH_VERSION"
    } else {
        $installUrl = "git+$REPO"
    }

    Write-Host ""
    Write-Info "  Installing from: $installUrl"
    Write-Info "  This may take a few minutes (downloading + building)..."

    if ($UseModulePipx) {
        $pyArgs = if ($PythonExe -eq "py") { @("-3") } else { @() }
        Run-CommandOrDie -Exe $PythonExe `
            -Args ($pyArgs + @("-m", "pipx", "install", "--force", $installUrl)) `
            -TimeoutSec 300 `
            -Description "pipx install CodeGraph Explorer" `
            -FixSuggestion @"
Possible causes:
  - Network cannot reach GitHub
  - Git is not installed or not in PATH
  - Python environment is broken

Try manual install:
  pip install -e "git+$REPO#egg=codegraph&subdirectory="
  # or clone and install:
  git clone $REPO
  cd CodeGraph-Explorer
  pip install -e "backend[mcp,watch]"
"@
    } else {
        Run-CommandOrDie -Exe pipx `
            -Args @("install", "--force", $installUrl) `
            -TimeoutSec 300 `
            -Description "pipx install CodeGraph Explorer" `
            -FixSuggestion @"
Possible causes:
  - Network cannot reach GitHub
  - Git is not installed or not in PATH
  - Python environment is broken

Try manual install:
  git clone $REPO
  cd CodeGraph-Explorer
  pip install -e "backend[mcp,watch]"
"@
    }

    Write-StepOk
}

# --- step 6: verify ------------------------------------------------------

function Verify-Install {
    Write-Step "[6/6] Verifying codegraph command..."

    try {
        $null = Get-Command codegraph -ErrorAction Stop
        $result = Run-Command -Exe codegraph -Args @("--version") -TimeoutSec 30 -Description "codegraph --version"
        if ($result.ExitCode -eq 0) {
            if ($Script:Verbose) {
                Write-Host "  [ver] $($result.Stdout)" -ForegroundColor Gray
            }
        } else {
            Write-Warn "  codegraph --version returned non-zero."
        }

        Write-StepOk
        Write-Host ""
        Write-Host "CodeGraph Explorer installed successfully." -ForegroundColor Green
        Write-Host ""
        Write-Host "  Next steps:"
        Write-Host "    cd your-project"
        Write-Host "    codegraph init"
        Write-Host "    codegraph configure all"
        Write-Host "    codegraph doctor"
        Write-Host ""
        return
    } catch {
        # codegraph not on PATH
    }

    # Not on PATH — give clear guidance
    Write-Host ""
    Write-Host "  codegraph is installed but not on your current PATH." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Option 1 — Refresh PATH in this terminal:"
    Write-Host '    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" + [System.Environment]::GetEnvironmentVariable("Path","Machine")'
    Write-Host ""
    Write-Host "  Option 2 — Restart PowerShell, then verify with:"
    Write-Host "    codegraph --help"
    Write-Host ""
    Write-Host "  If it still isn't found, run:"
    Write-Host "    python -m pipx ensurepath"
    Write-Host "    # then restart PowerShell"
    Write-Host ""

    $pipxBin = "$env:USERPROFILE\.local\bin"
    Write-Host "  Expected pipx bin directory: $pipxBin" -ForegroundColor Gray
    Write-StepOk
}

# --- main -----------------------------------------------------------------

function Main {
    if ($Script:Verbose) {
        Write-Host "[verbose] Verbose mode enabled" -ForegroundColor Gray
        Write-Host "[verbose] PowerShell $($PSVersionTable.PSVersion)" -ForegroundColor Gray
    }

    Write-Host ""
    Write-Host "CodeGraph Explorer — Installer"
    Write-Host "================================"
    Write-Host ""

    # [1/6]
    $pythonExe = Detect-PythonExe

    # [2/6]
    Check-PythonVersion $pythonExe

    # [3/6]
    Check-Git

    # [4/6]
    $useModulePipx = Ensure-Pipx $pythonExe

    # [5/6]
    Install-CodeGraph $pythonExe $useModulePipx

    # [6/6]
    Verify-Install
}

Main
