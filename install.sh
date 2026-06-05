#!/usr/bin/env sh
set -eu

# CodeGraph Explorer — one-line installer (macOS / Linux)
# curl -fsSL https://raw.githubusercontent.com/2cux/CodeGraph-Explorer/main/install.sh | sh
#
# Optional version pin:
#   CODEGRAPH_VERSION=v1.0.0-rc.1 curl -fsSL ... | sh

REPO="https://github.com/2cux/CodeGraph-Explorer.git"
PACKAGE="codegraph"
REQUIRED_PYTHON_MAJOR=3
REQUIRED_PYTHON_MINOR=10

# --- helpers -------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

say()  { printf "%b\n" "$*"; }
info() { say "${GREEN}[info]${NC} $*"; }
warn() { say "${YELLOW}[warn]${NC} $*" >&2; }
err()  { say "${RED}[error]${NC} $*" >&2; }
die()  { err "$@"; exit 1; }

# --- python detection ----------------------------------------------------

detect_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            info "Using $candidate ($(command -v "$candidate"))"
            printf "%s" "$candidate"
            return 0
        fi
    done
    die "Python not found. Install Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+ and retry."
}

# --- version check -------------------------------------------------------

check_python_version() {
    py="$1"
    ver="$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)" || {
        die "Failed to query Python version from '$py'."
    }
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "$major" -lt "$REQUIRED_PYTHON_MAJOR" ] || { [ "$major" -eq "$REQUIRED_PYTHON_MAJOR" ] && [ "$minor" -lt "$REQUIRED_PYTHON_MINOR" ]; }; then
        die "Python $ver detected — need ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+."
    fi
    info "Python $ver — ok"
}

# --- pipx -----------------------------------------------------------------

# Returns "true" if we must use "python -m pipx" instead of bare "pipx"
ensure_pipx() {
    py="$1"

    if command -v pipx >/dev/null 2>&1; then
        pipx_ver=$(pipx --version 2>&1 | head -n1)
        info "pipx found: $pipx_ver"
        printf "%s" "false"
        return 0
    fi

    warn "pipx not found — installing via pip."
    "$py" -m pip install --user pipx || die "Failed to install pipx."
    "$py" -m pipx ensurepath || warn "pipx ensurepath returned non-zero (PATH may need a restart)."

    # Refresh PATH for current session
    export PATH="$HOME/.local/bin:$PATH"

    if command -v pipx >/dev/null 2>&1; then
        info "pipx is now available."
        printf "%s" "false"
        return 0
    fi

    warn "pipx still not on PATH. Falling back to python -m pipx."
    printf "%s" "true"
    return 0
}

# --- install --------------------------------------------------------------

install_codegraph() {
    py="$1"
    use_module_pipx="$2"

    if [ -n "${CODEGRAPH_VERSION:-}" ]; then
        install_url="git+${REPO}@${CODEGRAPH_VERSION}"
        info "Installing CodeGraph Explorer (${CODEGRAPH_VERSION}) ..."
    else
        install_url="git+${REPO}"
        info "Installing CodeGraph Explorer (latest) ..."
    fi

    if [ "$use_module_pipx" = "true" ]; then
        "$py" -m pipx install --force "$install_url" || die "pipx install failed."
    else
        pipx install --force "$install_url" || die "pipx install failed."
    fi
}

# --- verify ---------------------------------------------------------------

verify_install() {
    info "Verifying installation ..."
    if command -v codegraph >/dev/null 2>&1; then
        codegraph --help || warn "codegraph --help returned non-zero."
        codegraph doctor --help >/dev/null 2>&1 || warn "codegraph doctor --help returned non-zero."
        say ""
        say "${GREEN}CodeGraph Explorer installed successfully.${NC}"
        say ""
        say "  Next steps:"
        say "    cd your-project"
        say "    codegraph init"
        say "    codegraph configure all"
        say "    codegraph doctor"
        return 0
    fi

    # Not on PATH — give clear guidance
    say ""
    say "${YELLOW}codegraph is installed but not on your current PATH.${NC}"
    say ""
    say "  Refresh PATH in this terminal:"
    say '    export PATH="$HOME/.local/bin:$PATH"'
    say ""
    say "  Then verify with:"
    say "    codegraph --help"
    say ""
    say "  If it still isn't found, run:"
    say "    python3 -m pipx ensurepath"
    say "    # then restart your terminal"
    return 0
}

# --- main -----------------------------------------------------------------

main() {
    say ""
    say "CodeGraph Explorer — Installer"
    say "================================"
    say ""

    PYTHON=$(detect_python)
    check_python_version "$PYTHON"

    USE_MODULE_PIPX=$(ensure_pipx "$PYTHON")

    install_codegraph "$PYTHON" "$USE_MODULE_PIPX"
    verify_install
}

main
