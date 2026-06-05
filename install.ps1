# CodeGraph Explorer — one-line installer (Windows PowerShell)
# irm https://raw.githubusercontent.com/2cux/CodeGraph-Explorer/main/install.ps1 | iex
#
# Optional version pin:
#   $env:CODEGRAPH_VERSION="v1.0.0-rc.1"; irm https://... | iex
#
# Verbose mode (shows every command and output):
#   $env:CODEGRAPH_INSTALL_VERBOSE="1"; irm https://... | iex

param()

$REPO = "https://github.com/2cux/CodeGraph-Explorer.git"
$PACKAGE = "codegraph"
$REQUIRED_PYTHON_MAJOR = 3
$REQUIRED_PYTHON_MINOR = 10

# Version check code must NOT use f-strings (Python 2 compatibility for error messages)
$VERSION_CHECK_CODE = "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))"

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

    # Build display string
    $cmdDisplay = if ($Args.Count -gt 0) { "$Exe $($Args -join ' ')" } else { $Exe }

    if ($Script:Verbose) {
        Write-Host "  [cmd] $cmdDisplay" -ForegroundColor Gray
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
        if ($Script:Verbose) {
            Write-Host "  [err] Failed to start: $cmdDisplay — $_" -ForegroundColor DarkYellow
        }
        return @{ ExitCode = -1; Stdout = ""; Stderr = "$_"; TimedOut = $false }
    }

    $finished = $proc.WaitForExit($TimeoutSec * 1000)

    if (-not $finished -or -not $proc.HasExited) {
        try { $proc.Kill() } catch {}
        if ($Script:Verbose) {
            Write-Host "  [err] Timed out after ${TimeoutSec}s: $cmdDisplay" -ForegroundColor DarkYellow
        }
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

    $cmdDisplay = if ($Args.Count -gt 0) { "$Exe $($Args -join ' ')" } else { $Exe }

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
        Write-Err "  Command failed (exit=$($result.ExitCode)): $cmdDisplay"
        if ($result.Stderr) { Write-Err "  $($result.Stderr)" }
        if ($FixSuggestion) {
            Write-Host "  Try:" -ForegroundColor Yellow
            Write-Host "    $FixSuggestion" -ForegroundColor Yellow
        }
        exit 1
    }

    return $result
}

# --- step 1: find Python 3 -----------------------------------------------

function Test-PythonCandidate {
    param(
        [string]$Exe,
        [string[]]$Args,
        [string]$Label
    )

    $allArgs = $Args + @("-c", $VERSION_CHECK_CODE)
    $result = Run-Command -Exe $Exe -Args $allArgs -TimeoutSec 30 -Description "Testing $Label"

    if ($result.ExitCode -ne 0) {
        if ($Script:Verbose) {
            $errBrief = if ($result.Stderr) { ($result.Stderr -split "`n")[0] } else { "exit code $($result.ExitCode)" }
            Write-Host "  [skip] $Label — $errBrief" -ForegroundColor Gray
        }
        return @{ Success = $false; Error = $result.Stderr }
    }

    $verStr = ($result.Stdout -split "`n")[0].Trim()
    if ([string]::IsNullOrWhiteSpace($verStr)) {
        if ($Script:Verbose) {
            Write-Host "  [skip] $Label — empty version output" -ForegroundColor Gray
        }
        return @{ Success = $false; Error = "Empty version output" }
    }

    $parts = $verStr -split '\.'
    if ($parts.Count -lt 2) {
        if ($Script:Verbose) {
            Write-Host "  [skip] $Label — unexpected version format: $verStr" -ForegroundColor Gray
        }
        return @{ Success = $false; Error = "Unexpected version format: $verStr" }
    }

    $major = [int]$parts[0]
    $minor = [int]$parts[1]

    return @{
        Success    = $true
        Major      = $major
        Minor      = $minor
        VersionStr = "$major.$minor"
    }
}

