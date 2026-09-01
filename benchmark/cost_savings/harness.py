#!/usr/bin/env python3
"""Verifiable cost-savings benchmark: Perseus+Vault vs full-context stuffing,
dollar-metered through the Perseus Ledger, accuracy-gated (#749).

Two arms, identical task set, identical pinned answerer+judge, both metered
into a Perseus Ledger via ``ledger_agent.metering.record_usage``:

- ``fullcontext``  — every question gets the whole haystack (baseline).
- ``vault``        — Perseus Vault hybrid recall, top-k (the product arm).

The arms are produced by the vault's content-hashed LongMemEval QA harness
(``perseus-vault/benchmark/longmemeval/qa.py --systems fullcontext vault``) —
the same official-judge methodology behind the published accuracy numbers —
so the savings figure and the accuracy gate come from ONE run under ONE
config. Dollars come from the Perseus Ledger (``spend_by(dimension=
"workspace")``), not hand math: each answer/judge call is metered as a usage
event tagged with its arm, and the report reads the ledger back.

Modes:
  --mode mock   (default) free: qa.py --mock-llm — real ingest + retrieval +
                real per-question prompt-token counts, stub LLM. Dollars are
                estimates (token counts x the Perseus Ledger price table); accuracy
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

Report: ``cost_savings_report.json`` — per-arm Ledger dollars, tokens,
events, accuracy, savings %, full config, and a content hash over the
result set. The Perseus Ledger itself is left on disk next to the report
(``ledger.db``) so the numbers can be independently re-queried.
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

try:
    from .contract import qa_display_content_hash, qa_display_payload
except ImportError:  # direct execution: python benchmark/cost_savings/harness.py
    from contract import qa_display_content_hash, qa_display_payload

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
    for rel in (f"target/release/perseus-vault{exe}", f"target/release/vault{exe}"):
        p = vault_repo / rel
        if p.exists():
            return p
    sys.exit("no release perseus-vault binary found; build one or pass --bin")


ARM_WORKSPACE = {"fullcontext": "baseline-fullcontext", "vault": "perseus-vault"}


def _validated_usage(usage: object, label: str) -> dict[str, int]:
    """Validate provider/journal token counts without coercing malformed data."""
    if not isinstance(usage, dict):
        raise ValueError(f"{label} usage must be an object")
    result: dict[str, int] = {}
    for field in ("prompt_tokens", "completion_tokens"):
        value = usage.get(field)
        if type(value) is not int or value < 0:
            raise ValueError(f"{label}.{field} must be a non-negative integer")
        result[field] = value
    return result


def _validate_journal_totals(
    counts: dict[str, dict[str, int]], qa_projection: dict, mode: str
) -> None:
    """Require the journal's metered/skipped rows to cover validated QA exactly."""
    events_per_graded_record = 2 if mode == "live" else 1
    for system in ARM_WORKSPACE:
        qa_system = qa_projection["systems"][system]
        expected_events = qa_system["n_graded"] * events_per_graded_record
        expected_skipped = qa_system["n_attempted"] - qa_system["n_graded"]
        if (counts[system]["events"] != expected_events
                or counts[system]["skipped"] != expected_skipped):
            raise ValueError(
                f"journal totals for {system} do not match validated QA counts "
                f"(events {counts[system]['events']}/{expected_events}, "
                f"skipped {counts[system]['skipped']}/{expected_skipped})"
            )


