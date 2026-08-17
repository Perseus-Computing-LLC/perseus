#!/usr/bin/env python3
"""Build the sendable one-page federal capability statement PDF.

The PDF is a generated public artifact. Keep current figures and posture wording
here aligned with claims.json and government/capability-statement.html.

Usage:
    uv run --with reportlab python3 scripts/build_capability_statement.py
"""
from pathlib import Path
import json

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement.pdf"

NAVY = HexColor("#102B46")
BLUE = HexColor("#1769AA")
GREEN = HexColor("#176B4D")
INK = HexColor("#17212B")
MUTED = HexColor("#445566")
FAINT = HexColor("#617384")
PALE_BLUE = HexColor("#EAF2F8")
PALE_GREEN = HexColor("#EAF5EF")
RULE = HexColor("#C9D6DE")
WHITE = colors.white


def make_styles():
    return {
        "brand": ParagraphStyle(
            "brand", fontName="Helvetica-Bold", fontSize=16.4, leading=18,
            textColor=WHITE, spaceAfter=0,
        ),
        "tagline": ParagraphStyle(
            "tagline", fontName="Helvetica", fontSize=8.5, leading=10.5,
            textColor=HexColor("#D5E8F7"),
        ),
        "identity": ParagraphStyle(
            "identity", fontName="Helvetica", fontSize=7.5, leading=9,
            textColor=FAINT, alignment=TA_LEFT,
        ),
        "intro": ParagraphStyle(
            "intro", fontName="Helvetica", fontSize=8.7, leading=11.2,
            textColor=INK,
        ),
        "section": ParagraphStyle(
            "section", fontName="Helvetica-Bold", fontSize=9.2, leading=10.8,
            textColor=NAVY, spaceBefore=0, spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=8.3, leading=10.2,
            textColor=INK,
        ),
        "body_small": ParagraphStyle(
            "body_small", fontName="Helvetica", fontSize=7.8, leading=9.4,
            textColor=INK,
        ),
        "bullet": ParagraphStyle(
            "bullet", fontName="Helvetica", fontSize=8.0, leading=10.0,
            textColor=INK, leftIndent=8, firstLineIndent=-7, spaceAfter=1.4,
        ),
        "label": ParagraphStyle(
            "label", fontName="Helvetica-Bold", fontSize=7.7, leading=9.2,
            textColor=NAVY,
        ),
        "mission_label": ParagraphStyle(
            "mission_label", fontName="Helvetica-Bold", fontSize=7.25, leading=8.7,
            textColor=GREEN,
        ),
        "metric": ParagraphStyle(
            "metric", fontName="Helvetica-Bold", fontSize=14.2, leading=15,
            textColor=GREEN, alignment=TA_CENTER,
        ),
        "metric_label": ParagraphStyle(
            "metric_label", fontName="Helvetica", fontSize=6.8, leading=8.2,
            textColor=MUTED, alignment=TA_CENTER,
        ),
        "footer": ParagraphStyle(
            "footer", fontName="Helvetica", fontSize=6.7, leading=8,
            textColor=FAINT, alignment=TA_CENTER,
        ),
    }


def section_heading(title, styles):
    return [
        Paragraph(title.upper(), styles["section"]),
        HRFlowable(width="100%", thickness=0.65, color=BLUE, spaceBefore=0, spaceAfter=4),
    ]


def bullet(text, styles):
    return Paragraph(f"&bull;&nbsp; {text}", styles["bullet"])


