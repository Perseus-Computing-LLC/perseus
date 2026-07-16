#!/usr/bin/env python3
"""Honest prompt-token A/B harness (#804).

Measured question: for the same information need, how many prompt tokens does
a request carry when context is assembled naively (arm A) versus by Perseus's
shipped defaults (arm B)?

Replaces the retired synthetic harness (#803): the old one added a hard-coded
+250 token penalty to the baseline arm, counted only the compiled context for
the product arm, and stubbed all timing. This harness has none of that:

- Corpus: the Perseus repository itself at a pinned commit (recorded in the
  report), same precedent as benchmark/real_deltas.json.
- Arm B: `perseus render` run as a real subprocess with SHIPPED DEFAULTS
  (fresh PERSEUS_HOME per cold run, so no user config leaks in). Rendered
  cold (empty cache) and warm (second render, same PERSEUS_HOME); both are
  reported and the headline is the less favorable (cold).
- Arm A: the same information assembled naively: every @include directive is
  replaced by the FULL referenced file content (no last=/since= window, no
  mode=reference pointer), concatenated with a minimal one-line header per
  file. @prompt block text is kept verbatim (a naive doc would carry the same
  instructions as plain text). The @memory pointer contributes ZERO tokens to
  arm A because the repo corpus contains no local narrative or memory files;
  nothing is invented. No penalties, no multipliers, no synthetic overhead.
- Both arms count the FULL request identically: a fixed system stub (same
  bytes in both arms, reported separately and excluded from the reduction
  percentage), the assembled context, and the same fixture set of user
  prompts.
- Tokenizer: tiktoken cl100k_base. Hard failure if tiktoken is missing;
  there is no len//4 fallback in this harness.
- Overhead: the `perseus render` subprocess (including interpreter startup)
  is timed inside the measurement window; arm A assembly is timed the same
  way. No sleeps, no stub latency.

Usage (from the repo root, network-free):

    python3 benchmark/tokenab/harness.py \
        --out benchmark/tokenab/report.json

Only stdlib + tiktoken. See benchmark/tokenab/README.md for methodology and
limits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import tiktoken
except ImportError:  # hard requirement, checked at use time so imports stay cheap
    tiktoken = None

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
FIXTURES = HERE / "fixtures"
TOKENIZER = "cl100k_base"

# Directives the arm A builder knows how to mirror. Anything else in a fixture
# is a hard error so the naive arm can never silently drop information.
_INCLUDE_RE = re.compile(r"^@include\s+(.*)$")
_MEMORY_RE = re.compile(r"^@memory\b")
_OTHER_DIRECTIVE_RE = re.compile(
    r"@(?:date|env|query|read|waypoint|session|services|health|agora|skills|"
    r"mimir|mneme|tree|list|agent|tool|capture|drift|context-diff|synthesize|"
    r"if|else|endif|constraint|validate|inbox|research|focus|profile|budget|"
    r"tokens|bandit|auto-skill|perseus\s+http)\b")


def _encoder():
    if tiktoken is None:
        sys.stderr.write(
            "FATAL: tiktoken is required for this harness (tokenizer-accurate "
            "counts are part of the methodology; there is no len//4 fallback). "
            "pip install tiktoken\n")
        raise SystemExit(2)
    return tiktoken.get_encoding(TOKENIZER)


def count_tokens(enc, text: str) -> int:
    return len(enc.encode(text, disallowed_special=()))


def _extract_include_path(args_str: str) -> tuple[str, dict]:
    """Return (path, options) from the text after `@include`."""
    raw = args_str.strip()
    if raw and raw[0] in "\"'":
        quote = raw[0]
        end = raw.index(quote, 1)
        path = raw[1:end]
        rest = raw[end + 1:]
    else:
        parts = raw.split(None, 1)
        path = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
    opts = dict(re.findall(r"(\w+)=([^\s]+)", rest))
    return path, opts


def parse_fixture(text: str) -> list[dict]:
    """Parse a fixture doc into events the arm A builder understands.

    Supported constructs (anything else directive-like is a hard error):
      - `@perseus vX` header line (dropped in arm A)
      - `@prompt` ... `@end` block (inner text kept verbatim in arm A)
      - `@include <path> [last=N] [since=..] [mode=..]`
      - `@memory ...` (zero tokens in arm A: the corpus has no memory files)
      - plain markdown (copied verbatim)
    """
    events: list[dict] = []
    lines = text.splitlines()
    i = 0
    if lines and lines[0].startswith("@perseus"):
        events.append({"kind": "header", "line": lines[0]})
        i = 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "@prompt":
            block: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != "@end":
                block.append(lines[i])
                i += 1
            if i >= len(lines):
                raise ValueError("unterminated @prompt block")
            events.append({"kind": "prompt", "text": "\n".join(block).strip()})
        elif stripped.startswith("@include"):
            path, opts = _extract_include_path(stripped[len("@include"):])
            events.append({"kind": "include", "path": path, "options": opts,
                           "directive": stripped})
        elif _MEMORY_RE.match(stripped):
            events.append({"kind": "memory", "directive": stripped})
        elif _OTHER_DIRECTIVE_RE.search(line):
            raise ValueError(
                f"fixture uses a directive the naive-arm builder does not "
                f"mirror: {line!r}. Add explicit arm A semantics before using it.")
        else:
            events.append({"kind": "text", "line": line})
        i += 1
    return events


def build_arm_a(events: list[dict], workspace: Path) -> str:
    """Assemble the naive baseline: full file contents, minimal headers.

    A strict information superset of arm B: every windowed or referenced
    @include becomes the complete file; @prompt text appears verbatim; the
    @memory pointer maps to zero content because no local narrative or memory
    files exist in the repo corpus (never invented).
    """
    out: list[str] = []
    for ev in events:
        kind = ev["kind"]
        if kind == "header":
            continue  # a naive hand-assembled doc carries no directive header
        if kind == "prompt":
            out.append(ev["text"])
        elif kind == "include":
            fp = (workspace / ev["path"]).resolve()
            if not fp.is_file():
                raise FileNotFoundError(f"arm A include target missing: {fp}")
            content = fp.read_bytes().decode(errors="replace").rstrip()
            out.append(f"## {ev['path']}\n\n{content}")
        elif kind == "memory":
            continue  # corpus has no memory files; contributes zero, never invented
        else:
            out.append(ev["line"])
    return "\n".join(out).strip() + "\n"


def _git(args: list[str]) -> str:
    return subprocess.run(["git"] + args, cwd=REPO_ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def render_arm_b(doc_name: str, doc_text: str, perseus_home: Path,
                 out_dir: Path) -> tuple[str, float]:
    """Run `perseus render` as a real subprocess and time it.

    The timed window covers the whole subprocess, interpreter startup
    included, because that is what a caller actually pays. Returns
    (rendered_text, elapsed_ms).
    """
    staged = REPO_ROOT / ".perseus" / f"tokenab_{doc_name}"
    out_file = out_dir / f"{doc_name}.rendered.md"
    staged.write_text(doc_text, encoding="utf-8")
    env = dict(os.environ)
    env["PERSEUS_HOME"] = str(perseus_home)
    env.pop("PERSEUS_ALLOW_DANGEROUS", None)  # shipped default: shell gates closed
    cmd = [sys.executable, "-X", "utf8", str(REPO_ROOT / "perseus.py"),
           "render", str(staged), "--output", str(out_file), "--quiet"]
    try:
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env,
                              capture_output=True, text=True, timeout=600)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
    finally:
        staged.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"perseus render failed for {doc_name}:\n{proc.stdout}\n{proc.stderr}")
    rendered = out_file.read_text(encoding="utf-8", errors="replace")
    if "⚠ @include" in rendered:
        raise RuntimeError(
            f"render of {doc_name} produced an @include warning; the run is "
            f"invalid:\n{rendered}")
    return rendered, elapsed_ms


def _pct(sorted_vals: list[float], p: float) -> float:
    """Nearest-rank percentile on a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1,
                   int(round(p / 100.0 * len(sorted_vals) + 0.5)) - 1))
    return sorted_vals[k]


