#!/usr/bin/env sh
set -eu

# CodeGraph Explorer — one-line installer (macOS / Linux)
# curl -fsSL https://raw.githubusercontent.com/2cux/CodeGraph-Explorer/main/install.sh | sh
#
# Optional version pin:
#   CODEGRAPH_VERSION=v1.0.0-rc.1 curl -fsSL ... | sh
#
# Verbose mode:
#   CODEGRAPH_INSTALL_VERBOSE=1 curl -fsSL ... | sh

REPO="https://github.com/2cux/CodeGraph-Explorer.git"
PACKAGE="codegraph"
REQUIRED_PYTHON_MAJOR=3
REQUIRED_PYTHON_MINOR=10

VERBOSE="${CODEGRAPH_INSTALL_VERBOSE:-0}"

# --- helpers -------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

say()        { printf "%b\n" "$*"; }
info()       { say "${GREEN}[info]${NC} $*"; }
warn()       { say "${YELLOW}[warn]${NC} $*" >&2; }
err()        { say "${RED}[error]${NC} $*" >&2; }
die()        { err "$@"; exit 1; }
step()       { printf "%b" "$*"; }
step_ok()    { say " ${GREEN}ok${NC}"; }
step_skip()  { say " ${GRAY}skip (already present)${NC}"; }
step_fail()  { say " ${RED}FAILED${NC}" >&2; }
verbose()    { if [ "$VERBOSE" = "1" ]; then say "${GRAY}  [verbose] $*${NC}"; fi; }

# Run a command with a timeout.
# Usage: run_cmd <timeout_sec> <description> <cmd> [args...]
# Returns the exit code; output captured to $CMD_STDOUT / $CMD_STDERR
CMD_STDOUT=""
CMD_STDERR=""

run_cmd() {
    timeout_sec="$1"; shift
    desc="$1"; shift

    if [ "$VERBOSE" = "1" ]; then
        say "${GRAY}  [cmd] $*${NC}"
    fi

    CMD_STDOUT=""
    CMD_STDERR=""

    # Use a temp file for output capture with timeout
    tmp_out="$(mktemp 2>/dev/null || echo "/tmp/codegraph_install_$$.out")"
    tmp_err="$(mktemp 2>/dev/null || echo "/tmp/codegraph_install_$$.err")"
    # Ensure clean temp files
    : > "$tmp_out"
    : > "$tmp_err"

    # Run command in background, wait with timeout
    "$@" >"$tmp_out" 2>"$tmp_err" &
    pid=$!

    elapsed=0
    while [ $elapsed -lt "$timeout_sec" ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        # Still running — timeout
        kill "$pid" 2>/dev/null || true
        sleep 1
        kill -9 "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        CMD_STDOUT="$(cat "$tmp_out" 2>/dev/null || true)"
        CMD_STDERR="Timed out after ${timeout_sec}s"
        rm -f "$tmp_out" "$tmp_err" 2>/dev/null || true
        return 124  # same as timeout command
    fi

    wait "$pid" 2>/dev/null || true
    exit_code=$?
    CMD_STDOUT="$(cat "$tmp_out" 2>/dev/null || true)"
    CMD_STDERR="$(cat "$tmp_err" 2>/dev/null || true)"
    rm -f "$tmp_out" "$tmp_err" 2>/dev/null || true

    if [ "$VERBOSE" = "1" ]; then
        [ -n "$CMD_STDOUT" ] && say "${GRAY}  [out] $CMD_STDOUT${NC}"
        [ -n "$CMD_STDERR" ] && say "${GRAY}  [err] $CMD_STDERR${NC}"
    fi

    return $exit_code
}

# Run a command or die with a helpful message.
run_cmd_or_die() {
    timeout_sec="$1"; shift
    desc="$1"; shift
    fix="$1"; shift

    run_cmd "$timeout_sec" "$desc" "$@"
    rc=$?

    if [ $rc -eq 124 ]; then
        step_fail
        err "  Command timed out after ${timeout_sec}s: $desc"
        err "  Possible causes:"
        err "    - Network is unreachable"
        err "    - Command is waiting for input"
        err "    - Python environment is broken"
        [ -n "$fix" ] && say "${YELLOW}  Try:${NC}"
        [ -n "$fix" ] && say "${YELLOW}    $fix${NC}"
        exit 1
    fi

    if [ $rc -ne 0 ]; then
        step_fail
        err "  Command failed (exit=$rc): $*"
        [ -n "$CMD_STDERR" ] && err "  $CMD_STDERR"
        [ -n "$fix" ] && say "${YELLOW}  Try:${NC}"
        [ -n "$fix" ] && say "${YELLOW}    $fix${NC}"
        exit 1
    fi
}

# --- step 1: python detection --------------------------------------------

detect_python() {
    step "[1/6] Checking Python..."

    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            run_cmd 30 "python detection" "$candidate" --version
            if [ $? -eq 0 ]; then
                verbose "Python path: $(command -v "$candidate")"
                step_ok
                printf "%s" "$candidate"
                return 0
            fi
        fi
    done

    step_fail
    die "Python not found. Install Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+ and retry."
}

# --- step 2: python version check ----------------------------------------

check_python_version() {
    py="$1"
    step "[2/6] Checking Python version..."

    run_cmd 30 "python version check" "$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if [ $? -ne 0 ] || [ -z "$CMD_STDOUT" ]; then
        step_fail
        die "Failed to query Python version from '$py'."
    fi

    ver="$(echo "$CMD_STDOUT" | head -n1 | tr -d '[:space:]')"
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)

    if [ "$major" -lt "$REQUIRED_PYTHON_MAJOR" ] || { [ "$major" -eq "$REQUIRED_PYTHON_MAJOR" ] && [ "$minor" -lt "$REQUIRED_PYTHON_MINOR" ]; }; then
        step_fail
        die "Python $ver detected — need ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+."
    fi

    verbose "Python $ver (>= ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR})"
    step_ok
}

