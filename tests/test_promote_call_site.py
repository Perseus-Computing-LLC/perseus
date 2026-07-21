"""test_promote_call_site.py — #832 perseus-side promotion call-site.

MnemeConnector.promote() is the perseus-side trigger for the vault's
mimir_promote primitive (shipped in perseus-vault#731). These tests pin:

- argument shaping (only non-None target fields are sent)
- canonical tool-name resolution (perseus_vault_promote preferred)
- success / vault-error / transport-error / not-connected paths
"""

import importlib.util
import sys
import types
from pathlib import Path

# Load mneme_connector by explicit path with a temporary synthetic package
# (same pattern as test_composite_ranking.py / test_memory_render_provenance.py)
# so the repo-root perseus.py artifact keeps shadowing src/perseus for every
# other test module.
_SRC = Path(__file__).resolve().parents[1] / "src" / "perseus"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_saved = {k: v for k, v in sys.modules.items() if k == "perseus" or k.startswith("perseus.")}
_pkg = types.ModuleType("perseus")
_pkg.__path__ = [str(_SRC)]
sys.modules["perseus"] = _pkg
try:
    _load("perseus.composite_ranking", _SRC / "composite_ranking.py")
    _load("perseus.retrieval_expansion", _SRC / "retrieval_expansion.py")
    mc = _load("perseus.mneme_connector", _SRC / "mneme_connector.py")
finally:
    for k in ("perseus", "perseus.composite_ranking", "perseus.retrieval_expansion", "perseus.mneme_connector"):
        sys.modules.pop(k, None)
    sys.modules.update(_saved)


class FakeClient:
    """Records calls; serves canned responses keyed by tool name."""

    def __init__(self, responses=None, tools=None):
        self.calls = []
        self.responses = responses or {}
        self._tools = tools or []
        self.is_connected = True

    def call_tool(self, name, args):
        self.calls.append((name, args))
        return self.responses.get(name, (None, f"unknown tool {name}"))

    def list_tools(self):
        return [{"name": t} for t in self._tools]


def make_connector(client, *, connected=True):
    conn = mc.MnemeConnector({"mneme": {"enabled": False}})
    conn._enabled = True
    conn._client = client
    conn._ensure_connected = lambda: connected  # noqa: E731
    # Simulate the post-handshake canonical-name resolution.
    conn._tool_names = {"mimir_promote": "perseus_vault_promote"}
    return conn


PROMOTE_OK = {
    "promoted": True,
    "action": "created",
    "from": "episodes/incident-42",
    "from_id": "mem-src00000001",
    "to": "convention/incident-42",
    "to_id": "mem-new00000001",
    "to_workspace_hash": "",
    "reason": "recurred three times",
}


def test_promote_sends_only_set_fields_and_returns_result():
    client = FakeClient(responses={"perseus_vault_promote": (PROMOTE_OK, None)})
    conn = make_connector(client)

    ok, out = conn.promote(
        "episodes", "incident-42",
        to_category="convention", reason="recurred three times",
    )

    assert ok is True
    assert out["to_id"] == "mem-new00000001"
    name, args = client.calls[0]
    assert name == "perseus_vault_promote", "legacy name must resolve to canonical"
    assert args == {
        "from_category": "episodes",
        "from_key": "incident-42",
        "to_category": "convention",
        "reason": "recurred three times",
    }, f"unset fields must not be sent: {args}"


def test_promote_scope_ladder_passes_workspace_hash():
    client = FakeClient(responses={"perseus_vault_promote": (PROMOTE_OK, None)})
    conn = make_connector(client)

    ok, _ = conn.promote("notes", "n1", to_workspace_hash="team-eng", to_key="shared-n1")

    assert ok is True
    _, args = client.calls[0]
    assert args["to_workspace_hash"] == "team-eng"
    assert args["to_key"] == "shared-n1"
    assert "to_category" not in args
    assert "reason" not in args


def test_promote_surfaces_vault_error_dict():
    client = FakeClient(responses={
        "perseus_vault_promote": ({"error": "Source entity not found: episodes/nope"}, None),
    })
    conn = make_connector(client)

    ok, err = conn.promote("episodes", "nope", to_category="convention")

    assert ok is False
    assert "not found" in err


def test_promote_surfaces_transport_error():
    client = FakeClient(responses={
        "perseus_vault_promote": (None, "vault process exited"),
    })
    conn = make_connector(client)

    ok, err = conn.promote("episodes", "e1", to_category="convention")

    assert ok is False
    assert "vault process exited" in err


def test_promote_when_not_connected_returns_status():
    client = FakeClient()
    conn = make_connector(client, connected=False)

    ok, err = conn.promote("episodes", "e1", to_category="convention")

    assert ok is False
    assert err == conn.status, "failure must surface the connector status"
    assert client.calls == [], "no MCP call may be attempted when disconnected"


def test_promote_rejects_malformed_success_response():
    client = FakeClient(responses={
        "perseus_vault_promote": ({"unexpected": "shape"}, None),
    })
    conn = make_connector(client)

    ok, err = conn.promote("episodes", "e1", to_category="convention")

    assert ok is False
    assert "unexpected" in err


def test_mimir_promote_registered_for_canonical_resolution():
    """_check_tool_compatibility must map mimir_promote → perseus_vault_promote."""
    client = FakeClient(tools=["perseus_vault_promote", "perseus_vault_recall"])
    conn = mc.MnemeConnector({"mneme": {"enabled": False}})
    conn._client = client

    conn._check_tool_compatibility()

    assert conn._tool_names["mimir_promote"] == "perseus_vault_promote"


def test_mimir_promote_falls_back_to_legacy_name_on_old_vault():
    """A vault without perseus_vault_promote but with the mimir_ alias resolves there."""
    client = FakeClient(tools=["mimir_promote"])
    conn = mc.MnemeConnector({"mneme": {"enabled": False}})
    conn._client = client

    conn._check_tool_compatibility()

    assert conn._tool_names["mimir_promote"] == "mimir_promote"
