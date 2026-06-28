"""Claim element (f): directive resolution happens OUTSIDE the model control loop.

Issue #487 — patent prosecution support.

The sharpest distinction from every agentic prior-art reference (Twilio
WO2025221751A1, Intuit US20250139367A1 / US12423313B1, agentic MCP-in-practice)
is that **the language model does not decide which directives fire**. A
deterministic resolver selects and expands author-specified directives BEFORE
any model is invoked. There is no model in the resolution loop.

This module proves that property in-process:

  * It imports the built ``perseus.py`` artifact and calls the real
    ``render_source`` entrypoint on a fixture that exercises multiple directive
    classes (@read / @env / @query).
  * It installs spies on EVERY model-reachable egress — outbound sockets,
    ``http.client`` requests, and ``urllib.request.urlopen`` — because the only
    way a language model could participate in resolution is by being contacted
    over one of those. (Perseus speaks to model providers, incl. local Ollama,
    over HTTP.)
  * It asserts the directives fully resolve (concrete content substituted) AND
    the model-egress call count is exactly ZERO.

Contrast (the §103 argument): unlike agentic tool-calling, where the model
emits tool-call tokens and the orchestration loop feeds results back to the
model turn after turn, Perseus resolves author-specified directives
deterministically out-of-loop. Combining MCP/Helicone-style observability with
agentic tool-calling would still leave the *model* driving directive selection
— the opposite of this teaching — which is evidence against obviousness.

Run:
    python -m pytest tests/test_resolution_out_of_model_loop.py -v
    python -m pytest tests/test_resolution_out_of_model_loop.py -v --save-exhibits
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import os
import socket
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSEUS_PY = REPO_ROOT / "perseus.py"
EXHIBITS_DIR = REPO_ROOT / "docs" / "ip" / "exhibits"


# ── import the built artifact in-process ───────────────────────────────────────

@pytest.fixture(scope="module")
def perseus_mod():
    spec = importlib.util.spec_from_file_location("perseus_artifact", PERSEUS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── model-egress spy ───────────────────────────────────────────────────────────

class _EgressSpy:
    """Records every outbound network operation during resolution.

    A language model can only participate in resolution by being contacted over
    the network. We patch the three egress chokepoints any model client (remote
    API or local Ollama) must traverse and record each call. Loopback DNS /
    unix-socket noise is irrelevant: real resolution should produce ZERO of any
    of these.
    """

    def __init__(self):
        self.calls: list[dict] = []

    def __enter__(self):
        self._orig_connect = socket.socket.connect
        self._orig_http_request = http.client.HTTPConnection.request
        self._orig_urlopen = urllib.request.urlopen
        spy = self

        def connect(self, address, *a, **k):  # noqa: ANN001
            spy.calls.append({"egress": "socket.connect", "target": repr(address)})
            return spy._orig_connect(self, address, *a, **k)

        def request(self, method, url, *a, **k):  # noqa: ANN001
            spy.calls.append({"egress": "http.request", "target": f"{method} {url}"})
            return spy._orig_http_request(self, method, url, *a, **k)

        def urlopen(url, *a, **k):  # noqa: ANN001
            target = getattr(url, "full_url", url)
            spy.calls.append({"egress": "urllib.urlopen", "target": str(target)})
            return spy._orig_urlopen(url, *a, **k)

        socket.socket.connect = connect
        http.client.HTTPConnection.request = request
        urllib.request.urlopen = urlopen
        return self

    def __exit__(self, *exc):
        socket.socket.connect = self._orig_connect
        http.client.HTTPConnection.request = self._orig_http_request
        urllib.request.urlopen = self._orig_urlopen
        return False


# ── deterministic, fully-offline fixture ───────────────────────────────────────

def _build_workspace(ws: Path) -> tuple[str, dict]:
    (ws / "facts.md").write_text(
        "Resolution is performed by a deterministic resolver, not by the model.\n",
        encoding="utf-8",
    )
    cfg = {
        "render": {"allow_query_shell": True, "allow_agent_shell": False},
    }
    source = (
        "@perseus v0.4\n\n"
        "# Out-of-loop resolution fixture\n"
        "@read facts.md\n"
        "@env HOME fallback=unset\n"
        '@query "echo resolved-out-of-loop" fallback="none"\n'
    )
    return source, cfg


# ── flag plumbing (--save-exhibits registered in conftest.py) ──────────────────

def _save_exhibits(request) -> bool:
    try:
        return bool(request.config.getoption("--save-exhibits"))
    except ValueError:
        return False


# ── tests ──────────────────────────────────────────────────────────────────────

def test_resolution_makes_zero_model_calls(perseus_mod, tmp_path, request):
    """Directives resolve to concrete content with ZERO model-reachable egress."""
    os.environ["PERSEUS_ALLOW_DANGEROUS"] = "1"  # unlock @query in-process
    ws = tmp_path / "repo"
    ws.mkdir()
    source, cfg = _build_workspace(ws)

    collector: list[dict] = []
    with _EgressSpy() as spy:
        rendered = perseus_mod.render_source(
            source, cfg, workspace=ws, _directive_collector=collector,
        )

    # (1) The directives genuinely fired and produced concrete content — this is
    #     not a vacuous "zero calls because nothing happened" result.
    assert "deterministic resolver" in rendered, rendered  # @read body
    assert "resolved-out-of-loop" in rendered, rendered     # @query stdout
    assert "@read" not in rendered and "@query" not in rendered, (
        f"directives must be fully expanded, not echoed:\n{rendered}"
    )
    directive_count = len(collector)
    assert directive_count >= 3, f"fixture should fire >=3 directives: {collector}"

    # (2) The core claim: no language model was contacted during resolution.
    model_calls = spy.calls
    assert model_calls == [], (
        "directive resolution must occur OUTSIDE the model control loop; "
        f"observed {len(model_calls)} network egress call(s): {model_calls}"
    )

    # Exhibit E5.
    exhibit = {
        "evidence": "E5",
        "issue": 487,
        "title": "Directive resolution occurs outside the model control loop",
        "perseus_version": getattr(perseus_mod, "_PERSEUS_VERSION", None),
        "measured": {
            "directives_resolved": directive_count,
            "directive_classes": sorted({d.get("directive", d.get("name", "?"))
                                         for d in collector}),
            "model_egress_calls_during_resolution": len(model_calls),
            "rendered_contains_resolved_content": True,
            "rendered_contains_unexpanded_directives": False,
        },
        "method": (
            "Imported the built perseus.py artifact and called render_source() "
            "in-process while spying on socket.connect, http.client request, and "
            "urllib.urlopen — the only egress paths by which any model client "
            "(remote API or local Ollama) could be contacted. Call count asserted "
            "== 0 across full resolution of @read/@env/@query directives."
        ),
        "patent_linkage": (
            "Claim element (f): the resolver selects and expands author-specified "
            "directives deterministically and prior to model invocation. Unlike "
            "agentic tool-calling, the model does not emit tool-call tokens or "
            "decide which directives fire. This defeats the §103 combination of "
            "MCP/observability + agentic tool-calling: that combination keeps the "
            "model in the loop, the opposite of this teaching."
        ),
    }

    print(
        f"\nE5 out-of-loop proof: {directive_count} directives resolved, "
        f"{len(model_calls)} model-egress calls during resolution"
    )

    if _save_exhibits(request):
        EXHIBITS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        jp = EXHIBITS_DIR / f"{ts}-E5-out-of-model-loop.json"
        jp.write_text(json.dumps(exhibit, indent=2), encoding="utf-8")
        md = _exhibit_markdown(exhibit)
        mp = EXHIBITS_DIR / f"{ts}-E5-out-of-model-loop.md"
        mp.write_text(md, encoding="utf-8")
        print(f"  Exhibits saved: {jp}\n                  {mp}")


def test_spy_actually_catches_egress(perseus_mod):
    """Guard: the spy is real. A deliberate egress attempt must be recorded.

    Without this, a silently-broken spy would make the zero-call assertion above
    vacuously pass. We attempt one loopback connection to a closed port and only
    require that the spy *recorded the attempt* (connection success irrelevant).
    """
    with _EgressSpy() as spy:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.05)
        try:
            s.connect(("127.0.0.1", 9))  # discard port; refusal/timeout is fine
        except OSError:
            pass
        finally:
            s.close()
    assert any(c["egress"] == "socket.connect" for c in spy.calls), (
        "egress spy failed to record a real outbound connection; the zero-call "
        "assertion in the sibling test would be unreliable"
    )


def _exhibit_markdown(ex: dict) -> str:
    m = ex["measured"]
    return (
        f"# Exhibit E5 — {ex['title']}\n\n"
        f"_Issue #{ex['issue']} · Perseus {ex['perseus_version']} · "
        f"generated {time.strftime('%Y-%m-%d %H:%M:%S %Z')}_\n\n"
        "## Measured (direct, in-process)\n\n"
        "| Metric | Value |\n|---|---|\n"
        f"| Directives resolved | {m['directives_resolved']} |\n"
        f"| Directive classes | {', '.join(m['directive_classes'])} |\n"
        f"| **Model-egress calls during resolution** | **{m['model_egress_calls_during_resolution']}** |\n"
        f"| Resolved content present | {m['rendered_contains_resolved_content']} |\n"
        f"| Unexpanded directives present | {m['rendered_contains_unexpanded_directives']} |\n\n"
        "## Method\n\n"
        f"{ex['method']}\n\n"
        "## Patent linkage\n\n"
        f"{ex['patent_linkage']}\n"
    )
