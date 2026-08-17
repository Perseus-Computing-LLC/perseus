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
        assert len(payload) > 1000

    public_copy = "\n".join(
        (ROOT / rel).read_text(encoding="utf-8")
        for rel in ("government/index.html", "government/capability-statement.html")
    )
    for phrase in (
        "Use it with the right context",
        "Attach the PDF",
        "Put the mission question",
        "For the first route",
        "intentionally short enough",
    ):
        assert phrase not in public_copy
