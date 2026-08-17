from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement.pdf"
PDF_HREF = "/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf"


def test_capability_download_artifact_exists_and_is_linked():
    payload = PDF.read_bytes()
    assert payload.startswith(b"%PDF-")
    assert len(payload) > 1000
    assert PDF_HREF in (ROOT / "government" / "index.html").read_text(encoding="utf-8")
    assert PDF_HREF in (ROOT / "government" / "capability-statement.html").read_text(encoding="utf-8")
    assert 'download="Perseus-Computing-LLC-Capability-Statement.pdf"' in (
        ROOT / "government" / "capability-statement.html"
    ).read_text(encoding="utf-8")
