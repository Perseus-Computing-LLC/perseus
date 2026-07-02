"""#616: @query shell-exec must enforce the PERSEUS_ALLOW_DANGEROUS
defense-in-depth env gate its docs and sibling directives (@agent,
@services command) promise/enforce — not just the allow_query_shell
config flag.

Note: tests/conftest.py sets PERSEUS_ALLOW_DANGEROUS=1 autouse (the gate's
intended posture per #94/#95); the denied-path tests below delete it.
"""

import copy

import perseus


def _cfg(tmp_path, allow_shell=True):
    cfg = copy.deepcopy(perseus.DEFAULT_CONFIG)
    cfg["render"]["allow_query_shell"] = allow_shell
    return cfg


def test_query_denied_without_env_gate(tmp_path, monkeypatch):
    """allow_query_shell=true alone must NOT execute; warning names the fix."""
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    out = perseus.resolve_query('"echo GATE-LEAK"', _cfg(tmp_path), tmp_path)
    assert "GATE-LEAK" not in out
    assert "PERSEUS_ALLOW_DANGEROUS" in out
    assert "export PERSEUS_ALLOW_DANGEROUS=1" in out


def test_query_denied_emits_policy_audit(tmp_path, monkeypatch):
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    events = []
    monkeypatch.setattr(
        perseus, "audit_event",
        lambda cfg, event, **kw: events.append((event, kw)),
    )
    perseus.resolve_query('"echo x"', _cfg(tmp_path), tmp_path)
    assert events, "denied @query must emit an audit event"
    event, kw = events[0]
    assert event == "policy_denied"
    assert kw.get("directive") == "@query"
    assert kw.get("reason") == "PERSEUS_ALLOW_DANGEROUS not set"


def test_query_config_gate_still_checked_first(tmp_path, monkeypatch):
    """Config-off must report the config gate, not the env gate."""
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    out = perseus.resolve_query('"echo x"', _cfg(tmp_path, allow_shell=False), tmp_path)
    assert "allow_query_shell" in out
    assert "PERSEUS_ALLOW_DANGEROUS" not in out


def test_query_executes_with_both_gates(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    out = perseus.resolve_query('"echo GATES-OPEN"', _cfg(tmp_path), tmp_path)
    assert "GATES-OPEN" in out


def test_if_query_condition_denied_without_env_gate(tmp_path, monkeypatch):
    """#616 review follow-up: @if query(...) is the same arbitrary-shell
    surface as @query and must enforce the same env gate. The denied path
    must not spawn ANY subprocess and must evaluate to False."""
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    spawned = []
    monkeypatch.setattr(
        perseus.subprocess, "run",
        lambda *a, **kw: spawned.append(a) or (_ for _ in ()).throw(
            AssertionError("subprocess.run must not be reached")),
    )
    result = perseus.evaluate_condition(
        'query("echo HELLO") matches /HELLO/', tmp_path, _cfg(tmp_path))
    assert result is False
    assert spawned == [], "@if query executed a subprocess despite unset env gate"


def test_if_query_condition_runs_with_both_gates(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    result = perseus.evaluate_condition(
        'query("echo HELLO") matches /HELLO/', tmp_path, _cfg(tmp_path))
    assert result is True


def test_if_query_condition_denied_emits_policy_audit(tmp_path, monkeypatch):
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS", raising=False)
    events = []
    monkeypatch.setattr(
        perseus, "audit_event",
        lambda cfg, event, **kw: events.append((event, kw)),
    )
    perseus.evaluate_condition(
        'query("echo x") matches /x/', tmp_path, _cfg(tmp_path))
    assert events, "denied @if query must emit an audit event"
    event, kw = events[0]
    assert event == "policy_denied"
    assert kw.get("directive") == "@if query"
    assert kw.get("reason") == "PERSEUS_ALLOW_DANGEROUS not set"


def test_query_fingerprint_tracks_env_gate(tmp_path, monkeypatch):
    """@query is now env-gated (#616): its cache fingerprint must flip with
    PERSEUS_ALLOW_DANGEROUS so a cached 'gate not set' warning cannot be
    served after the operator exports the var (and vice versa)."""
    assert "@query" in perseus._ENV_GATED_DIRECTIVES
    cfg = _cfg(tmp_path)
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")
    fp_on = perseus._dependency_fingerprint("@query", '"echo x"', tmp_path, cfg)
    monkeypatch.delenv("PERSEUS_ALLOW_DANGEROUS")
    fp_off = perseus._dependency_fingerprint("@query", '"echo x"', tmp_path, cfg)
    assert fp_on and fp_off and fp_on != fp_off
