#!/usr/bin/env python3
"""Bounded, offline replay of Vault recall through the real MCP binary."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DATASET = HERE / "dataset.json"
LOAD_BEARING = {"constraint", "contradiction", "correction", "keystone", "policy", "prohibition"}


def load_dataset(path=DATASET):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_corpus(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_probes(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def probe_database_paths(workdir, count):
    return [Path(workdir) / f"probe-{index:03d}.db" for index in range(count)]


def probe_replay_signature(report):
    """Return the stable measurement signature, excluding Vault-generated IDs."""
    rows = []
    for row in report["probes"]["rows"]:
        rows.append({
            "probe_id": row["probe_id"],
            "target": row["target"],
            "rank": row["rank"],
            "hit_at_5": row["hit_at_5"],
            "production": row["production"],
            "legacy": row["legacy"],
        })
    payload = {
        "benchmark": report["benchmark"],
        "version": report["version"],
        "binary": report["binary"],
        "budget_chars": report["budget_chars"],
        "corpus": report["corpus"],
        "rows": rows,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def load_perseus():
    import importlib.util

    artifact = REPO / "perseus.py"
    spec = importlib.util.spec_from_file_location("perseus_real_vault_density", artifact)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def find_binary(explicit=None):
    candidates = [explicit, os.environ.get("PERSEUS_VAULT_BIN")]
    candidates += [
        "/opt/data/benchmark-bin/v2.22.0/perseus-vault",
        "/opt/data/perseus-vault/target/release/perseus-vault",
        str(REPO.parent / "perseus-vault" / "target" / "release" / "perseus-vault"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


class VaultMCP:
    def __init__(self, binary, db):
        self.proc = subprocess.Popen(
            [binary, "--db", str(db)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            bufsize=1,
        )
        self._next_id = 0
        self._send({
            "jsonrpc": "2.0", "id": self._new_id(), "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "real-vault-density", "version": "1"}},
        })
        self._read()
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    def _send(self, message):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def _read(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                stderr = self.proc.stderr.read()[:1000]
                raise RuntimeError(f"Vault MCP closed stdout: {stderr}")
            message = json.loads(line)
            if "result" in message or "error" in message:
                return message

    def call(self, name, arguments):
        request_id = self._new_id()
        self._send({
            "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        response = self._read()
        if "error" in response:
            raise RuntimeError(response["error"])
        result = response.get("result", {})
        if result.get("isError"):
            text = result.get("content", [{}])[0].get("text", "Vault tool error")
            raise RuntimeError(text)
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        text = result.get("content", [{}])[0].get("text", "{}")
        return json.loads(text) if isinstance(text, str) else text

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=5)


def _tokens(text):
    return max(1, max(len(text) // 4, int(len(text.split()) * 1.33 + 0.5))) if text else 0


def _legacy_budget(items, budget):
    selected = []
    spent = 0
    for item in sorted(items, key=lambda x: x["relevance"], reverse=True):
        if spent + len(item["content"]) <= budget:
            selected.append(item)
            spent += len(item["content"])
        elif not selected:
            selected.append({**item, "content": item["content"][:max(1, budget - 2)].rstrip() + "…"})
            break
    return selected, []


def _production_budget(perseus, items, budget):
    hits = []
    for item in items:
        hits.append(perseus.MemoryHit(
            id=item["id"], category=item["category"], key=item["key"],
            content=item["content"], summary=item["content"], relevance=item["relevance"],
            external_refs=item.get("external_refs", []),
            why_served={"source_evidence_ids": item.get("source_evidence_ids", [])},
        ))
    selected, diagnostics = perseus.apply_recall_budget(hits, budget)
    return [{"id": hit.id, "content": hit.content} for hit in selected], diagnostics


def evaluate_case(perseus, case, vault_items):
    vault_by_address = {f"{x['category']}/{x['key']}": x for x in vault_items}
    items = []
    for spec in case["items"]:
        recalled = vault_by_address[f"{spec['category']}/{spec['key']}"]
        items.append({**recalled, "relevance": spec["relevance"]})
    production, diagnostics = _production_budget(perseus, items, case["budget_chars"])
    legacy, _ = _legacy_budget(items, case["budget_chars"])
    required = case["required_facts"]
    load_ids = set(case["load_bearing_ids"])
    decoder_ids = {
        f"{ref.get('category')}/{ref.get('key')}"
        for ref in diagnostics.get("decoder_refs", []) if isinstance(ref, dict)
    }
    def score(rows, decoder):
        text = "\n".join(x["content"] for x in rows)
        selected_ids = {row["id"] for row in rows}
        selected_addresses = {
            f"{item['category']}/{item['key']}"
            for item in items if item["id"] in selected_ids
        }
        recovered = set(decoder) | selected_addresses
        return {
            "task_resumption": float(all(f.lower() in text.lower() for f in required)),
            "load_bearing_retention": float(load_ids <= recovered),
            "decoder_recovery": float(load_ids <= recovered),
            "prompt_tokens": _tokens(text),
            "uncompressed_tokens": _tokens("\n".join(x["content"] for x in items)),
        }
    return {
        "case_id": case["id"],
        "vault_recalled_ids": [x["id"] for x in vault_items],
        "production": score(production, decoder_ids),
        "legacy": score(legacy, set()),
    }


def evaluate_corpus_case(perseus, items, budget):
    """Measure coverage and decoder recovery for a many-item corpus case."""
    hits = [perseus.MemoryHit(
        id=item["id"], category=item["category"], key=item["key"],
        content=item["content"], summary=item["content"], relevance=item["relevance"],
    ) for item in items]
    selected, diagnostics = perseus.apply_recall_budget(hits, budget)
    selected_ids = {item.id for item in selected}
    decoder_refs = {
        ref.get("id") for ref in diagnostics.get("decoder_refs", [])
        if isinstance(ref, dict)
    }
    all_ids = {item["id"] for item in items}
    production = {
        "task_resumption": 1.0,
        "load_bearing_retention": 1.0,
        "decoder_recovery": float((all_ids - selected_ids) <= decoder_refs),
        "selected_item_fraction": round(len(selected_ids) / len(all_ids), 4),
        "omitted_item_count": len(all_ids - selected_ids),
        "decoder_coverage": float((all_ids - selected_ids) <= decoder_refs),
        "prompt_tokens": _tokens("\n".join(item.content for item in selected)),
        "uncompressed_tokens": _tokens("\n".join(item["content"] for item in items)),
    }
    legacy_selected, _ = _legacy_budget(items, budget)
    legacy_ids = {item["id"] for item in legacy_selected}
    legacy = {
        "task_resumption": 1.0,
        "load_bearing_retention": 1.0,
        "decoder_recovery": 0.0,
        "selected_item_fraction": round(len(legacy_ids) / len(all_ids), 4),
        "omitted_item_count": len(all_ids - legacy_ids),
        "decoder_coverage": 0.0,
        "prompt_tokens": _tokens("\n".join(item["content"] for item in legacy_selected)),
        "uncompressed_tokens": production["uncompressed_tokens"],
    }
    return {"production": production, "legacy": legacy}


def evaluate_probe(probe, recalled, perseus, budget=160):
    """Evaluate one gold probe against Vault recall plus serving budget."""
    addresses = [f"{item.get('category', '')}/{item.get('key', '')}" for item in recalled]
    target = f"{probe['category']}/{probe['key']}"
    rank = addresses.index(target) + 1 if target in addresses else None
    items = [{**item, "relevance": 1.0 / (index + 1)} for index, item in enumerate(recalled)]
    selected, diagnostics = _production_budget(perseus, items, budget)
    legacy, _ = _legacy_budget(items, budget)
    required = probe["required_terms"]
    target_id = next((item["id"] for item in recalled if f"{item.get('category', '')}/{item.get('key', '')}" == target), None)
    decoder_ids = {ref.get("id") for ref in diagnostics.get("decoder_refs", []) if isinstance(ref, dict)}

    def score(rows, decoder_ids):
        text = "\n".join(item["content"] for item in rows)
        row_ids = {item["id"] for item in rows}
        target_visible = target_id is not None and target_id in row_ids
        task_resumption = float(target_visible and all(term.lower() in text.lower() for term in required))
        return {
            "task_resumption": task_resumption,
            "decoder_coverage": float(target_id is not None and not target_visible and target_id in decoder_ids),
            "selected_item_fraction": round(len(row_ids) / max(1, len(items)), 4),
            "prompt_tokens": _tokens(text),
            "uncompressed_tokens": _tokens("\n".join(item["content"] for item in items)),
        }

    return {
        "probe_id": probe["id"],
        "target": target,
        "rank": rank,
        "hit_at_5": rank is not None and rank <= 5,
        "production": score(selected, decoder_ids),
        "legacy": score(legacy, set()),
    }


def summarize_probes(rows):
    count = len(rows)
    return {
        "count": count,
        "hit_at_5": round(sum(row["hit_at_5"] for row in rows) / count, 4),
        "mrr": round(sum(1 / row["rank"] if row["rank"] else 0 for row in rows) / count, 4),
        "production_task_resumption": round(sum(row["production"]["task_resumption"] for row in rows) / count, 4),
        "production_decoder_coverage": round(sum(row["production"]["decoder_coverage"] for row in rows) / count, 4),
        "legacy_task_resumption": round(sum(row["legacy"]["task_resumption"] for row in rows) / count, 4),
        "legacy_decoder_coverage": round(sum(row["legacy"]["decoder_coverage"] for row in rows) / count, 4),
    }


def build_probe_report(rows, binary, corpus_items, budget_chars=160):
    production = summarize_probes(rows)
    legacy = {
        key: production[key.replace("production_", "legacy_")]
        for key in ("production_task_resumption", "production_decoder_coverage")
    }
    report = {
        "benchmark": "perseus-real-vault-semantic-probes",
        "version": 1,
        "real_vault": True,
        "offline": True,
        "network_calls": 0,
        "measurement_only": True,
        "binary": Path(binary).name,
        "budget_chars": budget_chars,
        "corpus": {"items": corpus_items},
        "probes": {"count": len(rows), "summary": production, "rows": rows},
        "methods": {
            "production": {
                "task_resumption": production["production_task_resumption"],
                "decoder_coverage": production["production_decoder_coverage"],
            },
            "legacy": {
                "task_resumption": production["legacy_task_resumption"],
                "decoder_coverage": production["legacy_decoder_coverage"],
            },
        },
        "gate": {"pass": None},
    }
    report["probe_replay_signature"] = probe_replay_signature(report)
    return finalize_report(report)


def _average(rows, method):
    keys = ("task_resumption", "load_bearing_retention", "decoder_recovery", "prompt_tokens", "uncompressed_tokens")
    return {key: round(sum(row[method][key] for row in rows) / len(rows), 4) for key in keys}


def _report_signature_payload(report):
    return {key: value for key, value in report.items() if key != "signature_sha256"}


def finalize_report(report):
    report = dict(report)
    report["signature_sha256"] = hashlib.sha256(
        json.dumps(_report_signature_payload(report), sort_keys=True).encode()
    ).hexdigest()
    return report


def verify_report_signature(report):
    expected = report.get("signature_sha256")
    if not isinstance(expected, str):
        return False
    actual = hashlib.sha256(
        json.dumps(_report_signature_payload(report), sort_keys=True).encode()
    ).hexdigest()
    return actual == expected


def build_report(rows, binary):
    production = _average(rows, "production")
    legacy = _average(rows, "legacy")
    report = {
        "benchmark": "perseus-real-vault-semantic-density",
        "version": 1,
        "real_vault": True,
        "offline": True,
        "network_calls": 0,
        "binary": Path(binary).name,
        "case_results": rows,
        "methods": {"production": production, "legacy": legacy},
        "vault": {"cases_replayed": len(rows)},
        "corpus": {"items": len(rows)},
        "gate": {"pass": all(production[key] == 1.0 for key in ("task_resumption", "load_bearing_retention", "decoder_recovery"))},
    }
    return finalize_report(report)


def run_benchmark(binary, workdir):
    perseus = load_perseus()
    dataset = load_dataset(DATASET)
    db = Path(workdir) / "vault-replay.db"
    vault = VaultMCP(binary, db)
    try:
        for case in dataset["cases"]:
            for item in case["items"]:
                body = {"content": item["content"], "summary": item["content"]}
                vault.call("perseus_vault_remember", {
                    "category": item["category"], "key": item["key"],
                    "body_json": json.dumps(body), "type": "insight",
                    "skip_dedup": True,
                    "external_refs": item.get("external_refs", []),
                })
        rows = []
        for case in dataset["cases"]:
            recalled = vault.call("perseus_vault_recall", {"query": "", "limit": 100, "mode": "fts5", "trust_weight": 0, "min_decay": 0})
            rows.append(evaluate_case(perseus, case, recalled.get("items", [])))
        return build_report(rows, binary)
    finally:
        vault.close()


def build_corpus_dataset(corpus):
    """Shape sanitized items into one bounded, deterministic replay case."""
    items = corpus.get("items", [])
    if not items:
        raise ValueError("sanitized corpus contains no content-bearing items")
    return {
        "offline": True,
        "cases": [{
            "id": "sanitized-corpus",
            "query": "",
            "budget_chars": 160,
            "items": [
                {"category": item["category"], "key": item["key"],
                 "content": item["content"],
                 "relevance": 1.0 - index / max(1, len(items))}
                for index, item in enumerate(items[:24])
            ],
            "required_facts": [], "load_bearing_ids": [],
        }],
        "corpus_item_count": min(len(items), 24),
    }


def run_corpus_benchmark(binary, corpus_path, workdir):
    """Replay a sanitized Vault corpus through the real MCP binary."""
    dataset = build_corpus_dataset(json.loads(Path(corpus_path).read_text(encoding="utf-8")))
    perseus = load_perseus()
    db = Path(workdir) / "vault-replay.db"
    vault = VaultMCP(binary, db)
    try:
        case = dataset["cases"][0]
        for item in case["items"]:
            vault.call("perseus_vault_remember", {
                "category": item["category"], "key": item["key"],
                "body_json": json.dumps({"content": item["content"], "summary": item["content"]}),
                "type": "insight", "skip_dedup": True,
            })
        recalled = vault.call("perseus_vault_recall", {
            "query": "", "limit": 1000, "mode": "fts5", "trust_weight": 0, "min_decay": 0,
        })
        recalled_by_address = {
            f"{item['category']}/{item['key']}": item
            for item in recalled.get("items", [])
        }
        replay_items = [
            {**recalled_by_address[f"{item['category']}/{item['key']}"],
             "relevance": item["relevance"]}
            for item in case["items"]
        ]
        metrics = evaluate_corpus_case(perseus, replay_items, case["budget_chars"])
        row = {
            "case_id": case["id"],
            "vault_recalled_ids": [item["id"] for item in recalled.get("items", [])],
            **metrics,
        }
        report = build_report([row], binary)
        report["corpus"] = {"items": dataset["corpus_item_count"], "format": "perseus-sanitized-replay-v1"}
        return finalize_report(report)
    finally:
        vault.close()


def run_probe_benchmark(binary, corpus_path, probes_path, workdir, budget=640):
    """Replay a sanitized corpus and evaluate fixed, auditable gold probes."""
    corpus = load_corpus(corpus_path)
    probes = load_probes(probes_path)
    if not probes:
        raise ValueError("probe manifest is empty")
    perseus = load_perseus()
    rows = []
    for probe_index, probe in enumerate(probes):
        vault = VaultMCP(binary, probe_database_paths(workdir, len(probes))[probe_index])
        try:
            for item in corpus.get("items", []):
                vault.call("perseus_vault_remember", {
                    "category": item["category"], "key": item["key"],
                    "body_json": json.dumps({"content": item["content"], "summary": item.get("summary", "")}),
                    "type": "insight", "skip_dedup": True,
                })
            recalled = vault.call("perseus_vault_recall", {
                "query": probe["query"], "limit": 1000, "mode": "fts5", "trust_weight": 0,
                "skip_side_effects": True, "min_decay": 0,
            })
            rows.append(evaluate_probe(probe, recalled.get("items", []), perseus, budget))
        finally:
            vault.close()
    return build_probe_report(
        rows,
        binary,
        corpus_items=len(corpus.get("items", [])),
        budget_chars=budget,
    )


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", default=None)
    parser.add_argument("--out", default=str(HERE / "results.json"))
    parser.add_argument("--corpus", default=None, help="Sanitized corpus JSON to replay")
    parser.add_argument("--probes", default=None, help="Gold probe manifest to evaluate against --corpus")
    args = parser.parse_args(argv)
    binary = find_binary(args.bin)
    if not binary:
        parser.error("perseus-vault binary not found; pass --bin or set PERSEUS_VAULT_BIN")
    with tempfile.TemporaryDirectory(prefix="perseus-vault-density-") as tmp:
        if args.probes and not args.corpus:
            parser.error("--probes requires --corpus")
        report = (run_probe_benchmark(binary, args.corpus, args.probes, Path(tmp))
                  if args.probes else run_corpus_benchmark(binary, args.corpus, Path(tmp))
                  if args.corpus else run_benchmark(binary, Path(tmp)))
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.probes:
        summary = report["probes"]["summary"]
        print(f"real Vault probes: {summary['count']} probes, network_calls=0")
        print(f"production: hit@5={summary['hit_at_5']:.4f} mrr={summary['mrr']:.4f} task={summary['production_task_resumption']:.4f} decoder={summary['production_decoder_coverage']:.4f}")
        print(f"measurement-only report -> {args.out}")
        return 0
    p = report["methods"]["production"]
    print(f"real Vault density: {report['vault']['cases_replayed']} cases, network_calls=0")
    print(f"production: resumption={p['task_resumption']:.4f} load_bearing={p['load_bearing_retention']:.4f} decoder={p['decoder_recovery']:.4f}")
    print(f"gate: {'PASS' if report['gate']['pass'] else 'FAIL'} -> {args.out}")
    return 0 if report["gate"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
