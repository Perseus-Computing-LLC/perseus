"""#716: gated @query/@agent/@services must not emit a multi-line operator
warning block into the rendered output document.

When the directive is enabled in config but PERSEUS_ALLOW_DANGEROUS=1 is
not set:
  1. a directive with fallback="..." renders the fallback value;
  2. a directive without a fallback renders a single-line HTML comment
     (<!-- perseus: @query gated (PERSEUS_ALLOW_DANGEROUS not set) -->);
  3. the "export PERSEUS_ALLOW_DANGEROUS=1" operator guidance is routed to
     stderr, once per top-level render (not once per gated block).

Note: tests/conftest.py sets PERSEUS_ALLOW_DANGEROUS=1 autouse; the gated
tests below delete it. conftest's autouse _clear_session_cache calls
_clear_render_path_memos(), which also resets the once-per-render stderr
flag, so each test observes its own first warning.
"""

import copy

import perseus

GUIDANCE = "export PERSEUS_ALLOW_DANGEROUS=1"


def _cfg():
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["render"]["allow_query_shell"] = True
    c["render"]["allow_agent_shell"] = True
    c["render"]["allow_services_command"] = True
    return c


# ── behavior 1: fallback= wins over any warning ──────────────────────────────

def test_gated_query_renders_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    out = perseus.resolve_query('"echo LEAK" fallback="(query gated off)"', _cfg(), tmp_path)
    assert out == "(query gated off)"
    assert "LEAK" not in out


def test_gated_agent_renders_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    out = perseus.resolve_agent('"echo LEAK" fallback="(agent gated off)"', _cfg(), tmp_path)
    assert out == "(agent gated off)"


def test_gated_query_fallback_still_audits(tmp_path, monkeypatch):
    """The fallback path must not silence the policy_denied audit event."""
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    events = []
    monkeypatch.setattr(
        perseus, "audit_event",
        lambda cfg, event, **kw: events.append((event, kw)),
    )
    perseus.resolve_query('"echo x" fallback="(off)"', _cfg(), tmp_path)
    assert events and events[0][0] == "policy_denied"
    assert events[0][1].get("reason") == "PERSEUS_ALLOW_DANGEROUS not set"


# ── behavior 2: no fallback → single-line HTML comment ───────────────────────

def test_gated_query_without_fallback_is_single_comment(tmp_path, monkeypatch):
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    out = perseus.resolve_query('"echo LEAK"', _cfg(), tmp_path)
    assert out == "<!-- perseus: @query gated (PERSEUS_ALLOW_DANGEROUS not set) -->"
    assert "\n" not in out
    assert GUIDANCE not in out


def test_gated_agent_without_fallback_is_single_comment(tmp_path, monkeypatch):
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    out = perseus.resolve_agent('"echo LEAK"', _cfg(), tmp_path)
    assert out == "<!-- perseus: @agent gated (PERSEUS_ALLOW_DANGEROUS not set) -->"
    assert "\n" not in out


def test_gated_services_command_row_is_terse(monkeypatch, capsys):
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    _, row = perseus._check_one_service(
        {"name": "svc", "command": "echo up"}, 0, 3.0, _cfg())
    assert row == "| svc | ⚠ gated (PERSEUS_ALLOW_DANGEROUS not set) | — |"
    assert GUIDANCE not in row
    assert GUIDANCE in capsys.readouterr().err


# ── behavior 3: operator guidance → stderr, once per render ──────────────────

def test_gated_render_emits_guidance_once_and_keeps_doc_clean(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    lines = [
        '@query "echo ONE"',
        "some prose",
        '@query "echo TWO" fallback="(two gated)"',
    ]
    out = perseus._render_lines(lines, _cfg(), workspace=tmp_path, no_cache=True)

    # Document stays clean: no multi-line warning block, no fix instructions.
    assert GUIDANCE not in out
    assert "defense-in-depth" not in out
    assert "acknowledge the risk" not in out
    assert "<!-- perseus: @query gated (PERSEUS_ALLOW_DANGEROUS not set) -->" in out
    assert "(two gated)" in out
    assert "ONE" not in out and "TWO" not in out

    # Guidance hit stderr exactly once despite two gated blocks.
    err = capsys.readouterr().err
    assert err.count(GUIDANCE) == 1


def test_gate_guidance_reemitted_on_next_render(tmp_path, monkeypatch, capsys):
    """Once per RENDER, not once per process: a second top-level render
    warns again (the renderer clears the flag at render entry)."""
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    c = _cfg()
    perseus._render_lines(['@query "echo A"'], c, workspace=tmp_path, no_cache=True)
    assert capsys.readouterr().err.count(GUIDANCE) == 1
    perseus._render_lines(['@query "echo A"'], c, workspace=tmp_path, no_cache=True)
    assert capsys.readouterr().err.count(GUIDANCE) == 1


def test_open_gates_still_execute(tmp_path, monkeypatch):
    """Sanity: with both gates open the directive actually runs (no comment)."""
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    out = perseus.resolve_query('"echo GATES-OPEN"', _cfg(), tmp_path)
    assert "GATES-OPEN" in out
    assert "gated" not in out
