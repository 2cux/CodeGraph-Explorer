#!/usr/bin/env sh
set -euo pipefail

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
            echo "$candidate"
            return 0
        fi
    done
    die "Python not found. Install Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+ and retry."
}

# --- version check -------------------------------------------------------

check_python_version() {
    local py="$1"
    local ver
    ver=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) || {
        die "Failed to query Python version from '$py'."
    }
    local major minor
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "$major" -lt "$REQUIRED_PYTHON_MAJOR" ] || { [ "$major" -eq "$REQUIRED_PYTHON_MAJOR" ] && [ "$minor" -lt "$REQUIRED_PYTHON_MINOR" ]; }; then
        die "Python $ver detected — need ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+."
    fi
    info "Python $ver — ok"
}

# --- pipx -----------------------------------------------------------------

ensure_pipx() {
    local py="$1"
    if command -v pipx >/dev/null 2>&1; then
        info "pipx found: $(pipx --version 2>&1 | head -n1)"
        return 0
    fi
    warn "pipx not found — installing via pip."
    "$py" -m pip install --user pipx || die "Failed to install pipx."
    "$py" -m pipx ensurepath || warn "pipx ensurepath returned non-zero (PATH may need a restart)."
    # Try again after ensurepath
    export PATH="$HOME/.local/bin:$PATH"
    if command -v pipx >/dev/null 2>&1; then
        info "pipx is now available."
        return 0
    fi
    warn "pipx still not on PATH. Falling back to python -m pipx."
    PIPX_CMD="$py -m pipx"
}

# --- install --------------------------------------------------------------

install_codegraph() {
    local install_url
    if [ -n "${CODEGRAPH_VERSION:-}" ]; then
        install_url="git+${REPO}@${CODEGRAPH_VERSION}"
        info "Installing CodeGraph Explorer (${CODEGRAPH_VERSION}) …"
    else
        install_url="git+${REPO}"
        info "Installing CodeGraph Explorer (latest) …"
    fi

    if [ -n "${PIPX_CMD:-}" ]; then
        $PIPX_CMD install --force "$install_url" || die "pipx install failed."
    else
        pipx install --force "$install_url" || die "pipx install failed."
    fi
}

# --- verify ---------------------------------------------------------------

verify_install() {
    info "Verifying installation …"
    if command -v codegraph >/dev/null 2>&1; then
        codegraph --version || warn "codegraph --version returned non-zero."
        codegraph doctor --help >/dev/null 2>&1 || warn "codegraph doctor --help returned non-zero."
        say ""
        say "${GREEN}✔ CodeGraph Explorer installed successfully.${NC}"
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
    say "${YELLOW}⚠ codegraph is installed but not on your current PATH.${NC}"
    say ""
    say "  Run this to update your PATH:"
    say "    python3 -m pipx ensurepath"
    say ""
    say "  Then restart your terminal, or run:"
    say "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    say ""
    say "  After that, verify with:"
    say "    codegraph --version"
}

# --- main -----------------------------------------------------------------

main() {
    say ""
    say "CodeGraph Explorer — Installer"
    say "================================"
    say ""

    PYTHON=$(detect_python)
    check_python_version "$PYTHON"

    PIPX_CMD=""
    ensure_pipx "$PYTHON"

    install_codegraph
    verify_install
}

main
