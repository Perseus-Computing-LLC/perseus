"""Static release checks for the VSCode extension (task-53)."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT_DIR = REPO_ROOT / "editors" / "vscode"


def _package() -> dict:
    return json.loads((EXT_DIR / "package.json").read_text())


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
    readme = (EXT_DIR / "README.md").read_text()
    release = (EXT_DIR / "RELEASE.md").read_text()
    combined = readme + "\n" + release

    assert "npm run package" in combined
    assert "tests/test_lsp.py" in combined
    assert "tests/test_vscode_extension.py" in combined
    assert "perseus.render" in combined
    assert "perseus.openCheckpoint" in combined
    assert "perseus.compactMemory" in combined
    assert "--allow-lsp-mutations" in combined
    assert "Do not publish" in combined
