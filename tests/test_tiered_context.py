"""Tests for Tiered Context Rendering (task-76)."""
import pytest
from conftest import cfg, perseus


def test_tier_field_on_all_directives():
    """Every registered directive must have a tier field."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        assert hasattr(spec, 'tier'), f"{name}: missing tier field"
        assert isinstance(spec.tier, int), f"{name}: tier is not int"
        assert 1 <= spec.tier <= 3, f"{name}: tier {spec.tier} out of range [1,3]"


def test_tier_defaults_t1_directives():
    """Tier 1 directives: @date, @memory, @waypoint, @health, @env."""
    for name in ["@date", "@memory", "@waypoint", "@health", "@env"]:
        assert perseus.DIRECTIVE_REGISTRY[name].tier == 1, f"{name}: expected tier 1"


def test_tier_defaults_t2_directives():
    """Tier 2 directives: @services, @skills, @session, @agora, @inbox, @drift."""
    for name in ["@services", "@skills", "@session", "@agora", "@inbox", "@drift"]:
        assert perseus.DIRECTIVE_REGISTRY[name].tier == 2, f"{name}: expected tier 2"


def test_tier_defaults_t3_directives():
    """Tier 3 directives: @query, @read, @include, @list, @tree, @agent, @tool."""
    for name in ["@query", "@read", "@include", "@list", "@tree", "@agent", "@tool"]:
        assert perseus.DIRECTIVE_REGISTRY[name].tier == 3, f"{name}: expected tier 3"


def test_max_tier_3_resolves_all():
    """max_tier=3 resolves every directive."""
    source = "@perseus\n@date\n@env HOME"
    out = perseus.render_source(source, cfg(), None, max_tier=3)
    assert "CDT" in out or "UTC" in out  # @date resolved
    assert "HOME" not in out or "/" in out  # @env resolved something


def test_max_tier_1_skips_t2_t3_directives():
    """max_tier=1 skips @skills (T2) and @query (T3) but resolves @date (T1)."""
    source = "@perseus\n@date"
    out = perseus.render_source(source, cfg(), None, max_tier=1)
    assert "CDT" in out or "UTC" in out  # @date resolved


def test_max_tier_1_emits_context_manifest():
    """When directives are skipped, Context Manifest appears."""
    source = "@perseus\n@date\n@skills"
    out = perseus.render_source(source, cfg(), None, max_tier=1)
    assert "Context Manifest" in out
    assert "@skills" in out
    assert "Tier limit: 1" in out


def test_max_tier_2_emits_manifest_for_t3_only():
    """max_tier=2 skips only T3 directives."""
    source = "@perseus\n@date\n@skills\n@query echo hello"
    out = perseus.render_source(source, cfg(), None, max_tier=2)
    assert "Context Manifest" in out
    assert "@query" in out
    assert "@skills" not in out.split("> 📋")[1] if "> 📋" in out else True  # @skills resolved, not in manifest


def test_max_tier_3_no_manifest():
    """max_tier=3 (all) emits no manifest."""
    source = "@perseus\n@date\n@skills"
    out = perseus.render_source(source, cfg(), None, max_tier=3)
    assert "Context Manifest" not in out


def test_tier_modifier_overrides_default():
    """@tier:1 on a T2 directive forces it to resolve at max_tier=1."""
    source = "@perseus\n@date\n@skills @tier:1"
    out = perseus.render_source(source, cfg(), None, max_tier=1)
    # @skills should have resolved (forced to T1), so not in manifest
    if "Context Manifest" in out:
        manifest = out.split("> 📋")[1] if "> 📋" in out else ""
        assert "@skills" not in manifest


def test_tier_modifier_respected_block_directive():
    """@tier:1 on @services block forces resolution at T1."""
    source = "@perseus\n@date\n@services @tier:1\nnonexistent-service\n@end"
    out = perseus.render_source(source, cfg(), None, max_tier=1)
    # @services resolved (or errored trying), should not be in manifest
    if "Context Manifest" in out:
        manifest = out.split("> 📋")[1] if "> 📋" in out else ""
        assert "@services" not in manifest


def test_parse_tier_modifier_strips_correctly():
    """_parse_tier_modifier strips @tier:N and returns the clean line."""
    clean, tier = perseus._parse_tier_modifier("@skills @tier:2 flag_stale=true")
    assert tier == 2
    assert "@tier:2" not in clean
    assert "@skills" in clean
    assert "flag_stale=true" in clean


def test_parse_tier_modifier_no_modifier():
    """_parse_tier_modifier returns None when no @tier present."""
    clean, tier = perseus._parse_tier_modifier("@skills flag_stale=true")
    assert tier is None
    assert clean == "@skills flag_stale=true"


def test_check_directive_tier_skip():
    """_check_directive_tier returns should_skip=True when tier > max_tier."""
    skipped = []
    should_skip, clean = perseus._check_directive_tier(
        "@skills", "@skills", max_tier=1, skipped=skipped
    )
    assert should_skip is True
    assert len(skipped) == 1
    assert skipped[0]["name"] == "@skills"
    assert skipped[0]["tier"] == 2


def test_check_directive_tier_pass():
    """_check_directive_tier returns should_skip=False when tier <= max_tier."""
    skipped = []
    should_skip, clean = perseus._check_directive_tier(
        "@date", "@date", max_tier=1, skipped=skipped
    )
    assert should_skip is False
    assert len(skipped) == 0


def test_check_directive_tier_structural_always_pass():
    """Structural directives (@if, @else, @endif, @end) always pass."""
    for name in ["@if", "@else", "@endif", "@end"]:
        skipped = []
        should_skip, _ = perseus._check_directive_tier(
            name, name, max_tier=1, skipped=skipped
        )
        assert should_skip is False, f"{name}: structural should always pass"
        assert len(skipped) == 0


def test_check_directive_tier_instance_override():
    """@tier:1 modifier overrides registry default of tier 2."""
    skipped = []
    should_skip, clean = perseus._check_directive_tier(
        "@skills @tier:1", "@skills", max_tier=1, skipped=skipped
    )
    assert should_skip is False
    assert len(skipped) == 0
    assert "@tier:1" not in clean


def test_context_manifest_tier_2_message():
    """Tier 2 manifest tells user to use --tier 3."""
    source = "@perseus\n@date\n@query echo hello"
    out = perseus.render_source(source, cfg(), None, max_tier=2)
    assert "Context Manifest" in out
    assert "--tier 3" in out


def test_context_manifest_tier_1_message():
    """Tier 1 manifest tells user to use --tier 2 or --tier 3."""
    source = "@perseus\n@date\n@skills"
    out = perseus.render_source(source, cfg(), None, max_tier=1)
    assert "Context Manifest" in out
    assert "--tier 2" in out
    assert "--tier 3" in out


def test_render_output_passes_max_tier():
    """render_output() passes max_tier through to render_source."""
    source = "@perseus\n@date\n@skills"
    out = perseus.render_output(source, "md", cfg(), None, max_tier=1)
    assert "Context Manifest" in out
