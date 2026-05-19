#!/usr/bin/env bash
# Perseus installer bootstrap (task-48 / Phase 18A).
#
# Installs the single-file `perseus.py` runtime as `perseus` on PATH.
# Verifies Python >= 3.10 and the `pyyaml` import. Does NOT split perseus.py,
# does NOT introduce a dependency manager, does NOT touch system Python.
#
# Usage:
#   ./scripts/install.sh                  # install latest from current repo to ~/.local/bin
#   ./scripts/install.sh --prefix /opt    # install to /opt/bin
#   ./scripts/install.sh --uninstall      # remove installed shim and runtime
#   ./scripts/install.sh --version        # print the version that would be installed
#
# Idempotent: re-running upgrades in place.
set -euo pipefail

PERSEUS_MIN_PY=10  # minor version (3.10+)
PREFIX="${PERSEUS_PREFIX:-$HOME/.local}"
ACTION="install"

die() { printf 'perseus install: %s\n' "$*" >&2; exit 1; }
note() { printf 'perseus install: %s\n' "$*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="${2:?--prefix requires a path}"; shift 2 ;;
        --prefix=*) PREFIX="${1#--prefix=}"; shift ;;
        --uninstall) ACTION="uninstall"; shift ;;
        --version) ACTION="version"; shift ;;
        --help|-h)
            sed -n '2,16p' "$0"; exit 0 ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

# Resolve repo root (parent of scripts/).
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
SRC="$REPO_ROOT/perseus.py"
[ -f "$SRC" ] || die "perseus.py not found at $SRC"

BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/share/perseus"
INSTALLED_RUNTIME="$LIB_DIR/perseus.py"
INSTALLED_SHIM="$BIN_DIR/perseus"

if [ "$ACTION" = "version" ]; then
    python3 "$SRC" --version
    exit 0
fi

if [ "$ACTION" = "uninstall" ]; then
    removed=0
    for p in "$INSTALLED_SHIM" "$INSTALLED_RUNTIME"; do
        if [ -e "$p" ]; then rm -f "$p" && note "removed $p" && removed=1; fi
    done
    rmdir "$LIB_DIR" 2>/dev/null || true
    [ $removed -eq 1 ] || note "nothing to uninstall under $PREFIX"
    exit 0
fi

# --- preflight checks ----------------------------------------------------------
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH (Perseus needs Python 3.${PERSEUS_MIN_PY}+)"

PY_OK=$(python3 - <<EOF
import sys
sys.exit(0 if sys.version_info >= (3, ${PERSEUS_MIN_PY}) else 1)
EOF
) && rc=$? || rc=$?
if [ ${rc:-1} -ne 0 ]; then
    pyv=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
    die "Python 3.${PERSEUS_MIN_PY}+ required (found $pyv)"
fi

if ! python3 -c 'import yaml' >/dev/null 2>&1; then
    die "missing dependency: pyyaml. Install with: python3 -m pip install --user pyyaml"
fi

# --- install -------------------------------------------------------------------
mkdir -p "$BIN_DIR" "$LIB_DIR"
install -m 0644 "$SRC" "$INSTALLED_RUNTIME"

cat > "$INSTALLED_SHIM" <<EOF
#!/usr/bin/env bash
# Perseus shim — installed by scripts/install.sh.
exec python3 "$INSTALLED_RUNTIME" "\$@"
EOF
chmod +x "$INSTALLED_SHIM"

# --- verify --------------------------------------------------------------------
if ! out=$("$INSTALLED_SHIM" --version 2>&1); then
    die "install verification failed: $out"
fi
note "installed: $INSTALLED_SHIM"
note "runtime:   $INSTALLED_RUNTIME"
note "verified:  $out"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) note "note: $BIN_DIR is not on PATH — add it to your shell rc to use 'perseus'" ;;
esac