def _prepare_journal(
    journal: Path, mode: str
) -> tuple[
    dict[str, dict[str, int]],
    list[tuple[str, list[tuple[str, dict[str, int], str]]]],
    dict[tuple[str, str], str],
]:
    """Parse and validate a journal before importing or writing to the Ledger."""
    if mode not in ("mock", "live"):
        raise ValueError("journal mode must be 'mock' or 'live'")
    counts = {arm: {"events": 0, "skipped": 0} for arm in ARM_WORKSPACE}
    prepared: list[tuple[str, list[tuple[str, dict[str, int], str]]]] = []
    identities: dict[tuple[str, str], str] = {}
    with open(journal, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if not isinstance(rec, dict):
                raise ValueError("journal records must be JSON objects")
            if "_config" in rec:
                continue
            system = rec.get("system")
            if system not in ARM_WORKSPACE:
                continue
            question_id = rec.get("question_id")
            question_type = rec.get("question_type")
            if (not isinstance(question_id, str) or not question_id
                    or not isinstance(question_type, str) or not question_type):
                raise ValueError("journal question identity is malformed")
            identity = (system, question_id)
            if identity in identities:
                raise ValueError("journal contains duplicate question/system rows")
            identities[identity] = question_type
            if rec.get("error") is not None:
                if mode == "live":
                    raise ValueError(
                        "live journal contains an errored record; refusing to under-meter"
                    )
                counts[system]["skipped"] += 1
                continue
            if mode == "live":
                calls = [
                    ("answer", _validated_usage(rec.get("ans_usage"), "ans_usage"), "api"),
                    ("judge", _validated_usage(rec.get("judge_usage"), "judge_usage"), "api"),
                ]
            else:
                calls = [
                    ("answer", _validated_usage({
                        "prompt_tokens": rec.get("tokens_est"),
                        "completion_tokens": 0,
                    }, "tokens_est"), "estimate")
                ]
            prepared.append((system, calls))
    return counts, prepared, identities


def meter_journal(conn, org_id: str, journal: Path, mode: str,
                  answer_model: str, judge_model: str,
                  expected_questions: dict[tuple[str, str], str] | None = None) -> dict:
    """Meter every graded qa.py journal record into the Perseus Ledger.

    live: provider-billed ans_usage/judge_usage per call (source='api').
    mock: the journal's real prompt-token estimate per answer call
          (source='estimate', output 0, judge skipped — the stub judge makes
          no API call and reports no usage).
    Returns counters for the report.
    """
    counts, prepared, identities = _prepare_journal(journal, mode)
    if expected_questions is not None and identities != expected_questions:
        raise ValueError("journal question identities do not match validated QA")
    from ledger_agent import metering

    for system, calls in prepared:
        ws = ARM_WORKSPACE[system]
        for call_kind, usage, source in calls:
            model = answer_model if call_kind == "answer" else judge_model
            res = metering.record_usage(
                conn, org_id, provider="openai",
                input_tokens=usage["prompt_tokens"],
                output_tokens=usage["completion_tokens"],
                model=model, task_type="longmemeval-qa",
                workspace=ws, source=source,
            )
            if not res.recorded:
                sys.exit(f"ledger_agent dropped a usage event ({res}); "
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
    ap.add_argument("--tpm", type=int, default=None,
                    help="live mode: tokens/min pacing passed to qa.py "
                         "(set to your provider tier's limit)")
    ap.add_argument("--yes", action="store_true",
                    help="live mode: skip qa.py's cost confirmation")
    ap.add_argument("--skip-qa", action="store_true",
                    help="reuse an existing journal in --outdir (re-meter only)")
    args = ap.parse_args()

    try:
        from ledger_agent import db as pdb
        from ledger_agent import metering, pricing
    except ImportError:
        sys.exit("pip install perseus-ledger (the meter this harness reports from)")

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
               "--data", args.data, "--systems", "fullcontext", "vault",
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
            if args.tpm:
                cmd += ["--tpm", str(args.tpm)]
        print(f"[1/3] running qa.py ({args.mode}, {args.limit} questions, "
              f"k={args.k}) ...", flush=True)
        rc = subprocess.run(cmd, cwd=str(qa.parent)).returncode
        if rc != 0:
            sys.exit(f"qa.py exited {rc}")

    report = json.loads(qa_report.read_text(encoding="utf-8"))
    try:
        qa_projection = qa_display_payload(report)
    except (TypeError, ValueError) as exc:
        sys.exit(f"qa.py produced an invalid report: {exc}")
    if qa_projection["mock_llm"] != (args.mode == "mock"):
        sys.exit("qa.py report mode does not match the harness mode")
    if qa_projection["retrieval"]["k"] != args.k:
        sys.exit("qa.py report retrieval k does not match the harness --k")
    answer_model = qa_projection["answerer_model"]
    judge_model = qa_projection["judge_model"]

    # ── 2. meter every call into a fresh Perseus Ledger ──────────────────────
    ledger_path = outdir / "ledger.db"
    if ledger_path.exists():
        ledger_path.unlink()
    conn = pdb.connect(ledger_path)
    pdb.init_schema(conn)
    org = pdb.create_org(conn, "costsave-bench", tier="enterprise")
    org_id = org["id"]
    print(f"[2/3] metering journal into the Perseus Ledger ({ledger_path.name}) ...",
          flush=True)
    expected_questions = {
        (row["system"], row["question_id"]): row["question_type"]
        for row in qa_projection["per_question"]
    }
    counts = meter_journal(conn, org_id, journal, args.mode,
                           answer_model, judge_model, expected_questions)

    # ── 3. read the dollars BACK from the ledger and gate on accuracy ───────
    by_ws = {row["key"]: row for row in metering.spend_by(conn, org_id, "workspace")}
    events_per_graded_record = 2 if args.mode == "live" else 1
    try:
        _validate_journal_totals(counts, qa_projection, args.mode)
    except ValueError as exc:
        sys.exit(str(exc))
    arms = {}
    for system, ws in ARM_WORKSPACE.items():
        ledger = by_ws.get(ws, {"cost": 0.0, "tokens": 0, "events": 0})
        qa_system = qa_projection["systems"][system]
        expected_events = qa_system["n_graded"] * events_per_graded_record
        if ledger["events"] != expected_events:
            sys.exit(
                f"ledger totals for {system} do not match validated QA counts "
                f"(events {ledger['events']}/{expected_events})"
            )
        arms[system] = {
            "workspace": ws,
            "ledger_cost_usd": round(ledger["cost"], 6),
            "ledger_tokens": ledger["tokens"],
            "ledger_events": ledger["events"],
            "metered_records": counts[system]["events"],
            "errored_records_unmetered": counts[system]["skipped"],
            "accuracy": qa_system["accuracy"],
            "n_graded": qa_system["n_graded"],
        }

    base, ours = arms["fullcontext"], arms["vault"]
    savings_pct = (100.0 * (base["ledger_cost_usd"] - ours["ledger_cost_usd"])
                   / base["ledger_cost_usd"]) if base["ledger_cost_usd"] else None
    acc_delta = (None if base["accuracy"] is None or ours["accuracy"] is None
                 else round(ours["accuracy"] - base["accuracy"], 4))

    result = {
        "benchmark": "perseus-vault-cost-savings (#749)",
        "record_status": "run_record",
        "mode": args.mode,
        "accuracy_grading": ("official LongMemEval per-type judge" if args.mode == "live"
                              else "mock judge (plumbing/estimate mode — do NOT quote)"),
        "dollars": ("provider-billed tokens x Perseus Ledger price table"
                     if args.mode == "live" else
                     "estimated prompt tokens x Perseus Ledger price table (input side only)"),
        "price_table_as_of": pricing.PRICE_TABLE_AS_OF,
        "answerer_model": answer_model,
        "judge_model": judge_model,
        "answer_prompt": qa_projection["answer_prompt"],
        "k": qa_projection["retrieval"]["k"],
        "n_questions": qa_projection["n_instances"],
        "dataset": qa_projection["dataset"],
        "arms": arms,
        "savings_pct": None if savings_pct is None else round(savings_pct, 2),
        "accuracy_delta": acc_delta,
        "qa_report": qa_report.name,
        "qa_content_hash_sha256": qa_projection["producer_content_hash_sha256"],
        "qa_display_content_hash_sha256": qa_display_content_hash(report),
        "ledger_db": ledger_path.name,
        "ledger_db_retained": True,
    }
    content_hash = hashlib.sha256(
        json.dumps(result, sort_keys=True).encode("utf-8")).hexdigest()
    result["content_hash_sha256"] = content_hash

    out = outdir / "cost_savings_report.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\n[3/3] cost-savings report -> {out}")
    print(f"  arm             $ (ledger)   tokens      events  accuracy")
    for system in ("fullcontext", "vault"):
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
    print(f"  content hash: {content_hash[:16]}...")


if __name__ == "__main__":
    main()
