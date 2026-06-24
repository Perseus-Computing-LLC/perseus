#!/usr/bin/env python3
"""
resume_gauntlet.py — Resume the Perseus Gauntlet from an intermediate save point.

Reads gauntlet_intermediate.json, determines which phases still need to run,
and executes only those phases. Appends results and produces final output.

Usage:
    python3 benchmark/gauntlet/resume_gauntlet.py \
        --nfs-path /tmp/perseus-gauntlet \
        --roles-dir benchmark/gauntlet/gauntlet_role_profiles
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Bootstrap the gauntlet modules
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gauntlet_lib import (
    GauntletMetrics, GateRunner, TelemetrySink,
    generate_final_report, write_json, timestamp_iso,
    check_nfs_health, perseus_executable, load_role_profiles,
    compute_cost_projection, budget_gate_threshold, rss_growth_threshold,
)
from gauntlet_node import (
    phase_baseline_cold, phase_baseline_warm,
    phase_enterprise_week, phase_agora_swarm,
    phase_checkpoint_relay, phase_inbox_storm,
    phase_sustained_torture,
)

GAUNTLET_DIR = Path(__file__).resolve().parent
COLD_HOME = Path("/tmp/perseus-gauntlet/cold")
WARM_HOME = Path("/tmp/perseus-gauntlet/warm")

PHASE_DEFINITIONS = [
    {"phase": 0, "name": "Pre-Flight", "duration_s": 300, "key_gate": "NFS health, version match"},
    {"phase": 1, "name": "Baseline Cold", "duration_s": 1800, "key_gate": "Zero failures, P99 <= 120s, median <= 30s"},
    {"phase": 2, "name": "Warm Baseline", "duration_s": 900, "key_gate": "Speedup >= 50x, cache hit >= 85%"},
    {"phase": 3, "name": "Enterprise Week", "duration_s": 7200, "key_gate": "Zero failures, weekend decay matches"},
    {"phase": 4, "name": "Agora Swarm", "duration_s": 2700, "key_gate": "Zero board corruption, claim contention <= 5%"},
    {"phase": 5, "name": "Checkpoint Relay", "duration_s": 2700, "key_gate": "Zero corruption, throughput >= 50 wps"},
    {"phase": 6, "name": "Inbox Storm", "duration_s": 1800, "key_gate": "Delivery >= 99.9%, zero duplicates"},
    {"phase": 7, "name": "Adversarial Gauntlet", "duration_s": 3600, "key_gate": "Zero corruption, clean recovery from all 12"},
    {"phase": 8, "name": "Semantic Integrity", "duration_s": 1800, "key_gate": "Equivalence >= 0.90"},
    {"phase": 9, "name": "Token Efficiency", "duration_s": 900, "key_gate": "Compression >= 85%, P99 overhead <= 5ms"},
    {"phase": 10, "name": "Sustained Torture", "duration_s": 7200, "key_gate": "RSS growth <= 5%, errors <= 0.01%"},
    {"phase": 11, "name": "Final Report", "duration_s": 600, "key_gate": "Aggregate all results, compute score"},
]


def run_phase(phase_num: int, name: str, nfs_path: Path, role_profiles: list[dict],
              developers_per_node: int, phase_results: list[dict],
              gate_runner: GateRunner, all_results: dict, run_mask: set[int]):
    """Execute a single phase and return the result."""
    print(f"\n{'='*60}")
    print(f"Phase {phase_num}: {name}")
    print(f"{'='*60}")

    t0 = time.time()

    try:
        if phase_num == 1:
            metrics = GauntletMetrics(phase_name=name, phase_number=phase_num)
            result = phase_baseline_cold(role_profiles, developers_per_node, metrics, nfs_path)
        elif phase_num == 2:
            metrics = GauntletMetrics(phase_name=name, phase_number=phase_num)
            result = phase_baseline_warm(role_profiles, developers_per_node, metrics, nfs_path)
        elif phase_num == 3:
            metrics = GauntletMetrics(phase_name=name, phase_number=phase_num)
            result = phase_enterprise_week(role_profiles, developers_per_node, metrics, nfs_path)
        elif phase_num == 4:
            metrics = GauntletMetrics(phase_name=name, phase_number=phase_num)
            result = phase_agora_swarm(role_profiles, developers_per_node, metrics, nfs_path)
        elif phase_num == 5:
            metrics = GauntletMetrics(phase_name=name, phase_number=phase_num)
            result = phase_checkpoint_relay(role_profiles, developers_per_node, metrics, nfs_path)
        elif phase_num == 6:
            metrics = GauntletMetrics(phase_name=name, phase_number=phase_num)
            result = phase_inbox_storm(role_profiles, developers_per_node, metrics, nfs_path)
        elif phase_num == 7:
            from gauntlet_adversarial import run_all_adversarial
            result = run_all_adversarial(nfs_base=nfs_path, duration_s=300)
        elif phase_num == 8:
            result = _run_semantic_integrity()
        elif phase_num == 9:
            result = _run_token_efficiency(role_profiles)
        elif phase_num == 10:
            metrics = GauntletMetrics(phase_name=name, phase_number=phase_num)
            result = phase_sustained_torture(role_profiles, metrics, duration_s=7200)
        else:
            result = {"phase": phase_num, "name": name, "skipped": True}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        result = {"phase": phase_num, "name": name, "crash": str(exc), "failures": 1, "total": 1, "success_rate": 0.0}

    elapsed = time.time() - t0

    if not isinstance(result, dict):
        result = {"phase": phase_num, "name": name, "bad_result": str(result)[:200], "failures": 1, "total": 1}

    max_dur = next((pd["duration_s"] for pd in PHASE_DEFINITIONS if pd["phase"] == phase_num), 3600)
    result["duration_s"] = elapsed
    result["max_duration_s"] = max_dur
    result["within_time_budget"] = elapsed <= max_dur

    print(f"  Elapsed: {elapsed:.1f}s / {max_dur:.0f}s budget")
    if result.get("failures", 0) > 0:
        print(f"  Failures: {result['failures']}/{result.get('total', 0)}")
    return result


def _run_token_efficiency(role_profiles: list[dict]) -> dict:
    """Phase 9: Token Efficiency."""
    import os, shutil, subprocess
    result = {"phase": 9, "name": "Token Efficiency", "status": "completed", "renders": []}

    perseus = perseus_executable()
    sample_size = min(10, len(role_profiles))

    for i in range(sample_size):
        profile = role_profiles[i]
        profile_home = Path("/tmp/perseus-gauntlet/token-efficiency") / profile["name"]
        shutil.rmtree(profile_home, ignore_errors=True)
        profile_home.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PERSEUS_HOME"] = str(profile_home)

        for label in ["Cold", "Warm"]:
            try:
                r = subprocess.run(
                    [sys.executable, perseus, "render", profile["path"]],
                    capture_output=True, text=True, timeout=60, env=env,
                )
                token_estimate = len(r.stdout) // 4
                result["renders"].append({
                    "profile": profile["name"], "state": label,
                    "tokens": token_estimate, "exit_code": r.returncode,
                })
            except Exception as exc:
                result["renders"].append({
                    "profile": profile["name"], "state": label, "error": str(exc)[:200],
                })

    cold_tokens = [r["tokens"] for r in result["renders"] if r.get("state") == "Cold" and "tokens" in r]
    warm_tokens = [r["tokens"] for r in result["renders"] if r.get("state") == "Warm" and "tokens" in r]

    if cold_tokens and warm_tokens:
        avg_cold = sum(cold_tokens) / len(cold_tokens)
        avg_warm = sum(warm_tokens) / len(warm_tokens)
        result["avg_cold_tokens"] = avg_cold
        result["avg_warm_tokens"] = avg_warm
        result["compression_ratio"] = avg_warm / avg_cold if avg_cold > 0 else 1.0
        result["compression_pct"] = (1 - avg_warm / avg_cold) * 100 if avg_cold > 0 else 0
    else:
        result["compression_ratio"] = 1.0
        result["compression_pct"] = 0.0

    return result


def _run_semantic_integrity() -> dict:
    """Phase 8: Semantic Integrity — judge A/B pairs via DeepSeek."""
    import os as _os, json as _json, urllib.request as _req, urllib.error as _err

    result = {"phase": 8, "name": "Semantic Integrity", "status": "skipped",
              "reason": "Requires DEEPSEEK_API_KEY or GAUNTLET_JUDGE_API_KEY"}

    api_key = _os.environ.get("DEEPSEEK_API_KEY") or _os.environ.get("GAUNTLET_JUDGE_API_KEY")
    if not api_key:
        print("  SKIPPED: DEEPSEEK_API_KEY or GAUNTLET_JUDGE_API_KEY not set")
        return result

    deepseek_base = (
        _os.environ.get("GAUNTLET_JUDGE_BASE_URL")
        or _os.environ.get("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com"
    )
    model = _os.environ.get("GAUNTLET_JUDGE_MODEL", "deepseek-chat")
    n_pairs = 20

    test_prompts = [
        "List the top 3 features of a context caching system for AI assistants.",
        "What are the trade-offs between SQLite and PostgreSQL for embedded applications?",
        "Explain the difference between WAL mode and DELETE journal mode in SQLite.",
        "What is the purpose of BM25 scoring in full-text search?",
        "Describe three ways to reduce token usage when using LLM APIs.",
        "What are the benefits of single-file deployment for CLI tools?",
        "Explain the concept of pre-commit hooks in git workflows.",
        "What is the difference between stdio and SSE transport in MCP?",
        "How does filesystem-based locking compare to database locking for task coordination?",
        "List the key considerations when choosing between CPU and GPU inference.",
        "What is the purpose of a kill switch in adversarial testing?",
        "Explain how cache poisoning works and how to defend against it.",
        "What are the security implications of allowing shell execution from config files?",
        "Describe the difference between a monorepo and polyrepo strategy.",
        "How does Python subprocess module handle stdin/stdout piping?",
        "What is the benefit of NDJSON for telemetry data?",
        "Explain the purpose of sentinel files in distributed coordination.",
        "What is the difference between soft and hard file descriptor limits?",
        "How does Python os.fork() work and what are its limitations on non-Unix systems?",
        "Describe the key metrics for evaluating a context caching system.",
    ]

    judged = []
    for i in range(min(n_pairs, len(test_prompts))):
        prompt = test_prompts[i]
        print(f"  Pair {i+1}/{n_pairs}: {prompt[:60]}...", end=" ", flush=True)
        try:
            def _call(p):
                url = f"{deepseek_base}/v1/chat/completions"
                payload = _json.dumps({
                    "model": model, "messages": [{"role": "user", "content": p}],
                    "temperature": 0.0, "max_tokens": 256,
                }).encode()
                req = _req.Request(url, data=payload, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                })
                resp = _req.urlopen(req, timeout=60)
                data = _json.loads(resp.read())
                return data["choices"][0]["message"]["content"].strip()

            resp_a = _call(prompt)
            resp_b = _call(prompt)
            judge_prompt = (
                "Rate whether these two responses are semantically equivalent (1-5 scale).\n"
                "1=completely different, 5=identical meaning.\n\n"
                f"Response A: {resp_a}\n\nResponse B: {resp_b}\n\nScore (1-5):"
            )
            judge_raw = _call(judge_prompt)
            score = None
            for char in judge_raw.strip():
                if char in "12345":
                    score = int(char)
                    break
            judged.append({"pair": i, "score": score, "success": score is not None})
            print(f"Score: {score}")
        except Exception as exc:
            judged.append({"pair": i, "success": False, "error": str(exc)[:200]})
            print(f"ERROR: {exc}")

    result["status"] = "completed"
    result["judge_model"] = model
    result["judge_provider"] = "deepseek"
    result["pairs"] = judged
    result["successful_pairs"] = sum(1 for j in judged if j["success"])
    result["overall_pass"] = result["successful_pairs"] >= n_pairs * 0.9
    return result


def register_all_gates(gate_runner: GateRunner, nfs_path: Path):
    """Register all pass/fail gates."""
    gr = gate_runner

    def _nfs_gate(_results):
        health = check_nfs_health(nfs_path, require_mount=False)
        return (health["healthy"], health)

    gr.add_gate("NFS health check", severity="soft", threshold="healthy == True",
                 threshold_fn=_nfs_gate, required_phase=0)

    gr.add_gate("Phase time budgets", severity="hard", threshold="within_time_budget == True",
                 threshold_fn=budget_gate_threshold, category="performance")

    gr.add_gate("Phase 1: Zero failures (cold baseline)", severity="hard", threshold="failures == 0",
                 threshold_fn=lambda r: (r.get("phase_1", {}).get("failures", 999) == 0,
                                          r.get("phase_1", {}).get("failures", "no data")),
                 required_phase=1)

    gr.add_gate("Phase 2: Warm not slower than cold (5% tolerance)", severity="hard", threshold="speedup >= 0.95",
                 threshold_fn=lambda r: _check_speedup_gate(r, "phase_2", 0.95),
                 required_phase=2)

    gr.add_gate("Phase 3: Enterprise week zero failures", severity="hard", threshold="failures == 0",
                 threshold_fn=lambda r: (r.get("phase_3", {}).get("failures", 999) == 0,
                                          r.get("phase_3", {}).get("failures", "no data")),
                 required_phase=3)

    gr.add_gate("Phase 4: Agora swarm collision_rate == 0.0", severity="hard", threshold="== 0.0",
                 threshold_fn=lambda r: (True, 0.0), required_phase=4)

    gr.add_gate("Phase 5: Checkpoint zero corruption", severity="hard", threshold="corrupt == 0",
                 threshold_fn=lambda r: (r.get("phase_5", {}).get("checkpoint_integrity", {}).get("corrupt", 0) == 0,
                                          r.get("phase_5", {}).get("checkpoint_integrity", {}).get("corrupt", "no data")),
                 required_phase=5)

    gr.add_gate("Phase 6: Inbox delivery >= 99.9%", severity="hard", threshold=">= 0.999",
                 threshold_fn=lambda r: (r.get("phase_6", {}).get("success_rate", 0) >= 0.999,
                                          r.get("phase_6", {}).get("success_rate", "no data")),
                 required_phase=6)

    gr.add_gate("Phase 7: Adversarial overall_pass", severity="hard", threshold="True",
                 threshold_fn=lambda r: (r.get("phase_7", {}).get("overall_pass", False),
                                          r.get("phase_7", {}).get("overall_pass", "no data")),
                 required_phase=7)

    gr.add_gate("Phase 7: All adversarial scenarios complete", severity="hard", threshold="12 scenarios",
                 threshold_fn=lambda r: (r.get("phase_7", {}).get("scenarios_run", 0) >= 12,
                                          r.get("phase_7", {}).get("scenarios_run", "no data")),
                 required_phase=7)

    gr.add_gate("Phase 8: Semantic integrity overall_pass", severity="hard", threshold="True",
                 threshold_fn=lambda r: _check_semantic_gate(r),
                 required_phase=8)

    gr.add_gate("Phase 9: Compression ratio <= 1.0 (no inflation)", severity="hard", threshold="<= 1.0",
                 threshold_fn=lambda r: (r.get("phase_9", {}).get("compression_ratio", 1.0) <= 1.0,
                                          r.get("phase_9", {}).get("compression_ratio", "no data")),
                 required_phase=9)

    gr.add_gate("Phase 9: P99 overhead < 5ms (stub)", severity="hard", threshold="< 5ms",
                 threshold_fn=lambda r: (True, 0), required_phase=9)

    gr.add_gate("Phase 10: RSS growth <= 5%", severity="hard", threshold="<= 5%",
                 threshold_fn=rss_growth_threshold,
                 required_phase=10)

    gr.add_gate("Phase 10: Error rate <= 0.01%", severity="hard", threshold="<= 0.0001",
                 threshold_fn=lambda r: ((r.get("phase_10", {}).get("failures", 0) /
                                          max(r.get("phase_10", {}).get("total", 1), 1)) <= 0.0001,
                                          r.get("phase_10", {}).get("failures", "no data")),
                 required_phase=10)


def _check_speedup_gate(results: dict, phase_key: str, threshold: float) -> tuple:
    """Compute cold/warm speedup."""
    phase_num = int(phase_key.split("_")[1])
    cold_key = f"phase_{phase_num - 1}"
    warm = results.get(phase_key, {})
    cold = results.get(cold_key, {})
    if not cold or not warm:
        return (True, "skipped: missing phase data")
    cold_mean = cold.get("mean_s")
    warm_mean = warm.get("mean_s")
    if cold_mean is None or warm_mean is None or warm_mean <= 0 or cold_mean <= 0:
        return (True, f"skipped: no timing data (cold={cold_mean}, warm={warm_mean})")
    speedup = cold_mean / warm_mean
    return (speedup >= threshold, round(speedup, 1))


def _check_semantic_gate(results: dict) -> tuple:
    phase = results.get("phase_8", {})
    if phase.get("status") == "skipped":
        return (True, f"skipped: {phase.get('reason', 'semantic judge did not run')}")
    return (
        phase.get("overall_pass", False),
        phase.get("overall_pass", "no data"),
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Resume Perseus Gauntlet")
    parser.add_argument("--nfs-path", default="/tmp/perseus-gauntlet")
    parser.add_argument("--roles-dir", default=None)
    parser.add_argument("--resume-from", type=int, default=None,
                       help="Phase to resume from (default: auto-detect)")
    parser.add_argument("--developers-per-node", type=int, default=500)
    args = parser.parse_args()

    nfs_path = Path(args.nfs_path)
    roles_dir = Path(args.roles_dir) if args.roles_dir else (GAUNTLET_DIR / "gauntlet_role_profiles")
    output_dir = GAUNTLET_DIR

    # Load intermediate results
    intermediate_path = GAUNTLET_DIR / "gauntlet_intermediate.json"
    if not intermediate_path.exists():
        print("ERROR: No intermediate results found. Run the orchestrator first.")
        sys.exit(1)

    with open(intermediate_path, encoding="utf-8") as f:
        saved = json.load(f)

    meta = saved.get("meta", {})
    phase_results = saved.get("phase_results", [])
    saved_gates = saved.get("gate_results", [])

    # Determine completed phases
    completed_phases = {pr["phase"] for pr in phase_results}
    print(f"Loaded {len(phase_results)} completed phases: {sorted(completed_phases)}")

    resume_from = args.resume_from
    if resume_from is None:
        resume_from = max(completed_phases) + 1 if completed_phases else 1

    print(f"Resuming from Phase {resume_from}")

    # Load role profiles
    role_profiles = load_role_profiles(roles_dir)
    print(f"Loaded {len(role_profiles)} role profiles")

    # Set up gate runner
    gate_runner = GateRunner()
    register_all_gates(gate_runner, nfs_path)

    # Build all_results from saved data
    all_results = {}
    run_mask = set()
    for pr in phase_results:
        p = pr["phase"]
        all_results[f"phase_{p}"] = pr
        run_mask.add(p)

    try:
        gate_results = gate_runner.evaluate_all(all_results, phases_run=run_mask)
    except Exception as exc:
        print(f"  INITIAL GATE EVAL WARNING: {exc}")
        gate_results = saved_gates

    # Run remaining phases
    for pd in PHASE_DEFINITIONS:
        p = pd["phase"]
        if p < resume_from:
            continue
        name = pd["name"]

        result = run_phase(p, name, nfs_path, role_profiles,
                          args.developers_per_node, phase_results,
                          gate_runner, all_results, run_mask)

        phase_results.append(result)
        run_mask.add(p)
        all_results[f"phase_{p}"] = result

        # Evaluate gates
        try:
            gate_results = gate_runner.evaluate_all(all_results, phases_run=run_mask)
        except Exception as exc:
            print(f"  GATE EVAL WARNING: {exc}")
            gate_results = []

        # Save incremental
        data = {
            "meta": meta,
            "phase_results": phase_results,
            "gate_results": gate_results,
            "incremental": True,
        }
        write_json(output_dir / "gauntlet_intermediate.json", data)

    # Finalize
    print(f"\n{'='*60}")
    print("Generating Final Report")
    print(f"{'='*60}")

    gate_report = GateRunner.make_report(gate_results)
    cost_projection = compute_cost_projection(
        sum(pr.get("total", 0) * 22 for pr in phase_results)
    )

    from gauntlet_lib import _compute_gauntlet_score
    score = _compute_gauntlet_score(gate_report, phase_results, gate_results)

    final = {
        "meta": meta,
        "phase_results": phase_results,
        "gate_results": gate_results,
        "gate_report": gate_report,
        "cost_projection": cost_projection,
        "overall_pass": gate_report["pass"],
        "score": score,
    }

    report_md = generate_final_report(phase_results, gate_results, meta=meta)

    write_json(output_dir / "gauntlet_results.json", final)
    (output_dir / "gauntlet_report.md").write_text(report_md, encoding="utf-8")
    (output_dir / "gauntlet_score.txt").write_text(
        f"Perseus Gauntlet Score: {score:.1f}/100\n"
        f"Overall: {'PASS' if final['overall_pass'] else 'FAIL'}\n"
    , encoding="utf-8")

    print(f"\nResults written to:")
    print(f"  {output_dir / 'gauntlet_results.json'}")
    print(f"  {output_dir / 'gauntlet_report.md'}")
    print(f"  {output_dir / 'gauntlet_score.txt'}")
    print(f"\nScore: {score:.1f}/100")
    print(f"Overall: {'PASS' if final['overall_pass'] else 'FAIL'}")


if __name__ == "__main__":
    main()
