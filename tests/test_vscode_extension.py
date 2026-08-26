"""Static release checks for the VSCode extension (task-53)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT_DIR = REPO_ROOT / "editors" / "vscode"
INTEGRATION_EXT_DIR = REPO_ROOT / "integrations" / "vscode"


def _package() -> dict:
    return json.loads((EXT_DIR / "package.json").read_text(encoding="utf-8"))


def test_vscode_package_commands_match_lsp_surface():
    package = _package()
    commands = {item["command"] for item in package["contributes"]["commands"]}
    activation_events = set(package["activationEvents"])

    assert commands == {
        "perseus.render",
        "perseus.openCheckpoint",
        "perseus.compactMemory",
    }
    for command in commands:
        assert f"onCommand:{command}" in activation_events


def test_vscode_package_mutation_gate_defaults_off():
    package = _package()
    props = package["contributes"]["configuration"]["properties"]
    allow = props["perseus.allowMutations"]

    assert allow["default"] is False
    assert "--allow-lsp-mutations" in allow["description"]
    assert "compactMemory" in allow["description"]


def test_vscode_package_has_reproducible_scripts():
    scripts = _package()["scripts"]

    assert scripts["vscode:prepublish"] == "npm run compile"
    assert scripts["compile"] == "tsc -p ./"
    assert scripts["package"] == "npx @vscode/vsce package"


def test_vscode_release_docs_cover_smoke_and_packaging():
    readme = (EXT_DIR / "README.md").read_text(encoding="utf-8")
    release = (EXT_DIR / "RELEASE.md").read_text(encoding="utf-8")
    combined = readme + "\n" + release

    assert "npm run package" in combined
    assert "tests/test_lsp.py" in combined
    assert "tests/test_vscode_extension.py" in combined
    assert "perseus.render" in combined
    assert "perseus.openCheckpoint" in combined
    assert "perseus.compactMemory" in combined
    assert "--allow-lsp-mutations" in combined
    assert "Do not publish" in combined


def test_public_vscode_integration_requires_trust_and_contains_output_paths():
    package = json.loads((INTEGRATION_EXT_DIR / "package.json").read_text(encoding="utf-8"))
    props = package["contributes"]["configuration"]["properties"]
    assert props["perseus.autoRender"]["default"] is False
    assert props["perseus.executable"]["default"] == ""

    source = (INTEGRATION_EXT_DIR / "extension.js").read_text(encoding="utf-8")
    assert "workspace.isTrusted" in source
    assert "resolveWithinWorkspace" in source
    assert "sourceCandidate" not in source
    assert "execFile(" in source

    extension_path = json.dumps(str(INTEGRATION_EXT_DIR / "extension.js"))
    script = f"""
const assert = require('assert');
const Module = require('module');
const path = require('path');
const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {{
  if (request === 'vscode') return {{}};
  return originalLoad.call(this, request, parent, isMain);
}};
const resolveWithinWorkspace = require({extension_path})._test.resolveWithinWorkspace;
const root = path.resolve('/tmp/perseus workspace');
assert.strictEqual(
  resolveWithinWorkspace(root, 'nested/AGENTS.md'),
  path.join(root, 'nested/AGENTS.md')
);
assert.throws(() => resolveWithinWorkspace(root, '../escape.md'));
assert.throws(() => resolveWithinWorkspace(root, path.resolve(root, '..', 'escape.md')));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