def header(styles):
    header = Table(
        [[
            Paragraph("PERSEUS COMPUTING LLC", styles["brand"]),
            Paragraph("A small-business partner for local-first AI systems", styles["tagline"]),
        ]],
        colWidths=[3.35 * inch, 4.25 * inch],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 11),
        ("RIGHTPADDING", (0, 0), (0, 0), 4),
        ("LEFTPADDING", (1, 0), (1, 0), 4),
        ("RIGHTPADDING", (1, 0), (1, 0), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return header


def metric(value, label, styles):
    return [Paragraph(value, styles["metric"]), Paragraph(label, styles["metric_label"])]


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    registry = json.loads((ROOT / "claims.json").read_text())
    claims = registry["claims"]
    updated = registry["_meta"]["updated"]
    styles = make_styles()
    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=letter,
        leftMargin=0.46 * inch,
        rightMargin=0.46 * inch,
        topMargin=0.39 * inch,
        bottomMargin=0.36 * inch,
        title="Perseus Computing LLC — Capability Statement",
        author="Perseus Computing LLC",
        subject="Federal capability statement",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="one_sheet")
    doc.addPageTemplates([PageTemplate(id="one_sheet", frames=[frame])])

    story = [header(styles), Spacer(1, 4)]
    story.append(Paragraph(
        "<b>Context, memory, and evidence infrastructure for AI agents.</b> Perseus Computing LLC builds the local-first layer that helps agents operate on current state, retain governed memory, and leave an inspectable record of consequential work. The system is designed for on-premises, disconnected, private-VPC, and regulated environments where the data boundary is part of the mission.",
        styles["intro"],
    ))
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        "<b>UEI:</b> PJS2LW7HAK35&nbsp;&nbsp;&nbsp; <b>CAGE:</b> 22JC5&nbsp;&nbsp;&nbsp; <b>SAM.gov:</b> Active&nbsp;&nbsp;&nbsp; <b>HQ:</b> Austin, Texas",
        styles["identity"],
    ))
    story.append(Spacer(1, 5))

    left = [Paragraph("CORE CAPABILITIES", styles["section"]), HRFlowable(width="100%", thickness=0.65, color=BLUE, spaceAfter=4)]
    left.extend([
        bullet("<b>Live context (Perseus):</b> resolves repository, ticket, deployment, and decision state into bounded, verifiable context before an agent acts.", styles),
        bullet("<b>Governed memory (Perseus Vault):</b> provides encrypted, bitemporal memory with durable journaling and explicit authority boundaries.", styles),
        bullet("<b>Evidence and provenance (Ledger):</b> links actions and decisions to evidence, authority, and time so reviews do not depend on an opaque dashboard.", styles),
        bullet("<b>Disconnected deployment:</b> local-first operation with no required cloud service, no required API key, and no mandatory vendor runtime.", styles),
    ])
    right = [Paragraph("MISSION FIT", styles["section"]), HRFlowable(width="100%", thickness=0.65, color=BLUE, spaceAfter=4)]
    mission_rows = [
        [Paragraph("PRIMARY · CYBER &amp; NETWORKS", styles["mission_label"]), Paragraph("Secure AI/ML, DevSecOps, and local context/memory infrastructure for controlled enterprise and cyber workflows.", styles["body_small"])],
        [Paragraph("C3BM · ENABLING FIT", styles["mission_label"]), Paragraph("Evidence and context infrastructure for software factories, ABMS, and decision-advantage workflows; not a claim to own the mission platform.", styles["body_small"])],
        [Paragraph("ES · CONDITIONAL FIT", styles["mission_label"]), Paragraph("Partner-led integration path for sensing, EW, PNT, or mission-system programs where trusted local AI support is relevant.", styles["body_small"])],
    ]
    mission = Table(mission_rows, colWidths=[1.28 * inch, 2.0 * inch])
    mission.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    right.append(mission)
    two_col = Table([[left, right]], colWidths=[4.0 * inch, 3.35 * inch])
    two_col.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(two_col)
    story.append(Spacer(1, 6))

    story.extend(section_heading("Measured evidence", styles))
    metrics = Table([
        [metric(claims["longmemeval_cot"]["value"], "LongMemEval QA\nofficial-CoT mean; 3 signed runs", styles),
         metric(claims["longmemeval_retrieval_recall10"]["value"], "retrieval recall@10\nretrieval-only", styles),
         metric(claims["beam_correctness"]["value"], "bi-temporal correctness\ngates through 10M tokens", styles),
         metric(claims["vault_durable_write_100k"]["value"], "durable sustained write\n@100K entities", styles)],
    ], colWidths=[1.835 * inch] * 4)
    metrics.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(metrics)
    story.append(Paragraph(
        "Measured on named hardware with signed or committed reports and rerunnable methods. Methodology variants remain separately labeled; no customer ROI or compliance certification is implied.",
        ParagraphStyle("evidence_note", parent=styles["identity"], fontSize=6.7, leading=8, spaceBefore=2),
    ))
    story.append(Spacer(1, 5))

    story.extend(section_heading("Procurement and security posture", styles))
    posture_rows = [
        [Paragraph("Business", styles["label"]), Paragraph("U.S. small business · NAICS 541715, 541511, 541512 · founder-led technical access", styles["body_small"]),
         Paragraph("Deployment", styles["label"]), Paragraph("On-premises, air-gapped, private VPC, or controlled network; zero required cloud dependencies", styles["body_small"])],
        [Paragraph("Assessment", styles["label"]), Paragraph("SPRS 110/110 · CMMC Level 2 final self-assessment, enclave scope", styles["body_small"]),
         Paragraph("Supply chain", styles["label"]), Paragraph("MIT-licensed · published SBOM · NIST AI RMF-aligned architecture", styles["body_small"])],
    ]
    posture = Table(posture_rows, colWidths=[0.8 * inch, 2.85 * inch, 0.8 * inch, 2.9 * inch])
    posture.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
        ("BACKGROUND", (2, 0), (2, -1), PALE_BLUE),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(posture)
    story.append(Spacer(1, 5))

    close = Table([[Paragraph(
        "<b>Best starting point:</b> a bounded technical briefing with Cyber &amp; Networks, followed by a scoped pilot or prime/partner discussion. Bring the mission workflow, data boundary, and integration surface; Perseus will bring the smallest credible path.",
        styles["body"],
    )]], colWidths=[7.35 * inch])
    close.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(close)
    story.append(Spacer(1, 5))
    story.append(HRFlowable(width="100%", thickness=0.55, color=RULE, spaceAfter=3))
    story.append(Paragraph(
        "Thomas Connally, Founder &nbsp;&middot;&nbsp; perseus@perseus.observer &nbsp;&middot;&nbsp; perseus.observer &nbsp;&middot;&nbsp; github.com/Perseus-Computing-LLC/perseus",
        styles["footer"],
    ))
    story.append(Paragraph(
        f"Master capability statement &nbsp;&middot;&nbsp; updated {updated} &nbsp;&middot;&nbsp; public claims are scoped and source-linked",
        styles["footer"],
    ))

    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    build()
