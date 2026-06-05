#!/usr/bin/env sh
set -eu

# CodeGraph Explorer — one-line installer (macOS / Linux)
# curl -fsSL https://raw.githubusercontent.com/2cux/CodeGraph-Explorer/main/install.sh | sh
#
# Optional version pin:
#   CODEGRAPH_VERSION=v1.0.0-rc.1 curl -fsSL ... | sh
#
# Verbose mode (shows every command and output):
#   CODEGRAPH_INSTALL_VERBOSE=1 curl -fsSL ... | sh

REPO="https://github.com/2cux/CodeGraph-Explorer.git"
PACKAGE="codegraph"
REQUIRED_PYTHON_MAJOR=3
REQUIRED_PYTHON_MINOR=10

# Version check code must NOT use f-strings (Python 2 compatibility for error messages)
VERSION_CHECK_CODE="import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))"

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

# Test a Python candidate — returns 0 and sets $CANDIDATE_VERSION if valid Python 3
# Usage: test_python_candidate <exe> [args...]
test_python_candidate() {
    exe="$1"; shift

    run_cmd 30 "test $exe" "$exe" "$@" -c "$VERSION_CHECK_CODE"
    rc=$?

    if [ $rc -ne 0 ]; then
        if [ "$VERBOSE" = "1" ]; then
            err_brief="${CMD_STDERR:-"exit code $rc"}"
            say "${GRAY}  [skip] $exe — $(echo "$err_brief" | head -n1)${NC}"
        fi
        return 1
    fi

    ver="$(echo "$CMD_STDOUT" | head -n1 | tr -d '[:space:]')"
    if [ -z "$ver" ]; then
        verbose "$exe — empty version output"
        return 1
    fi

    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)

    if [ -z "$major" ] || [ -z "$minor" ]; then
        verbose "$exe — unexpected version format: $ver"
        return 1
    fi

    # Export for caller
    CANDIDATE_VERSION="$ver"
    CANDIDATE_MAJOR="$major"
    CANDIDATE_MINOR="$minor"
    return 0
}

# --- step 1: find Python 3 -----------------------------------------------

# Returns: sets PYTHON_EXE, PYTHON_ARGS, PYTHON_LABEL, PYTHON_VERSION
find_python3() {
    step "[1/5] Finding Python 3..."

    # Candidate list: "exe|args|label"
    for entry in "python3||python3" "python||python"; do
        exe="${entry%%|*}"
        rest="${entry#*|}"
        args="${rest%|*}"
        label="${rest##*|}"

        if ! command -v "$exe" >/dev/null 2>&1; then
            verbose "$label — not found in PATH"
            continue
        fi

        # Test with version check (args may be empty)
        if [ -n "$args" ]; then
            test_python_candidate "$exe" "$args"
        else
            test_python_candidate "$exe"
        fi

        if [ $? -ne 0 ]; then
            continue
        fi

        # Found a Python, check its version
        if [ "$CANDIDATE_MAJOR" -lt "$REQUIRED_PYTHON_MAJOR" ]; then
            warn "  Found unsupported Python ${CANDIDATE_VERSION} at $label, trying next candidate..."
            continue
        fi

        if [ "$CANDIDATE_MAJOR" -eq "$REQUIRED_PYTHON_MAJOR" ] && [ "$CANDIDATE_MINOR" -lt "$REQUIRED_PYTHON_MINOR" ]; then
            step_fail
            die "Found Python ${CANDIDATE_VERSION} at $label, but ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+ is required.

Install from: https://www.python.org/downloads/"
        fi

        # Success — found a valid Python 3
        step_ok
        say "      ${GREEN}Using: $label${NC}"
        say "      ${GREEN}Version: ${CANDIDATE_VERSION}${NC}"

        PYTHON_EXE="$exe"
        PYTHON_ARGS="$args"
        PYTHON_LABEL="$label"
        PYTHON_VERSION="$CANDIDATE_VERSION"
        return 0
    done

    # All candidates exhausted
    step_fail
    die "No supported Python 3 installation found.

Please install Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+:
  https://www.python.org/downloads/

Then verify:
  python3 --version"
}

# --- step 2: git check ---------------------------------------------------

check_git() {
    step "[2/5] Checking Git..."

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

# --- step 3: pipx --------------------------------------------------------

# Returns "true" (to stdout) if we must use "python -m pipx" instead of bare "pipx"
ensure_pipx() {
    step "[3/5] Checking pipx..."

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

    if [ -n "$PYTHON_ARGS" ]; then
        run_cmd_or_die 180 "pip install pipx" \
            "Check your internet connection and retry. If behind a proxy, set HTTP_PROXY/HTTPS_PROXY." \
            "$PYTHON_EXE" "$PYTHON_ARGS" -m pip install --user pipx
    else
        run_cmd_or_die 180 "pip install pipx" \
            "Check your internet connection and retry. If behind a proxy, set HTTP_PROXY/HTTPS_PROXY." \
            "$PYTHON_EXE" -m pip install --user pipx
    fi

    if [ -n "$PYTHON_ARGS" ]; then
        run_cmd_or_die 30 "pipx ensurepath" \
            "Run manually: $PYTHON_LABEL -m pipx ensurepath" \
            "$PYTHON_EXE" "$PYTHON_ARGS" -m pipx ensurepath
    else
        run_cmd_or_die 30 "pipx ensurepath" \
            "Run manually: $PYTHON_LABEL -m pipx ensurepath" \
            "$PYTHON_EXE" -m pipx ensurepath
    fi

    # Refresh PATH for current session
    export PATH="$HOME/.local/bin:$PATH"

    if command -v pipx >/dev/null 2>&1; then
        info "  pipx is now available."
        step_ok
        printf "%s" "false"
        return 0
    fi

    warn "  pipx still not on PATH. Falling back to $PYTHON_LABEL -m pipx."
    step_ok
    printf "%s" "true"
    return 0
}

# --- step 4: install -----------------------------------------------------

install_codegraph() {
    use_module_pipx="$1"
    step "[4/5] Installing CodeGraph Explorer..."
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
        if [ -n "$PYTHON_ARGS" ]; then
            run_cmd_or_die 300 "pipx install CodeGraph Explorer" "$fix_msg" \
                "$PYTHON_EXE" "$PYTHON_ARGS" -m pipx install --force "$install_url"
        else
            run_cmd_or_die 300 "pipx install CodeGraph Explorer" "$fix_msg" \
                "$PYTHON_EXE" -m pipx install --force "$install_url"
        fi
    else
        run_cmd_or_die 300 "pipx install CodeGraph Explorer" "$fix_msg" \
            pipx install --force "$install_url"
    fi

    step_ok
}

# --- step 5: verify ------------------------------------------------------

verify_install() {
    step "[5/5] Verifying codegraph command..."

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

    # [1/5]
    find_python3

    # [2/5]
    check_git

    # [3/5]
    USE_MODULE_PIPX=$(ensure_pipx)

    # [4/5]
    install_codegraph "$USE_MODULE_PIPX"

    # [5/5]
    verify_install
}

main