# --- step 3: git check ---------------------------------------------------

check_git() {
    step "[3/6] Checking Git..."

    if command -v git >/dev/null 2>&1; then
        run_cmd 15 "git check" git --version
        if [ $? -eq 0 ]; then
            verbose "Git: $(echo "$CMD_STDOUT" | head -n1)"
            step_ok
            return 0
        fi
    fi

    step_fail
    err "  Git is required to install from git+https://..."
    err "  Install Git:"
    err "    macOS:   brew install git"
    err "    Linux:   sudo apt install git  (or your package manager)"
    err "  After installing, re-run this script."
    exit 1
}

# --- step 4: pipx --------------------------------------------------------

# Returns "true" if we must use "python -m pipx" instead of bare "pipx"
ensure_pipx() {
    py="$1"
    step "[4/6] Checking pipx..."

    if command -v pipx >/dev/null 2>&1; then
        run_cmd 30 "pipx version" pipx --version
        if [ $? -eq 0 ]; then
            verbose "pipx: $(echo "$CMD_STDOUT" | head -n1)"
            step_skip
            printf "%s" "false"
            return 0
        fi
    fi

    echo ""  # newline after step header
    warn "  pipx not found — installing via pip..."

    run_cmd_or_die 180 "pip install pipx" \
        "Check your internet connection and retry. If behind a proxy, set HTTP_PROXY/HTTPS_PROXY." \
        "$py" -m pip install --user pipx

    run_cmd_or_die 30 "pipx ensurepath" \
        "Run manually: python3 -m pipx ensurepath" \
        "$py" -m pipx ensurepath

    # Refresh PATH for current session
    export PATH="$HOME/.local/bin:$PATH"

    if command -v pipx >/dev/null 2>&1; then
        info "  pipx is now available."
        step_ok
        printf "%s" "false"
        return 0
    fi

    warn "  pipx still not on PATH. Falling back to python -m pipx."
    step_ok
    printf "%s" "true"
    return 0
}

# --- step 5: install -----------------------------------------------------

install_codegraph() {
    py="$1"
    use_module_pipx="$2"
    step "[5/6] Installing CodeGraph Explorer..."
    echo ""

    if [ -n "${CODEGRAPH_VERSION:-}" ]; then
        install_url="git+${REPO}@${CODEGRAPH_VERSION}"
    else
        install_url="git+${REPO}"
    fi

    info "  Installing from: $install_url"
    info "  This may take a few minutes (downloading + building)..."

    fix_msg="Possible causes:
  - Network cannot reach GitHub
  - Git is not installed or not in PATH
  - Python environment is broken

Manual install:
  git clone $REPO
  cd CodeGraph-Explorer
  pip install -e \"backend[mcp,watch]\""

    if [ "$use_module_pipx" = "true" ]; then
        run_cmd_or_die 300 "pipx install CodeGraph Explorer" "$fix_msg" \
            "$py" -m pipx install --force "$install_url"
    else
        run_cmd_or_die 300 "pipx install CodeGraph Explorer" "$fix_msg" \
            pipx install --force "$install_url"
    fi

    step_ok
}

# --- step 6: verify ------------------------------------------------------

verify_install() {
    step "[6/6] Verifying codegraph command..."

    if command -v codegraph >/dev/null 2>&1; then
        run_cmd 30 "codegraph --version" codegraph --version
        if [ $? -ne 0 ]; then
            warn "  codegraph --version returned non-zero."
        else
            verbose "codegraph: $(echo "$CMD_STDOUT" | head -n1)"
        fi
        step_ok
        echo ""
        say "${GREEN}CodeGraph Explorer installed successfully.${NC}"
        echo ""
        say "  Next steps:"
        say "    cd your-project"
        say "    codegraph init"
        say "    codegraph configure all"
        say "    codegraph doctor"
        echo ""
        return 0
    fi

    # Not on PATH — give clear guidance
    echo ""
    say "${YELLOW}  codegraph is installed but not on your current PATH.${NC}"
    echo ""
    say "  Refresh PATH in this terminal:"
    say '    export PATH="$HOME/.local/bin:$PATH"'
    echo ""
    say "  Then verify with:"
    say "    codegraph --version"
    echo ""
    say "  If it still isn't found, run:"
    say "    python3 -m pipx ensurepath"
    say "    # then restart your terminal"
    echo ""
    verbose "Expected pipx bin directory: $HOME/.local/bin"
    step_ok
    return 0
}

# --- main -----------------------------------------------------------------

main() {
    if [ "$VERBOSE" = "1" ]; then
        say "${GRAY}[verbose] Verbose mode enabled${NC}"
        say "${GRAY}[verbose] Shell: $(sh --version 2>/dev/null | head -n1 || echo 'sh')${NC}"
    fi

    echo ""
    say "CodeGraph Explorer — Installer"
    say "================================"
    echo ""

    # [1/6]
    PYTHON=$(detect_python)

    # [2/6]
    check_python_version "$PYTHON"

    # [3/6]
    check_git

    # [4/6]
    USE_MODULE_PIPX=$(ensure_pipx "$PYTHON")

    # [5/6]
    install_codegraph "$PYTHON" "$USE_MODULE_PIPX"

    # [6/6]
    verify_install
}

main
