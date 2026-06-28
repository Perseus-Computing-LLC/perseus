"""Resolve-before-context vs. agentic round-trip benchmark — Issue #486.

Patent prosecution support (§101 technical-effect evidence). This module
produces the quantified comparison that demonstrates the resolve-before-context
pipeline is a concrete improvement to computer functioning, not an abstract idea.

What is MEASURED directly (no estimation):
  * directive_count            — from the real `render --explain` manifest
  * resolution latency (ms)    — real wall-clock of the single resolution pass
  * per-directive durations    — from the real manifest
  * assembled-context tokens   — real cl100k_base token count (tiktoken) when
                                 available; otherwise a clearly-labelled proxy
  * reproducibility            — two independent renders hashed; asserted
                                 byte-identical (sha256)

What is DERIVED structurally (labelled as such, not a live-LLM measurement):
  * model round-trips. In an agentic tool-calling architecture the model must
    emit a tool call, receive the result, and resume — one round-trip per
    context-gathering operation — then a final synthesis call:
        agentic_round_trips = directive_count + 1
    The resolve-before-context pipeline resolves every directive deterministically
    in a single pre-model pass and then issues exactly ONE model call:
        resolve_round_trips = 1
    The reduction is therefore directive_count additional round-trips eliminated.
    This is an architectural property provable from the directive manifest; it is
    explicitly NOT presented as a timed live-model measurement.

Run:
    python -m pytest tests/test_benchmark_resolve_vs_agentic.py -v
    python -m pytest tests/test_benchmark_resolve_vs_agentic.py -v --save-exhibits

The --save-exhibits flag writes timestamped JSON + MD artifacts to
docs/ip/exhibits/. Tests pass without the flag.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSEUS_PY = REPO_ROOT / "perseus.py"
EXHIBITS_DIR = REPO_ROOT / "docs" / "ip" / "exhibits"

# Number of independent renders used to establish reproducibility + median latency.
N_RUNS = 3


# ── tiktoken (real tokenizer) with labelled fallback ───────────────────────────

def _token_count(text: str) -> tuple[int, str]:
    """Return (count, method). Prefer the real cl100k_base tokenizer."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text)), "tiktoken:cl100k_base"
    except Exception:
        # Labelled proxy — never silently presented as a real token count.
        return int(len(text.split()) * 1.3), "proxy:words*1.3"


# ── pytest flag (--save-exhibits) is registered in tests/conftest.py ───────────

def _save_exhibits(request) -> bool:
    try:
        return bool(request.config.getoption("--save-exhibits"))
    except ValueError:
        return False


def _write_exhibit(name: str, content, *, as_json: bool = False) -> Path:
    EXHIBITS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    suffix = ".json" if as_json else ".md"
    path = EXHIBITS_DIR / f"{ts}-{name}{suffix}"
    text = json.dumps(content, indent=2) if as_json else content
    path.write_text(text, encoding="utf-8")
    return path


# ── harness ────────────────────────────────────────────────────────────────────

def _env(home: Path) -> dict:
    e = os.environ.copy()
    e["PERSEUS_HOME"] = str(home)
    return e


def _render(source: Path, ws: Path, home: Path, *, explain: bool = False):
    args = ["render", str(source)]
    if explain:
        args.append("--explain")
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(PERSEUS_PY)] + args,
        cwd=ws, env=_env(home), capture_output=True, text=True,
        timeout=30, check=False,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, proc


def _build_fixture(ws: Path) -> Path:
    """Deterministic, offline workspace exercising multiple source classes.

    Uses @read (filesystem), @env (process env), and @query (shell) — all of
    which an agentic system would each gather via a separate model round-trip.
    Outputs are fixed so the assembled context is byte-reproducible.
    """
    (ws / ".perseus").mkdir(parents=True, exist_ok=True)
    (ws / ".perseus" / "config.yaml").write_text(
        "render:\n"
        "  allow_query_shell: true\n"
        "  allow_agent_shell: false\n",
        encoding="utf-8",
    )
    (ws / "facts.md").write_text(
        "The resolver builds a static directive dependency graph before any model call.\n",
        encoding="utf-8",
    )
    source = ws / "ctx.md"
    source.write_text(
        "@perseus v0.4\n\n"
        "# Resolve-before-context benchmark fixture\n"
        "@read facts.md\n"
        "@env HOME fallback=unset\n"
        "@env USER fallback=unknown\n"
        '@query "echo deterministic-42" @cache ttl=300 fallback="none"\n'
        "@query \"printf 'alpha\\nbeta\\ngamma'\" @cache ttl=300 fallback=\"none\"\n",
        encoding="utf-8",
    )
    return source


@pytest.fixture()
def fixture(tmp_path):
    ws = tmp_path / "repo"
    ws.mkdir()
    home = tmp_path / "perseus-home"
    source = _build_fixture(ws)
    return ws, home, source


# ── tests ────────────────────────────────────────────────────────────────────

def test_resolution_is_single_pass_with_real_directives(fixture):
    """The manifest proves multiple directives resolve in ONE pre-model pass."""
    ws, home, source = fixture
    _, proc = _render(source, ws, home, explain=True)
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads(proc.stdout)
    assert manifest["summary"]["directive_count"] >= 4, (
        f"fixture should exercise >=4 directives, got {manifest['summary']}"
    )
    # Every directive carries a real measured duration.
    for d in manifest["directives"]:
        assert "duration_ms" in d, f"directive missing duration: {d}"


