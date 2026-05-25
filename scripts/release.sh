#!/usr/bin/env bash
# Perseus release artifact builder (task-49 / Phase 18B).
#
# Produces deterministic distribution artifacts for the current version:
#   dist/perseus-<version>.tar.gz   — runtime + installer + docs
#   dist/perseus-<version>.zip      — same content for zip-only environments
#   dist/SHA256SUMS                 — checksums for both artifacts + runtime
#
# Does NOT publish anywhere; does NOT touch the network. Just builds locally.
#
# Usage:
#   ./scripts/release.sh           # build artifacts for the version in VERSION
#   ./scripts/release.sh --verify  # only verify version coherence; build nothing
#   ./scripts/release.sh --check   # verify a previously built dist/ matches the source
#   ./scripts/release.sh --clean   # rm -rf dist/
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
DIST_DIR="$REPO_ROOT/dist"

die() { printf 'release: %s\n' "$*" >&2; exit 1; }
note() { printf 'release: %s\n' "$*"; }

ACTION="build"
while [ $# -gt 0 ]; do
    case "$1" in
        --verify) ACTION="verify"; shift ;;
        --check) ACTION="check"; shift ;;
        --clean) ACTION="clean"; shift ;;
        --help|-h) sed -n '2,16p' "$0"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

if [ "$ACTION" = "clean" ]; then
    rm -rf "$DIST_DIR"
    note "removed $DIST_DIR"
    exit 0
fi

# --- version coherence ---------------------------------------------------------
VERSION=$(tr -d '[:space:]' < "$REPO_ROOT/VERSION")
[ -n "$VERSION" ] || die "VERSION file is empty"

# perseus.py
PY_VERSION=$(python3 -c 'import ast, pathlib, sys; tree = ast.parse(pathlib.Path(sys.argv[1]).read_text()); print(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name) and t.id == "_PERSEUS_VERSION"))' "$REPO_ROOT/perseus.py")
[ -n "$PY_VERSION" ] || die "could not parse _PERSEUS_VERSION from perseus.py"
[ "$PY_VERSION" = "$VERSION" ] || die "VERSION ($VERSION) != _PERSEUS_VERSION ($PY_VERSION) in perseus.py"

# perseus --version (matches AC #1)
CLI_VERSION=$(python3 "$REPO_ROOT/perseus.py" --version | awk '{print $NF}' | sed 's/^v//')
[ "$CLI_VERSION" = "$VERSION" ] || die "'perseus --version' ($CLI_VERSION) != VERSION ($VERSION)"

# CHANGELOG must reference the version (unless it's a -dev tag).
if ! grep -q "## \[$VERSION\]" "$REPO_ROOT/CHANGELOG.md"; then
    die "CHANGELOG.md has no '## [$VERSION]' section"
fi

note "version coherence ok: $VERSION"

if [ "$ACTION" = "verify" ]; then exit 0; fi

# --- check mode: just verify existing dist/ matches the runtime ----------------
if [ "$ACTION" = "check" ]; then
    [ -d "$DIST_DIR" ] || die "no dist/ directory to check"
    (cd "$DIST_DIR" && sha256sum -c SHA256SUMS)
    note "dist/ checksums verified"
    exit 0
fi

# --- build ---------------------------------------------------------------------
# Regenerate the single-file artifact from src/ before packaging.
note "building perseus.py from src/"
python3 "$REPO_ROOT/scripts/build.py" || { note "build.py failed — aborting release"; exit 1; }

mkdir -p "$DIST_DIR"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

PKG="perseus-$VERSION"
PKG_DIR="$STAGE/$PKG"
mkdir -p "$PKG_DIR/scripts"

cp "$REPO_ROOT/perseus.py" "$PKG_DIR/"
cp "$REPO_ROOT/VERSION" "$PKG_DIR/"
cp "$REPO_ROOT/CHANGELOG.md" "$PKG_DIR/"
cp "$REPO_ROOT/INSTALL.md" "$PKG_DIR/"
cp "$REPO_ROOT/README.md" "$PKG_DIR/" 2>/dev/null || true
cp "$REPO_ROOT/scripts/install.sh" "$PKG_DIR/scripts/"
chmod +x "$PKG_DIR/scripts/install.sh"

# Deterministic: zero mtimes, sorted file order.
find "$PKG_DIR" -exec touch -d "1970-01-01T00:00:00Z" {} +

TAR="$DIST_DIR/$PKG.tar.gz"
TAR_RAW="$DIST_DIR/$PKG.tar"
ZIP="$DIST_DIR/$PKG.zip"

# Reproducible tar: prefer GNU tar's metadata controls, fall back to a sorted
# file list for BSD tar on macOS.
rm -f "$TAR_RAW" "$TAR"
if tar --version 2>/dev/null | grep -qi 'gnu tar'; then
    (cd "$STAGE" && tar \
        --sort=name \
        --owner=0 --group=0 --numeric-owner \
        --mtime='1970-01-01 00:00:00 UTC' \
        -cf "$TAR_RAW" "$PKG")
else
    (cd "$STAGE" && find "$PKG" -print | LC_ALL=C sort | tar -cf "$TAR_RAW" -T -)
fi
gzip -n -c "$TAR_RAW" > "$TAR"
rm -f "$TAR_RAW"

# Reproducible zip: sort, strip extras. Best-effort — skip if `zip` is missing.
if command -v zip >/dev/null 2>&1; then
    (cd "$STAGE" && find "$PKG" -print | LC_ALL=C sort | zip -X -q "$ZIP" -@) >/dev/null
    HAVE_ZIP=1
else
    note "skipping .zip artifact: 'zip' not installed (install zip to enable)"
    HAVE_ZIP=0
    rm -f "$ZIP"
fi

# Checksums for the artifacts AND the standalone runtime.
cp "$REPO_ROOT/perseus.py" "$DIST_DIR/perseus.py"
if [ "$HAVE_ZIP" = "1" ]; then
    (cd "$DIST_DIR" && sha256sum "$PKG.tar.gz" "$PKG.zip" perseus.py > SHA256SUMS)
else
    (cd "$DIST_DIR" && sha256sum "$PKG.tar.gz" perseus.py > SHA256SUMS)
fi

note "built $TAR"
[ "$HAVE_ZIP" = "1" ] && note "built $ZIP"
note "built $DIST_DIR/SHA256SUMS"
note "artifacts:"
if [ "$HAVE_ZIP" = "1" ]; then
    (cd "$DIST_DIR" && ls -lh "$PKG.tar.gz" "$PKG.zip" perseus.py SHA256SUMS) | sed 's/^/  /'
else
    (cd "$DIST_DIR" && ls -lh "$PKG.tar.gz" perseus.py SHA256SUMS) | sed 's/^/  /'
fi