function Find-Python3 {
    Write-Step "[1/5] Finding Python 3..."

    $candidates = @(
        @{ Exe = "py";       Args = @("-3"); Label = "py -3" },
        @{ Exe = "python3";  Args = @();     Label = "python3" },
        @{ Exe = "python";   Args = @();     Label = "python" }
    )

    foreach ($c in $candidates) {
        $r = Test-PythonCandidate -Exe $c.Exe -Args $c.Args -Label $c.Label

        if (-not $r.Success) {
            continue
        }

        # Found a Python, check its version
        if ($r.Major -lt $REQUIRED_PYTHON_MAJOR) {
            Write-Warn "  Found unsupported Python $($r.VersionStr) at $($c.Label), trying next candidate..."
            continue
        }

        if ($r.Major -eq $REQUIRED_PYTHON_MAJOR -and $r.Minor -lt $REQUIRED_PYTHON_MINOR) {
            Write-StepFail
            Die "Found Python $($r.VersionStr) at $($c.Label), but $REQUIRED_PYTHON_MAJOR.$REQUIRED_PYTHON_MINOR+ is required.`n`nInstall from: https://www.python.org/downloads/"
        }

        # Success — found a valid Python 3
        Write-StepOk
        Write-Host "      Using: $($c.Label)" -ForegroundColor Green
        Write-Host "      Version: $($r.VersionStr)" -ForegroundColor Green
        return @{ Exe = $c.Exe; Args = $c.Args; Label = $c.Label; Version = $r.VersionStr }
    }

    # All candidates exhausted
    Write-StepFail
    Die @"
No supported Python 3 installation found.

Please install Python $REQUIRED_PYTHON_MAJOR.$REQUIRED_PYTHON_MINOR+:
  https://www.python.org/downloads/

Then restart PowerShell and verify:
  py -3 --version
"@
}

# --- step 2: git check ---------------------------------------------------

function Check-Git {
    Write-Step "[2/5] Checking Git..."

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

# --- step 3: pipx --------------------------------------------------------

function Ensure-Pipx {
    param([hashtable]$PyInfo)

    Write-Step "[3/5] Checking pipx..."

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

    Run-CommandOrDie -Exe $PyInfo.Exe -Args ($PyInfo.Args + @("-m", "pip", "install", "--user", "pipx")) `
        -TimeoutSec 180 `
        -Description "pip install pipx" `
        -FixSuggestion "Check your internet connection and retry. If behind a proxy, set `$env:HTTP_PROXY and `$env:HTTPS_PROXY."

    Run-CommandOrDie -Exe $PyInfo.Exe -Args ($PyInfo.Args + @("-m", "pipx", "ensurepath")) `
        -TimeoutSec 30 `
        -Description "pipx ensurepath" `
        -FixSuggestion "Run manually: $($PyInfo.Label) -m pipx ensurepath"

    # Refresh PATH for current session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")

    try {
        $null = Get-Command pipx -ErrorAction Stop
        Write-Info "  pipx is now available."
        Write-StepOk
        return $false
    } catch {
        Write-Warn "  pipx still not on PATH. Will use $($PyInfo.Label) -m pipx for installation."
        Write-Host "  After this install completes, run: $($PyInfo.Label) -m pipx ensurepath" -ForegroundColor Yellow
    }

    Write-StepOk
    return $true
}

# --- step 4: install -----------------------------------------------------

function Install-CodeGraph {
    param([hashtable]$PyInfo, [bool]$UseModulePipx)

    Write-Step "[4/5] Installing CodeGraph Explorer..."

    if ($env:CODEGRAPH_VERSION) {
        $installUrl = "git+$REPO@$env:CODEGRAPH_VERSION"
    } else {
        $installUrl = "git+$REPO"
    }

    Write-Host ""
    Write-Info "  Installing from: $installUrl"
    Write-Info "  This may take a few minutes (downloading + building)..."

    if ($UseModulePipx) {
        Run-CommandOrDie -Exe $PyInfo.Exe `
            -Args ($PyInfo.Args + @("-m", "pipx", "install", "--force", $installUrl)) `
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

# --- step 5: verify ------------------------------------------------------

function Verify-Install {
    Write-Step "[5/5] Verifying codegraph command..."

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

    # [1/5]
    $PyInfo = Find-Python3

    # [2/5]
    Check-Git

    # [3/5]
    $useModulePipx = Ensure-Pipx $PyInfo

    # [4/5]
    Install-CodeGraph $PyInfo $useModulePipx

    # [5/5]
    Verify-Install
}

Main
