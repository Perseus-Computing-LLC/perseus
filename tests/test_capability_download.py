import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement.pdf"
PDF_HREF = "/government/assets/Perseus-Computing-LLC-Capability-Statement.pdf"
COMPATIBILITY_PDFS = [
    ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement-Cyber-Networks.pdf",
    ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement-C3BM.pdf",
    ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement-Electronic-Systems.pdf",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_capability_download_artifact_exists_and_is_linked():
    payload = PDF.read_bytes()
    assert payload.startswith(b"%PDF-")
    assert b"/Count 2" in payload
    assert len(payload) > 1000
    for rel in ("government/index.html", "government/capability-statement.html"):
        assert PDF_HREF in (ROOT / rel).read_text(encoding="utf-8")


def test_capability_download_embeds_true_type_fonts():
    payload = PDF.read_bytes()
    assert b"/FontFile2" in payload
    assert not re.search(rb"/BaseFont /Helvetica(?:\s|/)", payload)
    assert not re.search(rb"/BaseFont /Helvetica-Bold(?:\s|/)", payload)


def test_old_tailored_urls_are_safe_byte_identical_compatibility_aliases():
    canonical = digest(PDF)
    assert all(digest(path) == canonical for path in COMPATIBILITY_PDFS)
    public_html = "\n".join(
        (ROOT / rel).read_text(encoding="utf-8")
        for rel in ("government/index.html", "government/capability-statement.html", "sitemap.xml")
    )
    for path in COMPATIBILITY_PDFS:
        assert path.name not in public_html


def test_government_surface_is_neutral_and_bounded():
    public = "\n".join(
        (ROOT / rel).read_text(encoding="utf-8")
        for rel in ("government/index.html", "government/capability-statement.html", "scripts/build_capability_statement.py")
    )
    for required in (
        "Perseus Context Engine",
        "Perseus Vault",
        "Perseus Ledger",
        "bounded workshare",
        "perseus@perseus.observer",
        "self-assessment",
    ):
        assert required.lower() in public.lower()
    for forbidden in (
        "Email Thomas",
        "Thomas Connally",
        "SAM.gov Active",
        "Active — All Awards",
        "Electronic Systems",
        "sensing, EW, PNT",
        "trusted by Government customers",
        "award granted",
        "holds a facility clearance",
    ):
        assert forbidden.lower() not in public.lower()
    generator = (ROOT / "scripts" / "build_capability_statement.py").read_text(encoding="utf-8")
    assert "COMPATIBILITY_OUTS" in generator
    assert "alias.write_bytes(payload)" in generator
    assert not (ROOT / "docs" / "site" / "MAINTENANCE.md").exists()


def test_tailoring_profile_is_retired_from_public_source():
    profile = (ROOT / "scripts" / "capability_profiles.json").read_text(encoding="utf-8")
    assert '"retired": true' in profile
    for marker in ("C3BM", "Cyber & Networks", "Electronic Systems", "NV074", "Primary fit"):
        assert marker not in profile
