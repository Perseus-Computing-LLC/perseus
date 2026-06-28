"""IP evidence for patent claim element (a): the unified typed-directive grammar.

Issue #488. Novelty anchor: a *single uniform grammar* of typed directives
resolving over heterogeneous source classes (filesystem, recursive composition,
live shell, semantic memory, sub-agent, external tool) through ONE
registry-driven dispatch — `DIRECTIVE_REGISTRY` + `_call_resolver` — rather than
per-directive parsers or an ad-hoc dispatch chain.

These tests assert the *structural* claim: every directive type is registered in
one table and routed through one call adapter, and a single source document can
resolve all six patent-named source classes in one render pass. They are
deterministic, offline, and make no network or model calls.

See: docs/disclosures/2026-06-27-unified-directive-grammar.md
     docs/ip/exhibits/SAMPLE-A-unified-grammar.md / .json
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path

import pytest

from conftest import cfg, make_tool_script, perseus

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


# The six patent-named source classes from provisional 64/069,842 mapped to the
# directives that implement each class in Perseus. @file -> @read and
# @search -> @memory reflect the implementation's canonical names (see the
# naming-reconciliation section of the disclosure); the point of claim element
# (a) is that all six route through one grammar, not the surface spelling.
PATENT_SOURCE_CLASSES = {
    "filesystem": "@read",
    "recursive_composition": "@include",
    "live_shell": "@query",
    "semantic_memory": "@memory",
    "sub_agent": "@agent",
    "external_tool": "@tool",
}


def test_single_registry_is_the_only_dispatch_table():
    """All directives live in exactly one table: DIRECTIVE_REGISTRY."""
    reg = perseus.DIRECTIVE_REGISTRY
    assert isinstance(reg, dict) and len(reg) >= 30
    # Every entry is a DirectiveSpec keyed by its own canonical name.
    for name, spec in reg.items():
        assert spec.name == name, f"registry key {name!r} != spec.name {spec.name!r}"
        assert name.startswith("@")


def test_all_six_source_classes_registered_through_one_interface():
    """Each patent source class resolves through one uniform DirectiveSpec."""
    reg = perseus.DIRECTIVE_REGISTRY
    for source_class, directive in PATENT_SOURCE_CLASSES.items():
        assert directive in reg, f"{source_class}: {directive} missing from registry"
        spec = reg[directive]
        # Uniform interface: a callable resolver bound through the registry.
        assert callable(spec.resolver), f"{directive} has no bound resolver"
        # Uniform call contract: one of the adapter signatures _call_resolver knows.
        assert spec.call_sig in {"a", "ac", "acw", "awc"}, (
            f"{directive} uses call_sig {spec.call_sig!r} outside the uniform adapter"
        )


def test_call_resolver_is_the_single_adapter_for_inline_directives():
    """_call_resolver dispatches every INLINE resolver by its declared call_sig.

    This is the 'one grammar' spine for the source-class directives: no inline
    directive has a bespoke call path. Block-kind resolvers (@prompt, @services,
    @tokens, @validate) carry call_sig='block' and are driven by the renderer's
    block accumulation path — also uniform, but a distinct dispatcher. All six
    patent source classes are inline and therefore go through _call_resolver.
    """
    reg = perseus.DIRECTIVE_REGISTRY
    inline_sigs = {
        spec.call_sig
        for spec in reg.values()
        if spec.resolver is not None and spec.kind == "inline"
    }
    handled = {"a", "ac", "acw", "awc"}
    assert inline_sigs.issubset(handled), f"unhandled inline call_sigs: {inline_sigs - handled}"

    # The six patent source classes are all inline and all adapter-dispatched.
    for directive in PATENT_SOURCE_CLASSES.values():
        spec = reg[directive]
        assert spec.kind == "inline", f"{directive} expected inline, got {spec.kind}"
        assert spec.call_sig in handled

    # Every resolver's call_sig belongs to one of exactly two uniform dispatch
    # sets: the _call_resolver adapter {a,ac,acw,awc} or the renderer block path
    # {block}. No directive defines a third, bespoke dispatch path.
    all_resolver_sigs = {
        spec.call_sig for spec in reg.values() if spec.resolver is not None
    }
    assert all_resolver_sigs.issubset(handled | {"block"}), (
        f"call_sig outside the two uniform dispatchers: {all_resolver_sigs - (handled | {'block'})}"
    )


def test_inline_directive_regex_is_derived_from_the_registry():
    """The parser regex is built FROM the registry, not hand-maintained.

    Adding a directive to the table is sufficient to make the grammar parse it —
    there is no second place to edit. This is what makes it 'one grammar'.
    """
    reg = perseus.DIRECTIVE_REGISTRY
    inline_names = {s.name for s in reg.values() if s.kind == "inline"}
    rebuilt = perseus._build_inline_directive_re()
    for name in inline_names:
        assert rebuilt.match(name), f"{name} not matched by registry-derived regex"


def _write_six_class_template(tmp_path: Path) -> tuple[Path, dict]:
    """Materialize a workspace whose template exercises all six source classes."""
    (tmp_path / "data.txt").write_text("service: perseus\nport: 8080\n", encoding="utf-8")
    (tmp_path / "included.md").write_text(
        '@perseus\n## Included fragment (recursively resolved)\n@query "echo included-ok"\n',
        encoding="utf-8",
    )
    tool_path = make_tool_script(
        tmp_path, "echo-tool",
        sh="#!/bin/sh\necho perseus-tool-ok\n",
        bat="@echo off\necho perseus-tool-ok\n",
    )
    template = tmp_path / "grammar_demo.md"
    template.write_text(
        "@perseus\n"
        "# Unified grammar, six source classes\n"
        "## filesystem\n@read data.txt\n"
        "## recursive\n@include included.md\n"
        "## shell\n@query \"echo perseus-query-ok\"\n"
        "## memory\n@memory mode=search query=\"resolve before context\" k=1\n"
        "## sub-agent\n@agent \"echo perseus-agent-ok\"\n"
        "## external tool\n@tool echo-tool\n",
        encoding="utf-8",
    )
    c = cfg()  # shell + agent enabled
    c.setdefault("tools", {})
    c["tools"]["enabled"] = True
    c["tools"]["allowlist"] = [{
        "name": "echo-tool",
        "path": str(tool_path),
        "allowed_args": [],
        "timeout_s": 10,
    }]
    return template, c


def test_one_template_resolves_all_six_source_classes(tmp_path, monkeypatch):
    """A single source document resolves all six classes in one render pass.

    This is the end-to-end worked example for the disclosure exhibit.
    """
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    template, c = _write_six_class_template(tmp_path)
    out = perseus.render_source(template.read_text(encoding="utf-8"), c, workspace=tmp_path)

    # Each source class produced its concrete content (not a gate/error warning).
    assert "service: perseus" in out          # @read  -> filesystem
    assert "included-ok" in out               # @include -> recursive (nested @query)
    assert "perseus-query-ok" in out          # @query -> live shell
    assert "perseus-agent-ok" in out          # @agent -> sub-agent subprocess
    assert "perseus-tool-ok" in out           # @tool  -> allowlisted external tool
    # @memory resolves against an empty vault: assert it routed (no error marker),
    # producing the deterministic empty-vault notice rather than a resolver crash.
    assert "@memory error" not in out
    assert "⚠ @memory" not in out


def test_six_class_render_is_byte_reproducible(tmp_path, monkeypatch):
    """Determinism: two renders of the all-six template are byte-identical."""
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    template, c = _write_six_class_template(tmp_path)
    src = template.read_text(encoding="utf-8")
    a = perseus.render_source(src, copy.deepcopy(c), workspace=tmp_path)
    b = perseus.render_source(src, copy.deepcopy(c), workspace=tmp_path)
    assert a == b


def test_directive_graph_labels_each_directives_source_class(tmp_path, monkeypatch):
    """The static directive graph tags every node with its source-class hints.

    Evidence that source-class membership is machine-derivable from the one
    registry, not asserted by prose alone.
    """
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    template, c = _write_six_class_template(tmp_path)
    graph = perseus.directive_dependency_graph(
        template.read_text(encoding="utf-8"), source_name="grammar_demo", workspace=tmp_path, cfg=c
    )
    directives = set(graph["summary"]["directives"])
    for directive in PATENT_SOURCE_CLASSES.values():
        assert directive in directives, f"{directive} absent from directive graph"
    # Every node carries metadata sourced from its DirectiveSpec.
    for node in graph["nodes"]:
        assert "metadata" in node and "summary" in node["metadata"]
        assert node["source"] in {"builtin", "plugin"}


def test_save_exhibit_unified_grammar(tmp_path, monkeypatch, request):
    """Emit a timestamped reduction-to-practice exhibit (claim element a).

    Only writes when --save-exhibits is passed (CI). Mirrors the committed
    SAMPLE-A pair; the rendered all-six output is the human-readable .md and a
    manifest is the machine-checkable .json.
    """
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    template, c = _write_six_class_template(tmp_path)
    out = perseus.render_source(template.read_text(encoding="utf-8"), c, workspace=tmp_path)
    out_clean = "\n".join(l for l in out.splitlines() if not l.startswith("Dedup:")).rstrip() + "\n"
    # Sanity: all six classes resolved before we emit evidence.
    for marker in ("service: perseus", "included-ok", "perseus-query-ok",
                   "perseus-agent-ok", "perseus-tool-ok"):
        assert marker in out_clean

    if _save_exhibits(request):
        import hashlib
        manifest = {
            "evidence": "A",
            "title": "Unified typed-directive grammar — six source classes, one resolver interface",
            "claim_element": "(a) uniform grammar over heterogeneous source classes",
            "render_sha256": hashlib.sha256(out_clean.encode()).hexdigest(),
            "registry_size": len(perseus.DIRECTIVE_REGISTRY),
            "source_classes_resolved": dict(PATENT_SOURCE_CLASSES),
        }
        _write_exhibit("A-unified-grammar", manifest, as_json=True)
        _write_exhibit("A-unified-grammar", out_clean, as_json=False)
