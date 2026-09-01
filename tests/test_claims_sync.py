"""Keep current public HTML synchronized with the structured claims registry."""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))["claims"]

CANONICAL_PUBLIC = [
    "index.html",
    "context-engine/index.html",
    "vault/index.html",
    "ledger/index.html",
    "security/index.html",
    "benchmarks/index.html",

    "benchmarks/memconflict/index.html",
    "docs/index.html",
    "demo/index.html",
    "government/index.html",
    "government/capability-statement.html",
    "vault/mcp-reference/index.html",
]

SURFACE_CHECKS = [
    ("docs/index.html", "perseus_pypi_version"),
    ("context-engine/index.html", "perseus_pypi_version"),
    ("docs/index.html", "vault_version"),
    ("vault/index.html", "vault_version"),
    ("docs/index.html", "ledger_version"),
    ("ledger/index.html", "ledger_version"),
    ("benchmarks/index.html", "longmemeval_retrieval_recall10"),
    ("benchmarks/memconflict/index.html", "memconflict_macro"),
]

FORBIDDEN = [
    "94%",
    "488 → 27",
    "488->27",
    "0 ms P99",
    "1,190",
    "98,732",
    "PyPI v1.0.27",
    "SAM active",
    "Active — All Awards",
    "Email Thomas",
    # Deprecated LongMemEval answerer/judge claims; the current public metric
    # is the offline session-level retrieval lane.
    "73.8%",
    "80.9%",
    "official-CoT",
]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_canonical_values_are_present_on_owned_surfaces():
    for path, claim_id in SURFACE_CHECKS:
        value = str(CLAIMS[claim_id]["value"])
        assert value in read(path), f"{path} drifted from claims.json:{claim_id}={value}"


def test_retired_or_unqualified_claims_are_absent_from_canonical_public_html():
    combined = "\n".join(read(path) for path in CANONICAL_PUBLIC)
    generator = (ROOT / "scripts" / "build_public_site.py").read_text(encoding="utf-8")
    assert "signed report" not in generator.lower()
    assert "signed scale report" not in generator.lower()
    for token in FORBIDDEN:
        assert token not in combined, f"retired or unqualified public token returned: {token}"


def test_unpublishable_claims_do_not_leak_to_canonical_public_html():
    combined = "\n".join(read(path) for path in CANONICAL_PUBLIC)
    for claim_id, claim in CLAIMS.items():
        if claim.get("publishable", True):
            continue
        if claim.get("label") == "internal" or claim.get("status") == "source-release-candidate":
            continue
        value = claim.get("value")
        if not value:
            continue
        value = str(value)
        if value.isdigit():
            present = re.search(rf"(?<![0-9A-Za-z_.:-]){re.escape(value)}(?![0-9A-Za-z_.:%-])", combined)
        else:
            present = value in combined
        assert not present, f"unpublishable claim leaked: {claim_id}={value}"


def test_source_candidate_and_published_package_are_separate_claims():
    assert CLAIMS["perseus_version"]["status"] == "source-release-candidate"
    assert CLAIMS["perseus_version"]["publishable"] is False
    assert CLAIMS["perseus_pypi_version"]["status"] == "release"
    assert CLAIMS["perseus_pypi_version"]["value"] == "1.0.26"