def _latency_summary(samples_ms: list[float]) -> dict:
    s = sorted(samples_ms)
    return {
        "n": len(s),
        "min_ms": round(s[0], 1),
        "p50_ms": round(_pct(s, 50), 1),
        "p95_ms": round(_pct(s, 95), 1),
        "max_ms": round(s[-1], 1),
        "mean_ms": round(statistics.fmean(s), 1),
    }


def _reduction_pct(a: int, b: int) -> float:
    if a <= 0:
        return 0.0
    return round(100.0 * (1.0 - (b / a)), 2)


def load_prompts() -> list[str]:
    lines = (FIXTURES / "prompts.txt").read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def assemble_payload(context: str, prompt: str) -> str:
    """Context + user prompt, identical framing in both arms (no system stub:
    the stub is identical in both arms and excluded from the reduction math)."""
    return f"{context.rstrip()}\n\n## User request\n\n{prompt}\n"


def run(cold_runs: int, warm_runs: int, out_path: Path) -> dict:
    enc = _encoder()

    # Refuse to run against a workspace-local config that would silently
    # deviate from shipped defaults.
    local_cfg = REPO_ROOT / ".perseus" / "config.yaml"
    if local_cfg.exists():
        raise SystemExit(
            f"{local_cfg} exists; it would override shipped defaults. "
            f"Run against a clean clone.")

    commit = _git(["rev-parse", "HEAD"])
    dirty = bool(_git(["status", "--porcelain", "--untracked-files=no"]))

    system_stub = (FIXTURES / "system_stub.txt").read_text(encoding="utf-8")
    stub_tokens = count_tokens(enc, system_stub)
    prompts = load_prompts()

    doc_paths = sorted((FIXTURES / "docs").glob("*.md"))
    if not (3 <= len(doc_paths) <= 6):
        raise SystemExit(f"expected 3-6 fixture docs, found {len(doc_paths)}")

    docs_report: list[dict] = []
    cold_samples: list[float] = []
    warm_samples: list[float] = []
    arm_a_samples: list[float] = []
    warnings: list[str] = []

    tot = {"a_ctx": 0, "b_ctx_cold": 0, "b_ctx_warm": 0,
           "a_payload": 0, "b_payload_cold": 0, "b_payload_warm": 0,
           "a_full": 0, "b_full_cold": 0}

    scratch = Path(tempfile.mkdtemp(prefix="tokenab_"))
    try:
        for doc_path in doc_paths:
            name = doc_path.name
            fixture_text = doc_path.read_text(encoding="utf-8")
            events = parse_fixture(fixture_text)

            # Arm A: naive assembly, timed.
            t0 = time.perf_counter()
            arm_a_text = build_arm_a(events, REPO_ROOT)
            arm_a_ms = (time.perf_counter() - t0) * 1000.0
            arm_a_samples.append(arm_a_ms)

            # Arm B cold: fresh PERSEUS_HOME per run (empty cache, default config).
            cold_outputs: list[str] = []
            for r in range(cold_runs):
                home = scratch / f"home_cold_{name}_{r}"
                home.mkdir(parents=True)
                rendered, ms = render_arm_b(name, fixture_text, home, scratch)
                cold_samples.append(ms)
                cold_outputs.append(rendered)
            if len(set(cold_outputs)) > 1:
                warnings.append(
                    f"{name}: cold renders were not byte-identical across "
                    f"{cold_runs} runs; using the largest output for arm B "
                    f"(the choice least favorable to Perseus).")
            arm_b_cold = max(cold_outputs, key=lambda t: count_tokens(enc, t))

            # Arm B warm: prime once (untimed), then timed renders on the same home.
            warm_home = scratch / f"home_warm_{name}"
            warm_home.mkdir(parents=True)
            render_arm_b(name, fixture_text, warm_home, scratch)  # prime
            warm_outputs: list[str] = []
            for _ in range(warm_runs):
                rendered, ms = render_arm_b(name, fixture_text, warm_home, scratch)
                warm_samples.append(ms)
                warm_outputs.append(rendered)
            arm_b_warm = max(warm_outputs, key=lambda t: count_tokens(enc, t))

            a_ctx = count_tokens(enc, arm_a_text)
            b_ctx_cold = count_tokens(enc, arm_b_cold)
            b_ctx_warm = count_tokens(enc, arm_b_warm)

            a_payload = b_payload_cold = b_payload_warm = 0
            a_full = b_full_cold = 0
            for p in prompts:
                a_pl = assemble_payload(arm_a_text, p)
                b_pl_cold = assemble_payload(arm_b_cold, p)
                a_payload += count_tokens(enc, a_pl)
                b_payload_cold += count_tokens(enc, b_pl_cold)
                b_payload_warm += count_tokens(enc, assemble_payload(arm_b_warm, p))
                a_full += count_tokens(enc, f"{system_stub}\n\n{a_pl}")
                b_full_cold += count_tokens(enc, f"{system_stub}\n\n{b_pl_cold}")

            for k, v in (("a_ctx", a_ctx), ("b_ctx_cold", b_ctx_cold),
                         ("b_ctx_warm", b_ctx_warm), ("a_payload", a_payload),
                         ("b_payload_cold", b_payload_cold),
                         ("b_payload_warm", b_payload_warm),
                         ("a_full", a_full), ("b_full_cold", b_full_cold)):
                tot[k] += v

            docs_report.append({
                "fixture": f"fixtures/docs/{name}",
                "directives": [ev["directive"] for ev in events
                               if ev["kind"] in ("include", "memory")],
                "arm_a_context_tokens": a_ctx,
                "arm_b_context_tokens_cold": b_ctx_cold,
                "arm_b_context_tokens_warm": b_ctx_warm,
                "reduction_pct_context_cold": _reduction_pct(a_ctx, b_ctx_cold),
                "reduction_pct_context_warm": _reduction_pct(a_ctx, b_ctx_warm),
                "arm_a_payload_tokens_with_prompts": a_payload,
                "arm_b_payload_tokens_with_prompts_cold": b_payload_cold,
                "arm_b_payload_tokens_with_prompts_warm": b_payload_warm,
                "reduction_pct_with_prompts_cold": _reduction_pct(a_payload, b_payload_cold),
            })
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    result = {
        "benchmark": "tokenab",
        "issue": "https://github.com/Perseus-Computing-LLC/perseus/issues/804",
        "measured_question": (
            "For the same information need, how many prompt tokens does a "
            "request carry when context is assembled naively versus by "
            "Perseus's shipped defaults?"),
        "run": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "tokenizer": TOKENIZER,
            "tiktoken_version": getattr(tiktoken, "__version__", "unknown"),
            "perseus_version": (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip(),
            "repo_commit": commit,
            "repo_dirty": dirty,
            "cold_runs_per_doc": cold_runs,
            "warm_runs_per_doc": warm_runs,
            "user_prompt_count": len(prompts),
            "system_stub_tokens": stub_tokens,
            "system_stub_note": (
                "identical bytes in both arms; reported here and EXCLUDED "
                "from every reduction percentage"),
        },
        "docs": docs_report,
        "aggregate": {
            "arm_a_context_tokens": tot["a_ctx"],
            "arm_b_context_tokens_cold": tot["b_ctx_cold"],
            "arm_b_context_tokens_warm": tot["b_ctx_warm"],
            "reduction_pct_context_cold": _reduction_pct(tot["a_ctx"], tot["b_ctx_cold"]),
            "reduction_pct_context_warm": _reduction_pct(tot["a_ctx"], tot["b_ctx_warm"]),
            "arm_a_payload_tokens_with_prompts": tot["a_payload"],
            "arm_b_payload_tokens_with_prompts_cold": tot["b_payload_cold"],
            "arm_b_payload_tokens_with_prompts_warm": tot["b_payload_warm"],
            "reduction_pct_with_prompts_cold": _reduction_pct(tot["a_payload"], tot["b_payload_cold"]),
            "reduction_pct_with_prompts_warm": _reduction_pct(tot["a_payload"], tot["b_payload_warm"]),
            "full_request_tokens_incl_stub_arm_a": tot["a_full"],
            "full_request_tokens_incl_stub_arm_b_cold": tot["b_full_cold"],
            "headline": (
                "reduction_pct_with_prompts_cold: the full-request payload "
                "(context + user prompts, stub excluded), cold cache, the "
                "least favorable of the reported variants"),
        },
        "latency_ms": {
            "arm_b_render_cold": _latency_summary(cold_samples),
            "arm_b_render_warm": _latency_summary(warm_samples),
            "arm_a_assembly": _latency_summary(arm_a_samples),
            "note": (
                "arm B latency is the full `perseus render` subprocess, "
                "Python interpreter startup included, timed inside the "
                "measurement window; no sleeps, no stubs"),
        },
        "warnings": warnings,
        "limits": [
            "single-repo corpus: the Perseus repository itself; results on other corpora will differ",
            "arm A is a defined naive baseline (full-file concatenation with minimal headers), not a recorded production workload",
            "measures context-assembly token reduction only; says nothing about end-task accuracy",
            "since= windows are date-relative, so a rerun on a later date over the same commit can select different changelog sections",
            "shell-backed directives (@query, @services) are excluded: shipped defaults refuse shell execution, and counting a refused directive against full naive command output would credit Perseus for omitting information rather than compressing it",
            "the @memory pointer is the one arm B element with no arm A counterpart: the corpus has no memory files, so arm A gets zero tokens there and arm B pays for the pointer",
        ],
    }
    sig = hashlib.sha256(
        json.dumps(result, sort_keys=True).encode("utf-8")).hexdigest()
    result["signature_sha256"] = sig

    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    agg = result["aggregate"]
    print(f"tokenab report -> {out_path}")
    print(f"  commit {commit[:12]} dirty={dirty}")
    print(f"  arm A context tokens: {agg['arm_a_context_tokens']:,}")
    print(f"  arm B context tokens: {agg['arm_b_context_tokens_cold']:,} cold / "
          f"{agg['arm_b_context_tokens_warm']:,} warm")
    print(f"  reduction (context only): {agg['reduction_pct_context_cold']}% cold / "
          f"{agg['reduction_pct_context_warm']}% warm")
    print(f"  reduction (with prompts): {agg['reduction_pct_with_prompts_cold']}% cold / "
          f"{agg['reduction_pct_with_prompts_warm']}% warm")
    print(f"  render overhead cold: {result['latency_ms']['arm_b_render_cold']}")
    print(f"  render overhead warm: {result['latency_ms']['arm_b_render_warm']}")
    print(f"  signature_sha256: {sig}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cold-runs", type=int, default=3,
                    help="cold renders per doc, each with a fresh PERSEUS_HOME (default 3)")
    ap.add_argument("--warm-runs", type=int, default=3,
                    help="timed warm renders per doc after one untimed priming render (default 3)")
    ap.add_argument("--out", type=Path, default=HERE / "report.json",
                    help="report path (default benchmark/tokenab/report.json)")
    args = ap.parse_args()
    run(args.cold_runs, args.warm_runs, args.out)


if __name__ == "__main__":
    main()
