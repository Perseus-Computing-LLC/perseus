#!/usr/bin/env python3
"""Pinned-task context-assembly comparison (#962 evaluation).

Three assembly modes on a frozen synthetic task set:

* **direct**   — every record stuffed into context (uniform stuffing baseline);
* **linear**   — every record uniformly summarized to a fixed window
                 (linear-summary baseline, AGoT adoption guidance);
* **dag**      — selective, budgeted DAG compilation via
                 ``perseus.compile_context_dag`` with a deterministic
                 relevance/uncertainty-aware fetcher.

Metrics per task per arm: rendered tokens (``dag_tokens``, chars//4 — an
*estimate*, not provider billing), gold-fact coverage, and for the DAG arm the
terminal verdict + replay digest determinism. The tight-budget task
(``budget-07``) documents the fail-closed budget rejection path.

**Claim discipline.** Coverage is a *synthetic reference*: fixture-derived
fact presence, not model accuracy. Token numbers are *derived* estimates.
Nothing here establishes provider-run efficacy — that belongs to the
Context-Bench run (#961), which uses this instrumented assembly path.

Run from the repo root:  python3 benchmark/context_dag/run.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

import perseus  # noqa: E402  (single-file built artifact)

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(HERE, "dataset.json")
RESULTS = os.path.join(HERE, "results.json")
REPORT = os.path.join(HERE, "report.md")

LINEAR_WINDOW = 70


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def linear_summary(text: str, window: int = LINEAR_WINDOW) -> str:
    """Uniform deterministic summary: head + tail of a fixed window."""
    if len(text) <= window:
        return text
    half = window // 2
    return text[:half] + " … " + text[-half:]


def coverage(facts, packet_text: str) -> float:
    """Synthetic-reference fact coverage: fraction of facts present verbatim."""
    if not facts:
        return 1.0
    return round(sum(1 for f in facts if f in packet_text) / len(facts), 3)


def direct_arm(task) -> dict:
    text = task["question"] + " " + " ".join(r["text"] for r in task["records"])
    return {
        "mode": "direct",
        "tokens": perseus.dag_tokens(text),
        "coverage": coverage(task["facts"], text),
        "records": len(task["records"]),
    }


def linear_arm(task) -> dict:
    text = task["question"] + " " + " ".join(
        linear_summary(r["text"]) for r in task["records"])
    return {
        "mode": "linear",
        "tokens": perseus.dag_tokens(text),
        "coverage": coverage(task["facts"], text),
        "records": len(task["records"]),
    }


def _node_for(rec: dict) -> perseus.ContextNode:
    kind = rec.get("kind", "retrieved_record")
    ev = {"validity": rec.get("validity", "observed"),
          "verified": bool(rec.get("verified", True)),
          "source_ids": [f"fixture:{rec['id']}"]}
    if kind == "contradiction" and rec.get("resolved_by"):
        ev["resolved_by"] = rec["resolved_by"]
    if kind == "policy_constraint" and rec.get("policy_ref"):
        ev["policy_ref"] = rec["policy_ref"]
    return perseus.ContextNode(kind=kind, content=rec["text"], evidence=ev)


def make_fetch(task):
    """Deterministic relevance/uncertainty-aware fetcher.

    Includes a record when it is relevant (>= 0.5), carries uncertain validity
    (inferred/stale), is unverified, or is a contradiction/policy node.
    Only the root requirement triggers fetching — deeper nodes return nothing.
    """

    def fetch(node):
        if node.kind != "requirement":
            return []
        out = []
        for r in task["records"]:
            kind = r.get("kind", "retrieved_record")
            if kind in ("contradiction", "policy_constraint"):
                out.append(_node_for(r))
                continue
            rel = float(r.get("relevance", 0.0))
            val = r.get("validity", "observed")
            if rel >= 0.5 or val in ("inferred", "stale") or \
                    not bool(r.get("verified", True)):
                out.append(_node_for(r))
        return out

    return fetch


def dag_arm(task) -> dict:
    budget_cfg = task.get("budget") or {}
    budget = perseus.CompilationBudget(
        max_nodes=len(task["records"]) + 2,
        max_depth=2,
        max_fanout=len(task["records"]) + 1,
        max_tokens=int(budget_cfg.get("max_tokens", 100000)),
        deadline_s=float(budget_cfg.get("deadline_s", 30.0)),
    )
    root = perseus.ContextNode(
        kind="requirement", content=task["question"],
        evidence={"validity": "observed", "verified": True,
                  "source_ids": [f"task:{task['task_id']}"]})
    try:
        artifact = perseus.compile_context_dag(
            task_id=task["task_id"], root=root, fetch=make_fetch(task),
            budget=budget, verdict_hint="sufficient",
            created_by="perseus-context-dag-bench",
            meta={"bench_schema": "perseus-context-dag-bench/v1"})
    except perseus.BudgetExceeded as exc:
        return {
            "mode": "dag",
            "outcome": "budget_rejected",
            "budget_kind": exc.kind,
            "tokens": None,
            "coverage": None,
        }
    packet_text = " ".join(p["content"] for p in artifact["packet"])
    check = perseus.verify_compiled_dag(artifact)
    replay = perseus.compile_context_dag(
        task_id=task["task_id"], root=root, fetch=make_fetch(task),
        budget=budget, verdict_hint="sufficient",
        created_by="perseus-context-dag-bench",
        meta={"bench_schema": "perseus-context-dag-bench/v1"})
    return {
        "mode": "dag",
        "outcome": "compiled",
        "tokens": artifact["budget"]["tokens"],
        "coverage": coverage(task["facts"], packet_text),
        "verdict": artifact["verdict"]["verdict"],
        "verdict_reason": artifact["verdict"]["reason"],
        "nodes": artifact["budget"]["nodes"],
        "depth": artifact["budget"]["depth"],
        "verified_artifact": check["valid"],
        "replay_deterministic":
            replay["compiled_digest"] == artifact["compiled_digest"],
    }


def main() -> None:
    with open(DATASET, encoding="utf-8") as f:
        dataset = json.load(f)
    tasks = dataset["tasks"]

    rows = []
    for task in tasks:
        direct = direct_arm(task)
        linear = linear_arm(task)
        dag = dag_arm(task)
        base = direct["tokens"] or 1
        rows.append({
            "task_id": task["task_id"],
            "question": task["question"],
            "facts": task["facts"],
            "direct": direct,
            "linear": linear,
            "dag": dag,
            "reduction_linear_pct": round(
                (1 - (linear["tokens"] or 0) / base) * 100, 1),
            "reduction_dag_pct":
                None if dag["tokens"] is None else round(
                    (1 - dag["tokens"] / base) * 100, 1),
        })

    completed = [r for r in rows if r["dag"].get("outcome") == "compiled"]
    agg = {
        "tasks": len(rows),
        "budget_rejected": sum(
            1 for r in rows if r["dag"].get("outcome") == "budget_rejected"),
        "mean_tokens": {
            mode: round(sum(r[mode]["tokens"] for r in completed) / len(completed), 1)
            for mode in ("direct", "linear", "dag")
        },
        "mean_coverage": {
            mode: round(sum(r[mode]["coverage"] for r in completed) / len(completed), 3)
            for mode in ("direct", "linear", "dag")
        },
        "mean_reduction_pct": {
            mode: round(sum((r[f"reduction_{mode}_pct"] or 0.0)
                            for r in completed) / len(completed), 1)
            for mode in ("linear", "dag")
        },
        "dag_verdicts": {
            v: sum(1 for r in completed if r["dag"]["verdict"] == v)
            for v in ("sufficient", "abstain", "escalate")
        },
        "replay_deterministic_all":
            all(r["dag"]["replay_deterministic"] for r in completed),
        "verified_artifact_all":
            all(r["dag"]["verified_artifact"] for r in completed),
    }
    results = {
        "schema_version": "perseus-context-dag-bench-results/v1",
        "claims": {
            "coverage": "synthetic reference: fixture-derived fact presence, "
                        "not model accuracy",
            "tokens": "derived: dag_tokens estimate (chars//4), not provider "
                      "billing",
            "generalization": "not established: deterministic synthetic "
                              "fixture only",
        },
        "aggregate": agg,
        "rows": rows,
    }
    payload = json.dumps(results, indent=2, sort_keys=True)
    with open(RESULTS, "w", encoding="utf-8") as f:
        f.write(payload + "\n")
    results["results_digest"] = _sha(payload)
    with open(RESULTS, "w", encoding="utf-8") as f:
        f.write(json.dumps(results, indent=2, sort_keys=True) + "\n")

    _write_report(results)
    print(json.dumps(results["aggregate"], indent=2, sort_keys=True))
    print("results_digest:", results["results_digest"])


def _write_report(results: dict) -> None:
    agg = results["aggregate"]
    lines = [
        "# Context-assembly comparison — pinned tasks (direct vs linear vs DAG)",
        "",
        "Evaluation for perseus#962 (auditable context-compilation DAG). "
        "Deterministic, provider-free run over a frozen synthetic task set.",
        "",
        "**Claim discipline:** coverage is a *synthetic reference* "
        "(fixture-derived fact presence, not model accuracy). Token numbers "
        "are *derived* estimates (``dag_tokens``, chars//4) — not provider "
        "billing. Generalization to provider runs is **not established** by "
        "this benchmark; that is the scope of the Context-Bench run (#961).",
        "",
        "## Aggregate (excluding the budget-rejection task)",
        "",
        f"- tasks: {agg['tasks']}, budget-rejected: {agg['budget_rejected']} "
        f"(fail-closed budget enforcement)",
        f"- replay deterministic: {agg['replay_deterministic_all']}",
        f"- artifact verification: {agg['verified_artifact_all']}",
        "",
        "| mode | mean tokens | mean coverage | mean reduction vs direct |",
        "|---|---:|---:|---:|",
    ]
    for mode, label in (("direct", "direct (stuff all)"),
                        ("linear", "linear (uniform summaries)"),
                        ("dag", "dag (selective + budgeted)")):
        red = agg["mean_reduction_pct"].get(mode)
        lines.append(
            f"| {label} | {agg['mean_tokens'][mode]} | "
            f"{agg['mean_coverage'][mode]} | "
            f"{'—' if red is None else f'{red}%'} |")
    lines += [
        "",
        "DAG terminal verdicts: " + ", ".join(
            f"{k}={v}" for k, v in sorted(agg["dag_verdicts"].items())),
        "",
        "## Per-task rows",
        "",
        "| task | direct tok / cov | linear tok / cov | dag tok / cov | "
        "dag verdict | reduction |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for r in results["rows"]:
        d = r["direct"]
        ln = r["linear"]
        g = r["dag"]
        if g["tokens"] is None:
            dag_cell = f"rejected ({g['budget_kind']})"
            verdict = "—"
            red = "—"
        else:
            dag_cell = f"{g['tokens']} / {g['coverage']}"
            verdict = g["verdict"]
            red = f"{r['reduction_dag_pct']}%"
        lines.append(
            f"| {r['task_id']} | {d['tokens']} / {d['coverage']} | "
            f"{ln['tokens']} / {ln['coverage']} | {dag_cell} | "
            f"{verdict} | {red} |")
    lines += [
        "",
        "## Findings",
        "",
        "- **Selective DAG assembly carries fewer tokens than stuffing while "
        "preserving fixture fact coverage** where the gold facts ride on "
        "relevant/uncertain records (arcade-01, clinic-02, org-04, chain-06).",
        "- **Uniform linear summaries lose mid-text facts** by construction "
        "(head+tail window); the DAG keeps full record text for the records "
        "it selects.",
        "- **Relevance-thresholded selection can drop a low-relevance needle "
        "(needle-03).** This is the documented trade-off of selective "
        "assembly: token savings versus recall. In production the terminal "
        "evaluator's abstain path plus an external coverage signal is the "
        "control for this failure mode; that loop is out of scope for this "
        "deterministic fixture.",
        "- **Unresolved contradictions escalate** (escalate-05) — the DAG "
        "refuses to silently ship conflicting records.",
        "- **Budgets fail closed** (budget-07): the run is rejected with "
        "``BudgetExceeded`` rather than truncated.",
        "- **Every compiled artifact verifies and replays deterministically** "
        "(digest-stable across repeated compiles).",
        "",
        "## Reproduce",
        "",
        "```",
        "python3 benchmark/context_dag/run.py",
        "```",
        "",
        f"results digest: `{results['results_digest']}`",
        "",
    ]
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
