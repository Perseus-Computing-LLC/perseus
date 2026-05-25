---
id: task-27
title: "LSP integration test harness \u2014 exercise the real JSON-RPC loop"
status: completed
priority: medium
scope: medium
claimed_by: null
created: 2026-05-18
closed: 2026-05-19
phase: 11
theme: "C \u2014 Editor + LSP polish"
depends_on:
- task-25
blocks: []
opened: '2026-05-18'
---
## Why

Per the 2026-05-18 review: the existing LSP tests cover helpers (message
framing, diagnostic generation, URI parsing) but do **not** test the real
request loop. That means none of the following are covered:

- initialize → initialized → capabilities response shape against a client
- didOpen → publishDiagnostics over actual JSON-RPC
- didChange full-sync behavior
- hover side effects (and proof that hover never executes shell)
- completion behavior at realistic cursor positions
- executeCommand routing + mutation guard
- TCP transport vs stdio transport equivalence
- shutdown/exit semantics
- malformed JSON-RPC handling

The reviewer specifically flagged: "no test would catch the most worrying LSP
behavior: hover over `@agent` can execute a process." A regression test was
added in the v0.8.1 review-fix pass at the helper level, but a real
end-to-end test that spawns the server and sends the hover request over
JSON-RPC is the only way to truly lock the contract.

## What

Add an `LSPHarness` test fixture that:

1. Spawns `python perseus.py serve --lsp --stdio` as a subprocess.
2. Writes Content-Length-framed JSON-RPC messages to its stdin.
3. Reads framed responses from its stdout.
4. Provides helpers: `harness.request(method, params)`,
   `harness.notify(method, params)`, `harness.expect_notification(method)`,
   `harness.shutdown()`.
5. Has a context-manager interface that guarantees the subprocess is
   reaped on test exit.

Then write integration tests:

```python
def test_lsp_initialize_returns_capabilities(lsp_harness):
    rsp = lsp_harness.request("initialize", {
        "rootUri": f"file://{lsp_harness.workspace}",
        "capabilities": {},
    })
    caps = rsp["result"]["capabilities"]
    assert caps["textDocumentSync"] == 1                  # full sync
    assert caps["hoverProvider"] is True
    assert caps["completionProvider"]["triggerCharacters"] == ["@"]
    assert "executeCommandProvider" in caps

def test_lsp_didopen_publishes_diagnostics(lsp_harness):
    lsp_harness.notify("textDocument/didOpen", {
        "textDocument": {"uri": ..., "languageId": "markdown", "version": 1,
                          "text": "@if env.set FOO\nx\n"},   # missing @endif
    })
    diag = lsp_harness.expect_notification("textDocument/publishDiagnostics")
    assert any("unclosed @if" in d["message"].lower() for d in diag["params"]["diagnostics"])

def test_lsp_hover_over_agent_never_executes(lsp_harness):
    # Open a document containing `@agent echo ATTACK`.
    # Hover over it. The response MUST be the labelled stub.
    # The string "ATTACK" must NEVER appear in the hover output.
    ...

def test_lsp_executecommand_compact_memory_requires_mutation_capability(lsp_harness):
    """Hover/compact must be gated even when invoked via executeCommand."""
    ...

def test_lsp_tcp_transport_equivalence(lsp_harness_tcp):
    """Same tests over TCP should behave identically to stdio."""
    ...

def test_lsp_malformed_jsonrpc_returns_parse_error(lsp_harness):
    """Garbled input should yield -32700 Parse error, not crash."""
    ...
```

## Acceptance criteria

1. Harness fixture is reliable: 100 consecutive runs (`pytest -q --count=100`
   if `pytest-repeat` is added, or a manual loop) all pass.
2. Subprocess is always reaped even on test failure (atexit handler + finalizer).
3. Tests are tagged `@pytest.mark.slow` if they take > 0.5s each; default
   `pytest` run still includes them but a `-m "not slow"` skip is supported.
4. At least one test proves `@agent` hover does not execute (string
   should-not-appear assertion).
5. At least one test exercises `executeCommand` and confirms only
   read-only commands succeed when the appropriate gate is unset.
6. TCP transport has at least one end-to-end test (bind to ephemeral
   port, connect, exchange initialize, close cleanly).
7. Coverage gap on `_run_lsp_server` event loop drops measurably (informal —
   no coverage CI is in place, judgement call).

## Non-goals

- Do not add `pytest-asyncio` or any new dependency. Subprocess + plain
  pipes is sufficient for a single-client LSP.
- Do not test against a real editor (VSCode, Helix). That's manual smoke
  testing.
- Do not test completion ranking quality — only that completions fire
  and contain expected entries.

## Start here

1. Write the `LSPHarness` class as a pytest fixture in `tests/test_perseus.py`
   (or `tests/test_lsp.py` once task-29 splits the suite).
2. Write `test_lsp_initialize_returns_capabilities` and get it green.
3. Layer in the other tests one at a time.
4. Make sure `pytest -q` doesn't slow down by more than ~2s overall.

## Completed

- Added a real subprocess JSON-RPC harness for `perseus serve --lsp --stdio`.
- Covered initialize, didOpen/didChange diagnostics, completion from
  `DIRECTIVE_REGISTRY`, safe hover over `@agent`, shutdown/exit, malformed
  JSON-RPC, and TCP initialize smoke.
- Added the LSP mutation gate: `perseus.compactMemory` now requires
  `--allow-lsp-mutations`; the VSCode bridge exposes this as
  `perseus.allowMutations`.
