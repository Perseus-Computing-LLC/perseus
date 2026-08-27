#!/usr/bin/env python3
"""Build the single public Perseus defense capability brief.

The public site intentionally publishes one generic, bounded brief. Pursuit-
specific tailoring and internal fit matrices do not belong in GitHub Pages.
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement.pdf"
COMPATIBILITY_OUTS = [
    ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement-Cyber-Networks.pdf",
    ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement-C3BM.pdf",
    ROOT / "government" / "assets" / "Perseus-Computing-LLC-Capability-Statement-Electronic-Systems.pdf",
]
CLAIMS = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))["claims"]

PAPER = colors.HexColor("#F2EFE7")
INK = colors.HexColor("#132124")
SOFT = colors.HexColor("#3F5153")
TEAL = colors.HexColor("#176B69")
AMBER = colors.HexColor("#B66F17")
LINE = colors.HexColor("#C9C5BA")
TEAL_SOFT = colors.HexColor("#D7E5E1")
AMBER_SOFT = colors.HexColor("#F0DFC2")

styles = getSampleStyleSheet()
TITLE = ParagraphStyle("Title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=27, leading=29, textColor=INK, alignment=TA_LEFT, spaceAfter=11)
DECK = ParagraphStyle("Deck", parent=styles["BodyText"], fontName="Helvetica", fontSize=10.4, leading=14.2, textColor=SOFT, spaceAfter=10)
KICKER = ParagraphStyle("Kicker", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=TEAL, tracking=1.1, spaceAfter=6)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=16, leading=18, textColor=INK, spaceAfter=8, spaceBefore=3)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=10.5, leading=12.5, textColor=INK, spaceAfter=4)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=SOFT, spaceAfter=7)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=7.2, leading=9.3, spaceAfter=3)
WHITE = ParagraphStyle("White", parent=BODY, textColor=colors.white, fontName="Helvetica-Bold", fontSize=8.2, leading=10)


def p(text: str, style=BODY) -> Paragraph:
    return Paragraph(text, style)


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, letter[0], letter[1], stroke=0, fill=1)
    canvas.setStrokeColor(LINE)
    canvas.line(0.65 * inch, 0.52 * inch, 7.85 * inch, 0.52 * inch)
    canvas.setFillColor(SOFT)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(0.65 * inch, 0.31 * inch, "Perseus Computing LLC · perseus.observer · perseus@perseus.observer")
    canvas.drawRightString(7.85 * inch, 0.31 * inch, f"{doc.page} / 2")
    canvas.restoreState()


def label(text: str) -> Paragraph:
    return p(text.upper(), KICKER)


def fact_table(rows):
    data = [[p(a, KICKER), p(b, H3), p(c, SMALL)] for a, b, c in rows]
    table = Table(data, colWidths=[1.1 * inch, 2.1 * inch, 3.95 * inch])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def component_table():
    data = [
        [p("PRESENT", KICKER), p("Perseus Context Engine", H3), p("Resolves current repository, service, test, task, and convention data into a bounded briefing before work starts.", SMALL)],
        [p("CONTINUITY", KICKER), p("Perseus Vault", H3), p("Preserves decisions, corrections, and time-valid facts locally for later authorized work.", SMALL)],
        [p("EVIDENCE", KICKER), p("Perseus Ledger", H3), p("Records supplied events, evidence links, and authority references in a hash chain that can be checked later.", SMALL)],
    ]
    table = Table(data, colWidths=[1.05 * inch, 2.0 * inch, 4.1 * inch])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return table


def callout(text: str, background=TEAL_SOFT):
    table = Table([[p(text, H3)]], colWidths=[7.15 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("BOX", (0, 0), (-1, -1), 0.8, TEAL if background == TEAL_SOFT else AMBER),
        ("LEFTPADDING", (0, 0), (-1, -1), 13),
        ("RIGHTPADDING", (0, 0), (-1, -1), 13),
        ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    return table


def build_story():
    qa = CLAIMS["longmemeval_cot"]
    return [
        label("Defense capability brief · 2026"),
        p("Perseus Computing LLC", H3),
        p("Add context, memory, and evidence without replacing the mission system.", TITLE),
        p("Perseus is the system around the model. It gives agent work current context, governed memory, and reviewable evidence while the customer and qualified integrator retain model selection, data classification, accreditation, safety, system integration, and operational authority.", DECK),
        Spacer(1, 6),
        component_table(),
        Spacer(1, 14),
        label("Bounded workshare"),
        p("Start with one workflow, its data boundary, and the integration surface. Perseus Computing will identify the smallest context, memory, or evidence contribution that can be evaluated without claiming ownership of the mission system.", H2),
        fact_table([
            ("Secure AI", "Engineering context and continuity", "Prepare current repository, test, configuration, and handoff context inside a customer-controlled environment."),
            ("Review", "Evidence and provenance", "Link a supplied action to the state, references, and review context available at the time."),
            ("Integration", "Prime-led mission-system work", "Expose bounded interfaces alongside the mission platform. The prime retains hardware, domain integration, verification, accreditation, and delivery."),
        ]),
        Spacer(1, 14),
        label("Deployment boundary"),
        callout("Local CLI and stdio paths do not require a Perseus-hosted service. On-premises, private-cloud, and disconnected packaging remain subject to the program's own hardening, network, key, data-handling, and authorization decisions."),
        Spacer(1, 10),
        p("Perseus does not claim Government customers, awards, operational deployments, facility clearance, classified-data authority, ATO/cATO, cross-domain approval, safety certification, or autonomous authority over mission systems.", SMALL),
        PageBreak(),
        label("Evidence and procurement posture"),
        p("Proof with the condition attached.", TITLE),
        p("The figures below are separate measurement families. None is a customer outcome, operational deployment result, or Government authorization.", DECK),
        fact_table([
            ("QA", f"{qa['value']} · 410/500", "LongMemEval-S paired internal confirmation using the official-CoT answer prompt and evidence-structured context. Matched full-context control: 416/500 (83.2%); delta −1.2 points; preregistered success rule failed."),
            ("Retrieval", "99.2% recall@10", "Company-run session-level retrieval on the 500-instance LongMemEval split. No answer-quality control arm. Retrieval-only; not answer accuracy, model quality, customer performance, deployment evidence, or production validation."),
            ("Correctness", "13/13", "Company-run offline fixture scenarios across the published temporal gauntlet and BEAM corpus tiers. No comparative control arm. Reconstruction correctness for those fixtures; not real-world model quality, customer performance, deployment evidence, or production validation."),
            ("Operations", "40 durable writes/s", "Company-run signed scale report at 100K entities on named hardware. No comparative control arm. Sustained durable-write throughput only; not customer capacity, deployment performance, or a service-level guarantee."),
        ]),
        Spacer(1, 14),
        label("Entity and assessment records"),
        fact_table([
            ("Entity", "Perseus Computing LLC", "UEI PJS2LW7HAK35 · CAGE 22JC5. Identifiers do not imply an award, contract vehicle, clearance, or current SAM status."),
            ("SPRS", "Basic self-assessment: 110", "NIST SP 800-171 Basic assessment, recorded enclave scope, assessed 2026-08-04. Not an independent assessment."),
            ("CMMC", "Level 2 self-assessment: 110", "Final self-assessment, recorded enclave scope, assessed 2026-08-06. Not C3PAO certification."),
            ("JCP", "DD2345 0092893", "Approved 2026-08-18 through 2031-08-18 for requesting unclassified export-controlled military technical data. Separate registration and access approval still apply."),
            ("Software", "MIT-licensed core", "Published SBOM and security materials. These are source and supply-chain posture, not Government approval."),
        ]),
        Spacer(1, 12),
        callout("Discuss a bounded workshare · Perseus Computing LLC · perseus@perseus.observer", AMBER_SOFT),
        Spacer(1, 8),
        p("Review the current security boundary, methods, source, and web version at perseus.observer. Confirm volatile package, registry, assessment, and procurement facts from their authoritative source before proposal or award use.", SMALL),
    ]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.65 * inch,
        title="Perseus Computing LLC defense capability brief",
        author="Perseus Computing LLC",
        subject="Bounded public capability brief for Perseus Context Engine, Perseus Vault, and Perseus Ledger",
        invariant=1,
    )
    doc.build(build_story(), onFirstPage=on_page, onLaterPages=on_page)
    payload = OUT.read_bytes()
    for alias in COMPATIBILITY_OUTS:
        alias.write_bytes(payload)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
