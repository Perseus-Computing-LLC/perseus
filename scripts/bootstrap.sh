#!/usr/bin/env bash
# Perseus Context Engine bootstrap for a reviewed local checkout.
# Do not pipe a mutable remote script into a shell.
set -euo pipefail

PYTHON="${PYTHON:-python3}"
WORKSPACE="${WORKSPACE:-$(pwd)}"
PERSEUS_CTX_VERSION="${PERSEUS_CTX_VERSION:-1.0.26}"
PKG_SPEC="perseus-ctx==${PERSEUS_CTX_VERSION}"

fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
info() { printf '-> %s\n' "$*"; }

command -v "$PYTHON" >/dev/null 2>&1 || fail "$PYTHON not found"
"$PYTHON" -m pip --version >/dev/null 2>&1 || fail "pip is unavailable for $PYTHON"
[ -d "$WORKSPACE" ] || fail "workspace does not exist: $WORKSPACE"

info "Installing pinned package $PKG_SPEC"
"$PYTHON" -m pip install --upgrade "$PKG_SPEC"

cd "$WORKSPACE"
info "Initializing Perseus Context Engine in $WORKSPACE"
perseus quickstart

info "Running diagnostics"
perseus doctor

printf '\nPerseus Context Engine is configured.\n'
printf 'Review .perseus/config.yaml and .perseus/context.md before enabling shell or network directives.\n'
printf 'Perseus Vault is optional; install only from a versioned release after verifying its published digest.\n'
printf 'Release: https://github.com/Perseus-Computing-LLC/perseus-vault/releases/tag/v2.23.2\n'
