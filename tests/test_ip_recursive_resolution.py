"""IP evidence for patent claim element: recursive / dependency-ordered resolution.

Issue #490. Novelty anchor: when a directive resolves to content that itself
contains further directives (via @include), Perseus resolves them in
dependency order, with cycle detection (path + inode) and a depth bound, and
terminates. The resolution forms an explicit directive dependency graph
(directive_dependency_graph) — a concrete data structure for the §101
"improvement to computer functioning" argument.

Security note proven here: inline RESOLVER output (e.g. @query/@agent stdout)
is inserted literally and is NOT re-parsed as directives. Recursion happens
only through @include, whose body is rendered through render_source with an
incremented include depth and an immutable ancestor chain. This is a
deliberate injection boundary, and the tests assert it.

These tests are deterministic, offline, and make no network or model calls.

See: docs/disclosures/2026-06-27-recursive-dependency-resolution.md
     docs/ip/exhibits/SAMPLE-B-recursive-resolution.md / .json
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from conftest import cfg, perseus

pytestmark = pytest.mark.skipif(perseus is None, reason="requires Python >= 3.10 build artifact")

EXHIBITS_DIR = Path(__file__).resolve().parents[1] / "docs" / "ip" / "exhibits"


def _save_exhibits(request) -> bool:
    try:
        return bool(request.config.getoption("--save-exhibits"))
    except (ValueError, AttributeError):
        return False


def _write_exhibit(name: str, content, *, as_json: bool = False) -> Path:
    EXHIBITS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = ".json" if as_json else ".md"
    path = EXHIBITS_DIR / f"{ts}-{name}{suffix}"
    text = json.dumps(content, indent=2) if as_json else content
    path.write_text(text, encoding="utf-8")
    return path


def _chain_workspace(tmp_path: Path, levels: int = 3) -> Path:
    """Build an N-level @include chain, each level carrying its own @query."""
    for n in range(levels):
        body = [f"@perseus", f"# Level {n}", f'@query "echo L{n}-shell"']
        if n < levels - 1:
            body.append(f"@include level{n + 1}.md")
        name = "root.md" if n == 0 else f"level{n}.md"
        (tmp_path / name).write_text("\n".join(body) + "\n", encoding="utf-8")
    return tmp_path / "root.md"


def test_multilevel_include_resolves_in_dependency_order(tmp_path, monkeypatch):
    """A 3-level include chain resolves every level's directive, in order."""
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    root = _chain_workspace(tmp_path, levels=3)
    out = perseus.render_source(root.read_text(encoding="utf-8"), cfg(), workspace=tmp_path)
    # All three levels resolved.
    for n in range(3):
        assert f"L{n}-shell" in out, f"level {n} directive did not resolve"
    # Dependency order: L0 appears before L1 before L2 (parent renders before
    # the child it includes).
    assert out.index("L0-shell") < out.index("L1-shell") < out.index("L2-shell")