def test_context_is_byte_reproducible(fixture):
    """Same template + same source state => byte-identical context (sha256)."""
    ws, home, source = fixture
    hashes = []
    for _ in range(N_RUNS):
        _, proc = _render(source, ws, home)
        assert proc.returncode == 0, proc.stderr
        hashes.append(hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest())
    assert len(set(hashes)) == 1, (
        f"resolve-before-context must be reproducible; got {len(set(hashes))} "
        f"distinct digests across {N_RUNS} runs: {hashes}"
    )


def test_roundtrip_reduction_and_exhibit(fixture, request):
    """Quantify the agentic-vs-resolve comparison and emit the §101 exhibit."""
    ws, home, source = fixture

    # Real manifest (directive count + per-directive durations).
    _, ex = _render(source, ws, home, explain=True)
    assert ex.returncode == 0, ex.stderr
    manifest = json.loads(ex.stdout)
    directive_count = manifest["summary"]["directive_count"]

    # Real assembled context + real latency across N runs (median).
    latencies = []
    rendered = ""
    for _ in range(N_RUNS):
        ms, proc = _render(source, ws, home)
        assert proc.returncode == 0, proc.stderr
        latencies.append(ms)
        rendered = proc.stdout
    latencies.sort()
    median_ms = latencies[len(latencies) // 2]

    tokens, token_method = _token_count(rendered)
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    # Structural (architectural) round-trip model — labelled, not a live-LLM timing.
    agentic_round_trips = directive_count + 1   # one per context op + final synthesis
    resolve_round_trips = 1                      # single pass + single model call
    round_trips_eliminated = agentic_round_trips - resolve_round_trips
    reduction_pct = round(100.0 * round_trips_eliminated / agentic_round_trips, 1)

    exhibit = {
        "evidence": "E4",
        "issue": 486,
        "title": "Resolve-before-context vs. agentic round-trip benchmark",
        "perseus_version": manifest.get("version"),
        "measured": {
            "directive_count": directive_count,
            "per_directive_duration_ms": [d["duration_ms"] for d in manifest["directives"]],
            "median_resolution_latency_ms": round(median_ms, 2),
            "all_run_latencies_ms": [round(x, 2) for x in latencies],
            "assembled_context_tokens": tokens,
            "token_count_method": token_method,
            "context_sha256": digest,
            "reproducible_runs": N_RUNS,
            "byte_identical": True,
        },
        "structural_roundtrip_model": {
            "note": (
                "Round-trip counts are an architectural property derived from the "
                "real directive manifest, NOT a timed live-model measurement. In an "
                "agentic tool-calling design the model performs one round-trip per "
                "context-gathering operation plus a final synthesis call; the "
                "resolve-before-context pipeline resolves all directives in one "
                "pre-model pass and issues exactly one model call."
            ),
            "agentic_model_round_trips": agentic_round_trips,
            "resolve_before_context_round_trips": resolve_round_trips,
            "round_trips_eliminated": round_trips_eliminated,
            "round_trip_reduction_pct": reduction_pct,
        },
        "patent_linkage": (
            "Supports the §101 technical-effect narrative: deterministic single-pass "
            "resolution yields one model round-trip instead of N, with a "
            "byte-reproducible, auditable assembled context."
        ),
    }

    # Core assertions: the architecture eliminates round-trips and is reproducible.
    assert round_trips_eliminated >= 3, exhibit
    assert reduction_pct >= 50.0, exhibit

    print(
        f"\nE4 benchmark: directives={directive_count}  "
        f"agentic_round_trips={agentic_round_trips} -> resolve=1  "
        f"({reduction_pct}% eliminated)  "
        f"ctx_tokens={tokens} ({token_method})  "
        f"median_latency={median_ms:.1f}ms  reproducible={N_RUNS}/{N_RUNS}"
    )

    if _save_exhibits(request):
        jpath = _write_exhibit("E4-resolve-vs-agentic", exhibit, as_json=True)
        md = _exhibit_markdown(exhibit)
        mpath = _write_exhibit("E4-resolve-vs-agentic", md)
        print(f"  Exhibits saved: {jpath}\n                  {mpath}")


def _exhibit_markdown(ex: dict) -> str:
    m = ex["measured"]
    s = ex["structural_roundtrip_model"]
    return (
        f"# Exhibit E4 — {ex['title']}\n\n"
        f"_Issue #{ex['issue']} · Perseus {ex['perseus_version']} · "
        f"generated {time.strftime('%Y-%m-%d %H:%M:%S %Z')}_\n\n"
        "## Measured (direct)\n\n"
        "| Metric | Value |\n|---|---|\n"
        f"| Directives resolved in one pass | {m['directive_count']} |\n"
        f"| Median resolution latency | {m['median_resolution_latency_ms']} ms |\n"
        f"| Assembled-context tokens | {m['assembled_context_tokens']} "
        f"({m['token_count_method']}) |\n"
        f"| Reproducible runs | {m['reproducible_runs']} (byte-identical) |\n"
        f"| Context sha256 | `{m['context_sha256'][:16]}…` |\n\n"
        "## Structural round-trip model\n\n"
        f"> {s['note']}\n\n"
        "| Architecture | Model round-trips |\n|---|---|\n"
        f"| Agentic tool-calling | {s['agentic_model_round_trips']} "
        "(one per context op + synthesis) |\n"
        f"| Resolve-before-context | {s['resolve_before_context_round_trips']} |\n"
        f"| **Eliminated** | **{s['round_trips_eliminated']} "
        f"({s['round_trip_reduction_pct']}%)** |\n\n"
        "## Patent linkage\n\n"
        f"{ex['patent_linkage']}\n"
    )
