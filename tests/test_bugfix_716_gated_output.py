"""#716 follow-up: the PERSEUS_ALLOW_DANGEROUS gate guidance is scoped to
the RENDER, not the process.

#719 routed the gate guidance to stderr via _warn_dangerous_gate(), but the
once-only set was never cleared — a long-lived process (perseus serve, MCP)
warned only on the first render ever and stayed silent for every later
render. The renderer now resets _DANGEROUS_GATE_WARNED at top-level render
entry (_clear_render_path_memos), so each render's log carries the guidance
exactly once (still not once per gated block).

Also covers the end-to-end #716 contract through _render_lines: a document
with multiple gated blocks renders fallback= text / one-line comments only —
no operator guidance in the artifact.

Note: tests/conftest.py sets PERSEUS_ALLOW_DANGEROUS=1 autouse; gated tests
delete it. conftest's autouse _clear_session_cache calls
_clear_render_path_memos(), which now also resets the warn-once set, so each
test observes its own first warning.
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


def test_gated_render_emits_guidance_once_and_keeps_doc_clean(tmp_path, monkeypatch, capsys):
    """End-to-end through _render_lines: two gated @query blocks → clean
    document (fallback + one-line comment), guidance on stderr exactly once."""
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
    assert "<!-- perseus: @query gated (PERSEUS_ALLOW_DANGEROUS=1 is not set) -->" in out
    assert "(two gated)" in out
    assert "ONE" not in out and "TWO" not in out

    # Guidance hit stderr exactly once despite two gated blocks.
    err = capsys.readouterr().err
    assert err.count(GUIDANCE) == 1


def test_gate_guidance_reemitted_on_next_render(tmp_path, monkeypatch, capsys):
    """Once per RENDER, not once per process: a second top-level render warns
    again (the renderer clears _DANGEROUS_GATE_WARNED at render entry), so
    long-lived serve/MCP processes keep the guidance in every render's log."""
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    c = _cfg()
    perseus._render_lines(['@query "echo A"'], c, workspace=tmp_path, no_cache=True)
    assert capsys.readouterr().err.count(GUIDANCE) == 1
    perseus._render_lines(['@query "echo A"'], c, workspace=tmp_path, no_cache=True)
    assert capsys.readouterr().err.count(GUIDANCE) == 1


def test_render_entry_clears_warned_set():
    """_clear_render_path_memos (the top-level render reset point) owns the
    warn-once set's lifecycle."""
    perseus._DANGEROUS_GATE_WARNED.add("@query")
    perseus._clear_render_path_memos()
    assert not perseus._DANGEROUS_GATE_WARNED


def test_open_gates_still_execute(tmp_path, monkeypatch):
    """Sanity: with both gates open the directive actually runs (no comment)."""
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    out = perseus.resolve_query('"echo GATES-OPEN"', _cfg(), tmp_path)
    assert "GATES-OPEN" in out
    assert "gated" not in out
