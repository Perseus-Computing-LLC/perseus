#!/usr/bin/env python3
"""Verifiable cost-savings benchmark: Perseus+Vault vs full-context stuffing,
dollar-metered through the Plutus ledger, accuracy-gated (#749).

Two arms, identical task set, identical pinned answerer+judge, both metered
into a Plutus ledger via ``plutus_agent.metering.record_usage``:

- ``fullcontext``  — every question gets the whole haystack (baseline).
- ``mimir``        — Perseus Vault hybrid recall, top-k (the product arm).

The arms are produced by the vault's signed LongMemEval QA harness
(``perseus-vault/benchmark/longmemeval/qa.py --systems fullcontext mimir``) —
the same official-judge methodology behind the published accuracy numbers —
so the savings figure and the accuracy gate come from ONE run under ONE
config. Dollars come from the Plutus ledger (``spend_by(dimension=
"workspace")``), not hand math: each answer/judge call is metered as a usage
event tagged with its arm, and the report reads the ledger back.

Modes:
  --mode mock   (default) free: qa.py --mock-llm — real ingest + retrieval +
                real per-question prompt-token counts, stub LLM. Dollars are
                estimates (token counts x the Plutus price table); accuracy
                is mock-graded. This is the plumbing smoke AND the free
                savings estimator.
  --mode live   paid: provider-billed token usage (ans_usage/judge_usage from
                the qa journal) metered per call; accuracy is the official
                LongMemEval judge. Costs real money — qa.py prints the
                estimate and requires confirmation unless --yes.

Usage (from a checkout that has perseus-vault as a sibling, or set
PERSEUS_VAULT_REPO):

  python benchmark/cost_savings/harness.py \
      --data ~/lme-data/longmemeval_s_cleaned.json --limit 10 --mode mock

Report: ``cost_savings_report.json`` — per-arm ledger dollars, tokens,
events, accuracy, savings %, full config, and a sha256 signature over the
result set. The Plutus ledger itself is left on disk next to the report
(``plutus_ledger.db``) so the numbers can be independently re-queried.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def find_qa() -> Path:
    """Locate perseus-vault's qa.py: $PERSEUS_VAULT_REPO, then siblings."""
    cands = []
    env = os.environ.get("PERSEUS_VAULT_REPO")
    if env:
        cands.append(Path(env))
    repo_root = HERE.parent.parent
    cands += [repo_root.parent / "perseus-vault", Path.home() / "perseus-vault"]
    for c in cands:
        qa = c / "benchmark" / "longmemeval" / "qa.py"
        if qa.exists():
            return qa
    sys.exit("perseus-vault checkout not found (set PERSEUS_VAULT_REPO); "
             f"looked in: {[str(c) for c in cands]}")


def find_binary(explicit: str | None, vault_repo: Path) -> Path:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        sys.exit(f"--bin {explicit} does not exist")
    exe = ".exe" if os.name == "nt" else ""
    for rel in (f"target/release/perseus-vault{exe}", f"target/release/mimir{exe}"):
        p = vault_repo / rel
        if p.exists():
            return p
    sys.exit("no release perseus-vault binary found; build one or pass --bin")


ARM_WORKSPACE = {"fullcontext": "baseline-fullcontext", "mimir": "perseus-vault"}


