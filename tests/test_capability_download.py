from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement.pdf"
PDF_HREF = "/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf"
VARIANT_PDFS = [
    ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement-Cyber-Networks.pdf",
    ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement-C3BM.pdf",
    ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement-Electronic-Systems.pdf",
]


def test_capability_download_artifact_exists_and_is_linked():
    payload = PDF.read_bytes()
    assert payload.startswith(b"%PDF-")
    assert b"/Count 2" in payload
    assert len(payload) > 1000
    assert PDF_HREF in (ROOT / "government" / "index.html").read_text(encoding="utf-8")
    assert PDF_HREF in (ROOT / "government" / "capability-statement.html").read_text(encoding="utf-8")
    assert 'download="Perseus-Computing-LLC-Capability-Statement.pdf"' in (
        ROOT / "government" / "capability-statement.html"
    ).read_text(encoding="utf-8")


def test_tailored_capability_artifacts_exist_and_public_copy_is_not_internal_workflow_guidance():
    for pdf in VARIANT_PDFS:
        payload = pdf.read_bytes()
        assert payload.startswith(b"%PDF-")
        assert b"/Count 2" in payload
        assert len(payload) > 1000

    public_copy = "\n".join(
        (ROOT / rel).read_text(encoding="utf-8")
        for rel in ("government/index.html", "government/capability-statement.html")
    )
    assert "2 pages" in public_copy
    for phrase in (
        "Use it with the right context",
        "Attach the PDF",
        "Put the mission question",
        "For the first route",
        "intentionally short enough",
    ):
        assert phrase not in public_copy


def test_government_landing_is_single_purpose_and_exposes_all_three_custom_routes():
    landing = (ROOT / "government" / "index.html").read_text(encoding="utf-8")
    assert "Mission fit for" in landing and "controlled AI" in landing
    assert "Email Thomas" not in landing
    assert "Thomas Connally" not in landing
    assert "Choose the version for the conversation." in landing
    assert "Cyber-Networks.pdf" in landing
    assert "C3BM.pdf" in landing
    assert "Electronic-Systems.pdf" in landing
    for retired_marker in (
        "Deploy where the cloud cannot reach.",
        "Security posture",
        "Deployment models",
        "Continue the review",
        "Sovereignty",
    ):
        assert retired_marker not in landing