def test_include_cycle_is_detected_and_terminates(tmp_path, monkeypatch):
    """A -> B -> A include cycle is caught (path-based) and does not recurse forever."""
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    (tmp_path / "a.md").write_text("@perseus\n# A\n@include b.md\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("@perseus\n# B\n@include a.md\n", encoding="utf-8")
    out = perseus.render_source((tmp_path / "a.md").read_text(encoding="utf-8"), cfg(), workspace=tmp_path)
    assert "circular dependency detected" in out
    # Termination: the render returned (no RecursionError) and the chain is shown.
    assert "→" in out or "->" in out


def test_include_depth_is_bounded(tmp_path, monkeypatch):
    """A chain deeper than max_include_depth stops with a clear warning."""
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    c = cfg()
    c["render"]["max_include_depth"] = 3
    # 6-level linear chain, well past the depth cap.
    root = _chain_workspace(tmp_path, levels=6)
    out = perseus.render_source(root.read_text(encoding="utf-8"), c, workspace=tmp_path)
    assert "max depth" in out and "Stopping recursion" in out
    # Levels within the cap still resolved.
    assert "L0-shell" in out and "L1-shell" in out


def test_inline_resolver_output_is_not_reparsed_as_directives(tmp_path, monkeypatch):
    """SECURITY/BOUNDARY: @query stdout containing an @directive is NOT resolved.

    Recursion happens only through @include. A resolver that emits the literal
    text '@read /etc/passwd' must NOT cause a file read — the text is inserted
    verbatim. This is the injection boundary that makes recursive resolution
    safe to claim.
    """
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-SHOULD-NOT-APPEAR\n", encoding="utf-8")
    # @query prints a string that LOOKS like a directive referencing the secret.
    src = (
        "@perseus\n"
        f'@query "echo @read {secret}"\n'
    )
    out = perseus.render_source(src, cfg(), workspace=tmp_path)
    # The literal directive-looking text is present...
    assert "@read" in out
    # ...but it was NOT resolved: the secret file content must not leak.
    assert "TOP-SECRET-SHOULD-NOT-APPEAR" not in out


def test_directive_dependency_graph_is_an_explicit_data_structure(tmp_path, monkeypatch):
    """The resolution order is exposed as a typed graph (nodes + ordered edges).

    This is the concrete data structure cited for the §101 argument.
    """
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    root = _chain_workspace(tmp_path, levels=3)
    graph = perseus.directive_dependency_graph(
        root.read_text(encoding="utf-8"), source_name="root", workspace=tmp_path, cfg=cfg()
    )
    assert set(graph) >= {"nodes", "edges", "summary"}
    # Root level has two directives (@query, @include) with one ordering edge.
    assert graph["summary"]["node_count"] == 2
    assert graph["summary"]["edge_count"] == 1
    edge = graph["edges"][0]
    assert edge["type"] == "order"
    assert edge["from"] == graph["nodes"][0]["id"]
    assert edge["to"] == graph["nodes"][1]["id"]
    # Each node carries its resource hints (the dependency targets).
    inc = [n for n in graph["nodes"] if n["directive"] == "@include"][0]
    assert inc["metadata"]["reads_files"] is True


def test_multilevel_resolution_is_byte_reproducible(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    root = _chain_workspace(tmp_path, levels=3)
    src = root.read_text(encoding="utf-8")
    a = perseus.render_source(src, cfg(), workspace=tmp_path)
    b = perseus.render_source(src, cfg(), workspace=tmp_path)
    assert a == b


def test_save_exhibit_recursive_resolution(tmp_path, monkeypatch, request):
    """Emit a timestamped exhibit for recursive, dependency-ordered resolution.

    Only writes when --save-exhibits is passed (CI). Renders the 3-level chain
    and captures the dependency graph + a cycle-detection demonstration.
    """
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    root = _chain_workspace(tmp_path, levels=3)
    src = root.read_text(encoding="utf-8")
    out = perseus.render_source(src, cfg(), workspace=tmp_path)
    out_clean = "\n".join(l for l in out.splitlines() if not l.startswith("Dedup:")).rstrip() + "\n"
    for n in range(3):
        assert f"L{n}-shell" in out_clean

    # Cycle demo
    (tmp_path / "cycA.md").write_text("@perseus\n# A\n@include cycB.md\n", encoding="utf-8")
    (tmp_path / "cycB.md").write_text("@perseus\n# B\n@include cycA.md\n", encoding="utf-8")
    cyc = perseus.render_source((tmp_path / "cycA.md").read_text(encoding="utf-8"), cfg(), workspace=tmp_path)
    cyc_line = next((l for l in cyc.splitlines() if "circular" in l.lower()), "")
    assert cyc_line

    if _save_exhibits(request):
        import hashlib
        graph = perseus.directive_dependency_graph(src, source_name="root", workspace=tmp_path, cfg=cfg())
        manifest = {
            "evidence": "B",
            "title": "Recursive, dependency-ordered directive resolution",
            "claim_element": "recursive resolution + cycle detection + dependency graph",
            "render_sha256": hashlib.sha256(out_clean.encode()).hexdigest(),
            "levels_resolved": 3,
            "dependency_order": [f"L{n}-shell" for n in range(3)],
            "cycle_detection_demo": cyc_line.strip(),
            "directive_dependency_graph": graph,
        }
        _write_exhibit("B-recursive-resolution", manifest, as_json=True)
        _write_exhibit("B-recursive-resolution", out_clean, as_json=False)