def test_capability_statement_uses_publishable_retrieval_claim(tmp_path):
    generator = (ROOT / "scripts" / "build_capability_statement.py").read_text(encoding="utf-8")
    assert 'CLAIMS["longmemeval_retrieval_recall10"]' in generator
    assert 'CLAIMS["longmemeval_cot"]' not in generator

    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        pytest.skip("pdftotext is unavailable")
    pdf = ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement.pdf"
    result = subprocess.run(
        [pdftotext, str(pdf), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "99.8% recall@10" in result.stdout
    for retired in ("80.9%", "73.8%", "official-CoT", "1,213/1,500"):
        assert retired not in result.stdout


def test_dated_cost_savings_surface_is_explicitly_historical():
    generator = (ROOT / "benchmark" / "cost_savings" / "one_pager.py").read_text(encoding="utf-8")
    outputs = [
        (ROOT / "benchmark" / "cost_savings" / "results" / "ONE-PAGER.md").read_text(encoding="utf-8"),
        (ROOT / "benchmark" / "cost_savings" / "results" / "historical-one-pager.html").read_text(encoding="utf-8"),
        (ROOT / "benchmark" / "cost_savings" / "results" / "RESULTS.md").read_text(encoding="utf-8"),
    ]
    assert "historical" in generator.lower()
    assert all("historical" in output.lower() for output in outputs)
    for stale in (
        "latest paired confirmation is 82.0%",
        "not yet cryptographically tamper-evident",
        "signed reports",
        "independently re-queryable",
        "shipped ledger file",
        "cost-savings certification results",
    ):
        assert stale not in generator.lower()
        assert all(stale not in output.lower() for output in outputs)


def test_cost_savings_reports_use_canonical_historical_metadata():
    report_dir = ROOT / "benchmark" / "cost_savings" / "results"
    harness = (ROOT / "benchmark" / "cost_savings" / "harness.py").read_text(encoding="utf-8")
    assert "record_status" in harness
    assert "ledger_db_retained" in harness
    assert "content_hash_sha256" in harness
    assert "qa_content_hash_sha256" in harness
    assert "qa_display_content_hash_sha256" in harness
    assert "plutus_ledger" not in harness
    assert "signed LongMemEval" not in harness

    reports = sorted(report_dir.glob("cost_savings_*.json"))
    assert reports, "dated cost-savings reports must be present"
    for path in reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["record_status"] == "historical"
        assert report["ledger_db"] is None
        assert report["ledger_db_retained"] is False
        assert "plutus_ledger" not in report
        content_hash = report.pop("content_hash_sha256", None)
        assert content_hash and len(content_hash) == 64
        expected = hashlib.sha256(
            json.dumps(report, sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert content_hash == expected
        assert "signature_sha256" not in report
        assert "qa_content_hash_sha256" in report
        assert "qa_signature_sha256" not in report
        qa_name = report.get("qa_report")
        assert isinstance(qa_name, str) and qa_name
        qa_path = report_dir / qa_name
        assert qa_path.is_file(), f"missing QA artifact referenced by {path.name}: {qa_name}"
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        qa_hash = qa.get("content_hash_sha256")
        assert qa_hash and len(qa_hash) == 64
        assert report["qa_content_hash_sha256"] == qa_hash
        from benchmark.cost_savings.contract import qa_display_content_hash
        assert report["qa_display_content_hash_sha256"] == qa_display_content_hash(qa)
        text = path.read_text(encoding="utf-8")
        assert "plutus" not in text.lower()

    qa_reports = sorted(report_dir.glob("qa_report_*_2026-07-11.json"))
    assert qa_reports, "dated QA reports referenced by cost reports must be present"
    for path in qa_reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        content_hash = report.get("content_hash_sha256")
        assert content_hash and len(content_hash) == 64
        assert "signature_sha256" not in report


def test_one_pager_rejects_tampered_companion_qa():
    from benchmark.cost_savings import one_pager as module

    report = json.loads(
        (ROOT / "benchmark" / "cost_savings" / "results" / "cost_savings_stratified_2026-07-11.json")
        .read_text(encoding="utf-8")
    )
    qa = json.loads(
        (ROOT / "benchmark" / "cost_savings" / "results" / "qa_report_stratified_2026-07-11.json")
        .read_text(encoding="utf-8")
    )
    qa["systems"]["vault"]["by_question_type"]["multi-session"]["accuracy"] += 0.01

    with pytest.raises(ValueError, match="QA"):
        module.build_facts(report, qa)


def test_one_pager_rejects_nonfinite_qa_and_cross_artifact_metadata():
    from benchmark.cost_savings import one_pager as module

    report_path = ROOT / "benchmark" / "cost_savings" / "results" / "cost_savings_stratified_2026-07-11.json"
    qa_path = ROOT / "benchmark" / "cost_savings" / "results" / "qa_report_stratified_2026-07-11.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    qa = json.loads(qa_path.read_text(encoding="utf-8"))

    qa["systems"]["vault"]["by_question_type"]["multi-session"]["accuracy"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        module.build_facts(report, qa)

    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    del qa["per_question"][0]["error"]
    with pytest.raises(ValueError, match="error"):
        module.build_facts(report, qa)

    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa["per_question"] = qa["per_question"][:-2]
    with pytest.raises(ValueError, match="question count"):
        module.build_facts(report, qa)

    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    mismatched = json.loads(json.dumps(report))
    mismatched["answerer_model"] = "different-model"
    mismatched.pop("content_hash_sha256")
    mismatched["content_hash_sha256"] = hashlib.sha256(
        json.dumps(mismatched, sort_keys=True).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="metadata"):
        module.build_facts(mismatched, qa)


def test_one_pager_escapes_derived_html_strings():
    from benchmark.cost_savings import one_pager as module

    report = json.loads(
        (ROOT / "benchmark" / "cost_savings" / "results" / "cost_savings_stratified_2026-07-11.json")
        .read_text(encoding="utf-8")
    )
    qa = json.loads(
        (ROOT / "benchmark" / "cost_savings" / "results" / "qa_report_stratified_2026-07-11.json")
        .read_text(encoding="utf-8")
    )
    facts = module.build_facts(report, qa)
    facts["model"] = "</code><script>alert(1)</script>"
    facts["answer_prompt"] = "<img src=x onerror=alert(1)>"
    facts["date"] = "</footer><script>alert(1)</script>"
    facts["price_table"] = "<b>untrusted</b>"
    facts["by_type"] = {
        "<img src=x onerror=alert(1)>": {"n": 1, "base": 0.0, "ours": 1.0}
    }
    rendered = module.render_html(facts)
    assert "<script>" not in rendered
    assert "<img src=x" not in rendered
    assert "&lt;script&gt;" in rendered


def test_results_markdown_hashes_match_committed_cost_reports():
    report_dir = ROOT / "benchmark" / "cost_savings" / "results"
    results = (report_dir / "RESULTS.md").read_text(encoding="utf-8")
    for path in sorted(report_dir.glob("cost_savings_*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        for field in ("content_hash_sha256", "qa_content_hash_sha256", "qa_display_content_hash_sha256"):
            value = report.get(field)
            assert isinstance(value, str) and len(value) == 64
            assert f"`{value[:16]}...`" in results


def test_cost_savings_usage_validation_rejects_implicit_coercion():
    from benchmark.cost_savings import harness

    for usage in (
        None,
        {},
        {"prompt_tokens": 1.5, "completion_tokens": 0},
        {"prompt_tokens": True, "completion_tokens": 0},
        {"prompt_tokens": "1", "completion_tokens": 0},
    ):
        with pytest.raises(ValueError):
            harness._validated_usage(usage, "test")