def meter_journal(conn, org_id: str, journal: Path, mode: str,
                  answer_model: str, judge_model: str) -> dict:
    """Meter every graded qa.py journal record into the Plutus ledger.

    live: provider-billed ans_usage/judge_usage per call (source='api').
    mock: the journal's real prompt-token estimate per answer call
          (source='estimate', output 0, judge skipped — the stub judge makes
          no API call and reports no usage).
    Returns counters for the report.
    """
    from plutus_agent import metering

    counts = {arm: {"events": 0, "skipped": 0} for arm in ARM_WORKSPACE}
    with open(journal, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if "_config" in rec:
                continue
            system = rec.get("system")
            if system not in ARM_WORKSPACE or rec.get("error") is not None:
                if system in ARM_WORKSPACE:
                    counts[system]["skipped"] += 1
                continue
            ws = ARM_WORKSPACE[system]
            calls = []
            if mode == "live":
                if rec.get("ans_usage"):
                    calls.append((answer_model, rec["ans_usage"], "api"))
                if rec.get("judge_usage"):
                    calls.append((judge_model, rec["judge_usage"], "api"))
            else:
                calls.append((answer_model,
                              {"prompt_tokens": rec.get("tokens_est", 0),
                               "completion_tokens": 0},
                              "estimate"))
            for model, usage, source in calls:
                res = metering.record_usage(
                    conn, org_id, provider="openai",
                    input_tokens=int(usage.get("prompt_tokens", 0)),
                    output_tokens=int(usage.get("completion_tokens", 0)),
                    model=model, task_type="longmemeval-qa",
                    workspace=ws, source=source,
                )
                if not res.recorded:
                    sys.exit(f"plutus dropped a usage event ({res}); "
                             "ledger would understate spend — aborting")
                counts[system]["events"] += 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, help="LongMemEval dataset json")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--cot", action="store_true",
                    help="use the official CoT answer prompt (live mode)")
    ap.add_argument("--mode", choices=("mock", "live"), default="mock")
    ap.add_argument("--bin", default=None, help="perseus-vault binary")
    ap.add_argument("--outdir", default=str(HERE / "out"))
    ap.add_argument("--yes", action="store_true",
                    help="live mode: skip qa.py's cost confirmation")
    ap.add_argument("--skip-qa", action="store_true",
                    help="reuse an existing journal in --outdir (re-meter only)")
    args = ap.parse_args()

    try:
        from plutus_agent import db as pdb
        from plutus_agent import metering, pricing
    except ImportError:
        sys.exit("pip install plutus-agent (the meter this harness reports from)")

    qa = find_qa()
    vault_repo = qa.parent.parent.parent
    binary = find_binary(args.bin, vault_repo)
    # Absolute: qa.py runs with cwd at its own checkout, so relative paths
    # would resolve there, not here.
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    journal = outdir / f"qa_journal_{args.mode}.jsonl"
    qa_report = outdir / f"qa_report_{args.mode}.json"

    # ── 1. produce both arms with the vault's signed harness ────────────────
    if not args.skip_qa:
        if journal.exists():
            journal.unlink()
        cmd = [sys.executable, "-X", "utf8", str(qa),
               "--data", args.data, "--systems", "fullcontext", "mimir",
               "--k", str(args.k), "--limit", str(args.limit),
               "--bin", str(binary), "--journal", str(journal),
               "--out", str(qa_report), "--outdir", str(outdir)]
        if args.mode == "mock":
            cmd.append("--mock-llm")
        else:
            if args.cot:
                cmd.append("--cot")
            if args.yes:
                cmd.append("--yes")
        print(f"[1/3] running qa.py ({args.mode}, {args.limit} questions, "
              f"k={args.k}) ...", flush=True)
        rc = subprocess.run(cmd, cwd=str(qa.parent)).returncode
        if rc != 0:
            sys.exit(f"qa.py exited {rc}")

    report = json.loads(qa_report.read_text(encoding="utf-8"))
    answer_model = report.get("answerer_model", "gpt-4o-2024-08-06")
    judge_model = report.get("judge_model", answer_model)

    # ── 2. meter every call into a fresh Plutus ledger ──────────────────────
    ledger_path = outdir / "plutus_ledger.db"
    if ledger_path.exists():
        ledger_path.unlink()
    conn = pdb.connect(ledger_path)
    pdb.init_schema(conn)
    org = pdb.create_org(conn, "costsave-bench", tier="enterprise")
    org_id = org["id"]
    print(f"[2/3] metering journal into the Plutus ledger ({ledger_path.name}) ...",
          flush=True)
    counts = meter_journal(conn, org_id, journal, args.mode,
                           answer_model, judge_model)

    # ── 3. read the dollars BACK from the ledger and gate on accuracy ───────
    by_ws = {row["key"]: row for row in metering.spend_by(conn, org_id, "workspace")}
    systems = report.get("systems", {})
    arms = {}
    for system, ws in ARM_WORKSPACE.items():
        ledger = by_ws.get(ws, {"cost": 0.0, "tokens": 0, "events": 0})
        sysrep = systems.get(system, {})
        arms[system] = {
            "workspace": ws,
            "ledger_cost_usd": round(ledger["cost"], 6),
            "ledger_tokens": ledger["tokens"],
            "ledger_events": ledger["events"],
            "metered_records": counts[system]["events"],
            "errored_records_unmetered": counts[system]["skipped"],
            "accuracy": sysrep.get("accuracy"),
            "n_graded": sysrep.get("n_graded"),
        }

    base, ours = arms["fullcontext"], arms["mimir"]
    savings_pct = (100.0 * (base["ledger_cost_usd"] - ours["ledger_cost_usd"])
                   / base["ledger_cost_usd"]) if base["ledger_cost_usd"] else None
    acc_delta = (None if base["accuracy"] is None or ours["accuracy"] is None
                 else round(ours["accuracy"] - base["accuracy"], 4))

    result = {
        "benchmark": "perseus-vault-cost-savings (#749)",
        "mode": args.mode,
        "accuracy_grading": ("official LongMemEval per-type judge" if args.mode == "live"
                              else "mock judge (plumbing/estimate mode — do NOT quote)"),
        "dollars": ("provider-billed tokens x Plutus price table"
                     if args.mode == "live" else
                     "estimated prompt tokens x Plutus price table (input side only)"),
        "price_table_as_of": pricing.PRICE_TABLE_AS_OF,
        "answerer_model": answer_model,
        "judge_model": judge_model,
        "answer_prompt": report.get("answer_prompt", "plain"),
        "k": args.k,
        "n_questions": args.limit,
        "dataset": Path(args.data).name,
        "arms": arms,
        "savings_pct": None if savings_pct is None else round(savings_pct, 2),
        "accuracy_delta": acc_delta,
        "qa_report": qa_report.name,
        "qa_signature_sha256": report.get("signature_sha256"),
        "plutus_ledger": ledger_path.name,
    }
    sig = hashlib.sha256(
        json.dumps(result, sort_keys=True).encode("utf-8")).hexdigest()
    result["signature_sha256"] = sig

    out = outdir / "cost_savings_report.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\n[3/3] cost-savings report -> {out}")
    print(f"  arm             $ (ledger)   tokens      events  accuracy")
    for system in ("fullcontext", "mimir"):
        a = arms[system]
        acc = "n/a" if a["accuracy"] is None else f"{a['accuracy'] * 100:.1f}%"
        print(f"  {system:<15} ${a['ledger_cost_usd']:<11.4f} "
              f"{a['ledger_tokens']:<11,} {a['ledger_events']:<7} {acc}")
    if savings_pct is not None:
        print(f"\n  Perseus+Vault spends {savings_pct:.1f}% fewer dollars "
              f"(accuracy delta {acc_delta:+.4f})" if acc_delta is not None else "")
    if args.mode == "mock":
        print("  [mock mode: dollars are estimates, accuracy is stub-graded — "
              "run --mode live for quotable numbers]")
    print(f"  signature: {sig[:16]}...")


if __name__ == "__main__":
    main()
