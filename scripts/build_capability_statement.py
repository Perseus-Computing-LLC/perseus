#!/usr/bin/env python3
"""Build the master and audience-specific capability statement PDFs.

The PDFs share a single evidence and procurement layer, but the opening page is
written for the reader's mission rather than for Perseus's internal submission
workflow. All measured figures come from the root claims.json registry.

Usage:
    uv run --with reportlab python3 scripts/build_capability_statement.py
    uv run --with reportlab python3 scripts/build_capability_statement.py --profile cyber-networks
    uv run --with reportlab python3 scripts/build_capability_statement.py --all
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import BaseDocTemplate, Frame, HRFlowable, PageTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "scripts" / "capability_profiles.json"
OUTPUT_DIR = ROOT / "government" / "assets"

NAVY = HexColor("#13283D")
BLUE = HexColor("#1D6597")
GREEN = HexColor("#236B4D")
INK = HexColor("#17212B")
MUTED = HexColor("#465968")
FAINT = HexColor("#607381")
PALE_BLUE = HexColor("#EAF2F8")
PALE_GREEN = HexColor("#EAF5EF")
RULE = HexColor("#C4D2DA")
WHITE = colors.white


def styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=7.7, leading=9.2, textColor=INK)
    return {
        "brand": ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=15.6, leading=17, textColor=WHITE),
        "tagline": ParagraphStyle("tagline", fontName="Helvetica", fontSize=7.4, leading=8.8, textColor=HexColor("#D5E8F7"), alignment=TA_LEFT),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=6.8, leading=8.2, textColor=GREEN),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15.2, leading=17.2, textColor=NAVY, spaceAfter=4),
        "lead": ParagraphStyle("lead", fontName="Helvetica", fontSize=9.1, leading=11.3, textColor=INK),
        "identity": ParagraphStyle("identity", fontName="Helvetica", fontSize=7.2, leading=8.7, textColor=FAINT),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=8.7, leading=10.2, textColor=NAVY, spaceAfter=2),
        "body": ParagraphStyle("body", parent=base, fontSize=8.2, leading=9.8),
        "body_small": ParagraphStyle("body_small", parent=base, fontSize=7.8, leading=9.2),
        "bullet": ParagraphStyle("bullet", parent=base, fontSize=8.0, leading=9.5, leftIndent=7, firstLineIndent=-6, spaceAfter=1.8),
        "metric": ParagraphStyle("metric", fontName="Helvetica-Bold", fontSize=13.2, leading=14, textColor=GREEN, alignment=TA_CENTER),
        "metric_label": ParagraphStyle("metric_label", fontName="Helvetica", fontSize=6.1, leading=7.2, textColor=MUTED, alignment=TA_CENTER),
        "footer": ParagraphStyle("footer", fontName="Helvetica", fontSize=6.1, leading=7.2, textColor=FAINT, alignment=TA_CENTER),
        "footer_bold": ParagraphStyle("footer_bold", fontName="Helvetica-Bold", fontSize=6.1, leading=7.2, textColor=NAVY),
    }


def P(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>").replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>"), style)


def rich(text: str, style: ParagraphStyle) -> Paragraph:
    """Render trusted local copy with simple ReportLab markup."""
    return Paragraph(text, style)


def section_heading(title: str, st: dict[str, ParagraphStyle]) -> list:
    return [
        rich(escape(title.upper()), st["section"]),
        HRFlowable(width="100%", thickness=0.55, color=BLUE, spaceBefore=0, spaceAfter=3),
    ]


def bullet(label: str, text: str, st: dict[str, ParagraphStyle]) -> Paragraph:
    return rich(f"&bull;&nbsp; <b>{escape(label)}:</b> {escape(text)}", st["bullet"])


def header(profile: dict, st: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [[rich("PERSEUS COMPUTING LLC", st["brand"]), rich("LIVE CONTEXT + GOVERNED MEMORY FOR AI AGENTS", st["tagline"])]],
        colWidths=[3.48 * inch, 4.12 * inch],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 10),
        ("RIGHTPADDING", (0, 0), (0, 0), 4),
        ("LEFTPADDING", (1, 0), (1, 0), 4),
        ("RIGHTPADDING", (1, 0), (1, 0), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def metric(value: str, label: str, st: dict[str, ParagraphStyle]) -> list[Paragraph]:
    return [rich(escape(value), st["metric"]), rich(escape(label).replace("\\n", "<br/>"), st["metric_label"])]


def mission_table(rows: list[list[str]], st: dict[str, ParagraphStyle]) -> Table:
    data = [[rich(f"<b>{escape(label)}</b>", st["label"]), P(text, st["body_small"])] for label, text in rows]
    table = Table(data, colWidths=[1.33 * inch, 5.94 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PALE_GREEN),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
    ]))
    return table


def build(profile_name: str, profile: dict, claims: dict) -> Path:
    st = styles()
    output = OUTPUT_DIR / profile["filename"]
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(output),
        pagesize=letter,
        leftMargin=0.44 * inch,
        rightMargin=0.44 * inch,
        topMargin=0.34 * inch,
        bottomMargin=0.30 * inch,
        title=f"Perseus Computing LLC — {profile['audience_label']}",
        author="Perseus Computing LLC",
        subject="Capability statement",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="one_sheet")
    doc.addPageTemplates([PageTemplate(id="one_sheet", frames=[frame])])

    story: list = [header(profile, st), Spacer(1, 3)]
    story.extend([
        rich(escape(profile["audience_label"]), st["label"]),
        rich(escape(profile["headline"]), st["title"]),
        P(profile["lead"], st["lead"]),
        Spacer(1, 2),
        rich("<b>UEI:</b> PJS2LW7HAK35&nbsp;&nbsp;&nbsp; <b>CAGE:</b> 22JC5&nbsp;&nbsp;&nbsp; <b>SAM.gov:</b> Active&nbsp;&nbsp;&nbsp; <b>HQ:</b> Austin, Texas", st["identity"]),
        Spacer(1, 4),
    ])

    left: list = []
    left.extend(section_heading("What we build", st))
    left.extend([
        bullet("Live context", "resolves repository, ticket, deployment, and decision state into bounded context before an agent acts.", st),
        bullet("Governed memory", "persists encrypted, bitemporal memory with durable journaling and explicit authority boundaries.", st),
        bullet("Evidence and provenance", "links actions and decisions to evidence, authority, and time so a review does not depend on an opaque dashboard.", st),
        bullet("Deployment boundary", "runs on-premises, air-gapped, in a private VPC, or on a controlled network with no required cloud service, API key, or vendor runtime.", st),
    ])
    right: list = []
    right.extend(section_heading(profile["why_heading"], st))
    right.append(P(profile["why_body"], st["body"]))
    right.append(Spacer(1, 4))
    discussion = Table([[rich(f"<b>DISCUSS</b><br/>{escape(profile['discussion'])}", st["body_small"])]], colWidths=[3.15 * inch])
    discussion.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.45, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    right.append(discussion)
    two_col = Table([[left, right]], colWidths=[4.08 * inch, 3.15 * inch])
    two_col.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 9),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([two_col, Spacer(1, 9)])

    story.extend(section_heading("Measured evidence", st))
    evidence = Table([[
        metric(claims["longmemeval_cot"]["value"], "LongMemEval QA / official-CoT mean / 3 signed runs", st),
        metric(claims["longmemeval_retrieval_recall10"]["value"], "session-level retrieval recall@10 / retrieval-only", st),
        metric(claims["beam_correctness"]["value"], "BEAM correctness / every 128K-10M token tier", st),
        metric(claims["vault_durable_write_100k"]["value"], "durable sustained write / 100K entities", st),
    ]], colWidths=[1.81 * inch] * 4)
    evidence.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([
        evidence,
        rich("Measured on named hardware with signed or committed reports and rerunnable methods. Methodology variants remain separately labeled; no customer ROI or compliance certification is implied.", st["identity"]),
        Spacer(1, 9),
    ])

    story.extend(section_heading("Where it fits", st))
    story.extend([mission_table(profile["fit_rows"], st), Spacer(1, 8)])

    story.extend(section_heading("Procurement and security posture", st))
    posture = Table([
        [rich("<b>Business</b>", st["label"]), P("U.S. small business · NAICS 541715, 541511, 541512 · founder-led technical access", st["body_small"]), rich("<b>Deployment</b>", st["label"]), P("On-premises, air-gapped, private VPC, or controlled network", st["body_small"])],
        [rich("<b>Readiness</b>", st["label"]), P("SPRS 110/110 · CMMC Level 2 final self-assessment, enclave scope", st["body_small"]), rich("<b>Supply chain</b>", st["label"]), P("MIT-licensed · published SBOM · NIST AI RMF-aligned architecture", st["body_small"])],
    ], colWidths=[0.72 * inch, 2.92 * inch, 0.82 * inch, 2.77 * inch])
    posture.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
        ("BACKGROUND", (2, 0), (2, -1), PALE_BLUE),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
    ]))
    story.extend([posture, Spacer(1, 8)])
    next_step = Table([[rich(f"<b>THE FIRST CONVERSATION</b><br/>{escape(profile['discussion'])}", st["body"])]], colWidths=[7.23 * inch])
    next_step.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
        ("BOX", (0, 0), (-1, -1), 0.45, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([next_step, Spacer(1, 8), HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=3)])
    display_label = {
        "MASTER CAPABILITY STATEMENT": "Master",
        "CYBER & NETWORKS": "Cyber & Networks",
        "C3BM": "C3BM",
        "ELECTRONIC SYSTEMS": "Electronic Systems",
    }[profile["audience_label"]]
    story.extend([
        rich("Thomas Connally, Founder &nbsp;&middot;&nbsp; perseus@perseus.observer &nbsp;&middot;&nbsp; perseus.observer &nbsp;&middot;&nbsp; github.com/Perseus-Computing-LLC/perseus", st["footer"]),
        rich(f"{escape(display_label)} capability statement &nbsp;&middot;&nbsp; updated {escape(str(claims['_meta']['updated']))} &nbsp;&middot;&nbsp; source-linked public claims", st["footer"]),
    ])

    doc.build(story)
    print(f"wrote {output}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["master", "cyber-networks", "c3bm", "electronic-systems"], default="master")
    parser.add_argument("--all", action="store_true", help="build the master and all tailored variants")
    args = parser.parse_args()
    registry = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    selected = list(profiles) if args.all else [args.profile]
    for name in selected:
        build(name, profiles[name], registry["claims"] | {"_meta": registry["_meta"]})


if __name__ == "__main__":
    main()
