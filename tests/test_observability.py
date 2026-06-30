"""#511: opt-in structured context metadata for agent observability tools."""

import copy

import perseus


def _cfg():
    return copy.deepcopy(perseus.DEFAULT_CONFIG)


def test_no_metadata_block_by_default():
    # Default render path is unchanged (deterministic, no comment block).
    out = perseus.render_source("@perseus\nhello", _cfg(), None)
    assert "perseus:meta" not in out
    assert "hello" in out


def test_metadata_block_emitted_when_enabled():
    c = _cfg()
    c["observability"]["emit_metadata"] = True
    out = perseus.render_source("@perseus\nhello world", c, None)
    assert out.startswith("<!-- perseus:meta")
    assert "context_hash: sha256:" in out
    assert "span_id: perseus-" in out
    assert "rendered_at:" in out
    assert "version:" in out
    assert "-->" in out
    # Rendered content is preserved after the comment.
    assert "hello world" in out


def test_metadata_is_an_html_comment_before_the_body():
    c = _cfg()
    c["observability"]["emit_metadata"] = True
    out = perseus.render_source("@perseus\nbody-token", c, None)
    head = out.split("body-token")[0]
    assert head.strip().startswith("<!--")
    assert "-->" in head  # comment closes before the body


def test_context_hash_is_stable_for_identical_content():
    c = _cfg()
    c["observability"]["emit_metadata"] = True
    a = perseus.render_source("@perseus\nsame", c, None)
    b = perseus.render_source("@perseus\nsame", c, None)
    ha = [ln for ln in a.splitlines() if "context_hash" in ln][0]
    hb = [ln for ln in b.splitlines() if "context_hash" in ln][0]
    assert ha == hb


def test_derive_sources_maps_directives():
    src = "@perseus\n@memory mode=search\n@read file.md\n@services\n"
    assert perseus._derive_render_sources(src) == ["files", "mimir", "services"]
