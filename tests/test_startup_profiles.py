"""#792 — workflow-specific startup-memory profiles."""

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def test_scan_startup_profile_directive():
    assert (
        perseus._scan_startup_profile_name("@startup-profile daily_recap\n# ctx")
        == "daily_recap"
    )
    # A fenced example is documentation, not a directive.
    fenced = "```\n@startup-profile pre_call_brief\n```\n"
    assert perseus._scan_startup_profile_name(fenced) is None
    # Indented (non column-0) is inert too.
    assert perseus._scan_startup_profile_name("  @startup-profile daily_recap\n") is None
    assert perseus._scan_startup_profile_name("nothing here") is None


def test_resolve_startup_profile_precedence(monkeypatch):
    monkeypatch.delenv("PERSEUS_STARTUP_PROFILE", raising=False)
    # Source directive selects a known built-in.
    name, prof = perseus._resolve_startup_profile(cfg(), "@startup-profile pre_call_brief\n")
    assert name == "pre_call_brief"
    assert prof and "first_query" in prof

    # Env overrides the source directive.
    monkeypatch.setenv("PERSEUS_STARTUP_PROFILE", "daily_recap")
    name, _ = perseus._resolve_startup_profile(cfg(), "@startup-profile pre_call_brief\n")
    assert name == "daily_recap"

    # A selected-but-unknown name resolves to (name, None) — graceful fallback.
    monkeypatch.setenv("PERSEUS_STARTUP_PROFILE", "no_such_profile")
    name, prof = perseus._resolve_startup_profile(cfg(), "")
    assert name == "no_such_profile" and prof is None

    # Nothing selected → (None, None).
    monkeypatch.delenv("PERSEUS_STARTUP_PROFILE", raising=False)
    assert perseus._resolve_startup_profile(cfg(), "") == (None, None)


def test_config_startup_profiles_override(monkeypatch):
    monkeypatch.delenv("PERSEUS_STARTUP_PROFILE", raising=False)
    c = cfg()
    c.setdefault("render", {})["startup_profile"] = "custom"
    c["render"]["startup_profiles"] = {
        "custom": {"note": "n", "first_query": "q", "defer": "d"}
    }
    name, prof = perseus._resolve_startup_profile(c, "")
    assert name == "custom"
    assert prof["first_query"] == "q"


def test_pointer_block_includes_startup_lead():
    startup = ("pre_call_brief", perseus._STARTUP_PROFILES["pre_call_brief"])
    block = perseus._memory_pointer_block("default", {}, startup=startup)
    assert "Startup profile: pre_call_brief" in block
    assert "Do this first" in block
    # The header must stay first — the dedup regex anchors on it.
    assert block.startswith(perseus._MEMORY_POINTER_HEADER)
    # Without a profile, the block is unchanged (no lead).
    assert "Startup profile" not in perseus._memory_pointer_block("default", {})


def test_inject_on_demand_uses_startup_profile(monkeypatch):
    monkeypatch.setenv("PERSEUS_STARTUP_PROFILE", "ticket_triage")
    out = perseus._mneme_context_inject(cfg(), rendered="", source_text="", workspace=None)
    assert out is not None
    assert perseus._MEMORY_POINTER_HEADER in out
    assert "Startup profile: ticket_triage" in out
