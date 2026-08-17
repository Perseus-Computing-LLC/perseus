#!/usr/bin/env python3
"""Build a readable master and three audience-specific capability statements.

The layout intentionally uses two Letter pages instead of compressing every
claim into a single dense sheet:

  page 1: mission problem, Perseus system, fit, first conversation
  page 2: measured evidence, procurement facts, deployment boundary, contact

All public figures are read from the canonical claims.json registry. Profiles
change the audience framing and fit language, not the evidence layer.
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
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "scripts" / "capability_profiles.json"
OUTPUT_DIR = ROOT / "government" / "assets"

NAVY = HexColor("#10283D")
NAVY_2 = HexColor("#1A3C57")
BLUE = HexColor("#2E789F")
GREEN = HexColor("#25704D")
GOLD = HexColor("#B57925")
INK = HexColor("#17242D")
MUTED = HexColor("#4E626D")
FAINT = HexColor("#6D8089")
PALE_BLUE = HexColor("#EDF4F8")
PALE_GREEN = HexColor("#EDF7F1")
PALE_GOLD = HexColor("#FBF4E8")
RULE = HexColor("#C8D5DB")
WHITE = colors.white

PAGE_W, PAGE_H = letter


def make_styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "base",
        fontName="Helvetica",
        fontSize=9.1,
        leading=12.2,
        textColor=INK,
        spaceAfter=0,
    )
    return {
        "brand": ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=15.5, leading=17, textColor=WHITE),
        "brand_sub": ParagraphStyle("brand_sub", fontName="Helvetica", fontSize=7.3, leading=9, textColor=HexColor("#D6E7F1")),
        "eyebrow": ParagraphStyle("eyebrow", fontName="Helvetica-Bold", fontSize=7.4, leading=9, textColor=GREEN, tracking=0.8),
        "eyebrow_white": ParagraphStyle("eyebrow_white", fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=HexColor("#D5E8F7"), tracking=0.7),
        "hero_title": ParagraphStyle("hero_title", fontName="Helvetica-Bold", fontSize=25.5, leading=28.2, textColor=NAVY, spaceAfter=6),
        "hero_title_compact": ParagraphStyle("hero_title_compact", fontName="Helvetica-Bold", fontSize=21.5, leading=24.2, textColor=NAVY, spaceAfter=6),
        "lead": ParagraphStyle("lead", parent=base, fontSize=11.1, leading=14.4, textColor=INK),
        "body": ParagraphStyle("body", parent=base, fontSize=9.2, leading=12.0),
        "body_small": ParagraphStyle("body_small", parent=base, fontSize=8.25, leading=10.6),
        "body_tiny": ParagraphStyle("body_tiny", parent=base, fontSize=7.4, leading=9.2, textColor=MUTED),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=10.2, leading=12, textColor=NAVY),
        "card_title": ParagraphStyle("card_title", fontName="Helvetica-Bold", fontSize=11.3, leading=13.1, textColor=NAVY),
        "card_text": ParagraphStyle("card_text", parent=base, fontSize=8.25, leading=10.5, textColor=MUTED),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=7.2, leading=8.6, textColor=GREEN),
        "label_blue": ParagraphStyle("label_blue", fontName="Helvetica-Bold", fontSize=7.2, leading=8.6, textColor=BLUE),
        "label_gold": ParagraphStyle("label_gold", fontName="Helvetica-Bold", fontSize=7.2, leading=8.6, textColor=GOLD),
        "metric_value": ParagraphStyle("metric_value", fontName="Helvetica-Bold", fontSize=20, leading=21, textColor=GREEN, alignment=TA_LEFT),
        "metric_label": ParagraphStyle("metric_label", fontName="Helvetica-Bold", fontSize=8.2, leading=9.8, textColor=NAVY),
        "metric_detail": ParagraphStyle("metric_detail", parent=base, fontSize=7.4, leading=9.2, textColor=MUTED),
        "identity": ParagraphStyle("identity", fontName="Helvetica", fontSize=7.5, leading=9.4, textColor=FAINT),
        "footer": ParagraphStyle("footer", fontName="Helvetica", fontSize=6.7, leading=8.1, textColor=FAINT, alignment=TA_CENTER),
        "callout": ParagraphStyle("callout", parent=base, fontSize=9.1, leading=12.0, textColor=NAVY),
        "at_glance_value": ParagraphStyle("at_glance_value", fontName="Helvetica-Bold", fontSize=9.2, leading=11, textColor=NAVY),
        "at_glance_label": ParagraphStyle("at_glance_label", fontName="Helvetica-Bold", fontSize=6.8, leading=8.2, textColor=FAINT),
    }


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def rich(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def section_heading(title: str, st: dict[str, ParagraphStyle], color=BLUE) -> list:
    return [
        rich(escape(title.upper()), st["section"]),
        HRFlowable(width="100%", thickness=0.7, color=color, spaceBefore=1, spaceAfter=7),
    ]


def bullet(label: str, text: str, st: dict[str, ParagraphStyle]) -> Paragraph:
    return rich(f"<font color='{GREEN.hexval()}'>&bull;</font>&nbsp; <b>{escape(label)}</b> {escape(text)}", st["body_small"])


def header(st: dict[str, ParagraphStyle], page_label: str) -> Table:
    left = [rich("PERSEUS COMPUTING LLC", st["brand"]), rich("CONTEXT  ·  MEMORY  ·  EVIDENCE", st["brand_sub"])]
    right = [rich(escape(page_label.upper()), st["eyebrow_white"]), rich("CAPABILITY STATEMENT  ·  2026", st["brand_sub"])]
    table = Table([[left, right]], colWidths=[4.65 * inch, 2.75 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, 0), 13),
        ("RIGHTPADDING", (0, 0), (0, 0), 5),
        ("LEFTPADDING", (1, 0), (1, 0), 5),
        ("RIGHTPADDING", (1, 0), (1, 0), 13),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return table


def at_a_glance(profile: dict, st: dict[str, ParagraphStyle]) -> Table:
    rows = [
        [p("PRIMARY FIT", st["at_glance_label"]), p(profile["fit_tag"], st["at_glance_value"])],
        [p("DEPLOYMENT", st["at_glance_label"]), p("Local / air-gapped / private VPC", st["at_glance_value"])],
        [p("PROCUREMENT", st["at_glance_label"]), p("SAM active · CAGE 22JC5", st["at_glance_value"])],
        [p("CONTACT", st["at_glance_label"]), p("perseus@perseus.observer", st["at_glance_value"])],
    ]
    table = Table(rows, colWidths=[0.88 * inch, 2.13 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def module_card(number: str, title: str, text: str, background, st: dict[str, ParagraphStyle]) -> Table:
    cell = [
        rich(escape(number), st["label"]),
        Spacer(1, 9),
        rich(escape(title), st["card_title"]),
        Spacer(1, 5),
        p(text, st["card_text"]),
    ]
    table = Table([[cell]], colWidths=[2.36 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("BOX", (0, 0), (-1, -1), 0.45, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    return table


def fit_table(profile: dict, st: dict[str, ParagraphStyle]) -> Table:
    data = []
    for label, text, tag in profile["fit_rows"]:
        tag_style = st["label_gold"] if tag == "PRIMARY FIT" else st["label_blue"] if tag == "ENABLING FIT" else st["label"]
        data.append([rich(f"<b>{escape(label)}</b><br/><font size='6.7'>{escape(tag)}</font>", tag_style), p(text, st["body_small"])])
    table = Table(data, colWidths=[1.62 * inch, 5.58 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PALE_GREEN),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def metric_card(value: str, label: str, detail: str, st: dict[str, ParagraphStyle]) -> Table:
    cell = [rich(escape(value), st["metric_value"]), Spacer(1, 5), rich(escape(label), st["metric_label"]), Spacer(1, 4), p(detail, st["metric_detail"])]
    table = Table([[cell]], colWidths=[3.54 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    return table


def fact_block(title: str, rows: list[tuple[str, str]], background, st: dict[str, ParagraphStyle]) -> Table:
    body = [rich(escape(title.upper()), st["eyebrow"])]
    for label, value in rows:
        body.extend([rich(f"<b>{escape(label)}</b><br/>{escape(value)}", st["body_small"]), Spacer(1, 5)])
    table = Table([[body]], colWidths=[3.54 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def page_chrome(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.45)
    canvas.line(doc.leftMargin, 0.34 * inch, PAGE_W - doc.rightMargin, 0.34 * inch)
    canvas.setFillColor(FAINT)
    canvas.setFont("Helvetica", 6.7)
    canvas.drawString(doc.leftMargin, 0.20 * inch, "Perseus Computing LLC  ·  perseus.observer  ·  perseus@perseus.observer")
    canvas.drawRightString(PAGE_W - doc.rightMargin, 0.20 * inch, f"{doc.page} / 2")
    canvas.restoreState()


def build(profile_name: str, profile: dict, claims: dict) -> Path:
    st = make_styles()
    output = OUTPUT_DIR / profile["filename"]
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(output),
        pagesize=letter,
        leftMargin=0.56 * inch,
        rightMargin=0.56 * inch,
        topMargin=0.42 * inch,
        bottomMargin=0.52 * inch,
        title=f"Perseus Computing LLC — {profile['audience_label']}",
        author="Perseus Computing LLC",
        subject="Capability statement",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="capability")
    doc.addPageTemplates([PageTemplate(id="capability", frames=[frame], onPage=page_chrome)])

    c = claims
    story: list = []

    # PAGE 1: orient the reader before listing proof.
    story.append(header(st, profile["audience_label"]))
    story.append(Spacer(1, 13))
    story.append(rich("CAPABILITY STATEMENT", st["eyebrow"]))
    hero_title_style = st["hero_title_compact"] if len(profile["headline"]) > 62 else st["hero_title"]
    hero = [
        rich(escape(profile["headline"]), hero_title_style),
        p(profile["lead"], st["lead"]),
        Spacer(1, 8),
        rich("<b>UEI</b>  PJS2LW7HAK35 &nbsp;&nbsp; <b>CAGE</b>  22JC5 &nbsp;&nbsp; <b>SAM</b>  Active &nbsp;&nbsp; <b>HQ</b>  Austin, Texas", st["identity"]),
    ]
    hero_table = Table([[hero, at_a_glance(profile, st)]], colWidths=[4.25 * inch, 3.10 * inch])
    hero_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 13),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(hero_table)
    story.append(Spacer(1, 16))

    story.extend(section_heading("The problem we solve", st))
    problem = Table([[
        p(profile["problem"], st["body"]),
        rich(f"<b>WHAT CHANGES</b><br/><br/>{escape(profile['change'])}", st["callout"]),
    ]], colWidths=[4.25 * inch, 3.10 * inch])
    problem.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, 0), PALE_GOLD),
        ("BOX", (1, 0), (1, 0), 0.5, HexColor("#E5C58C")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 13),
        ("LEFTPADDING", (1, 0), (1, 0), 11),
        ("RIGHTPADDING", (1, 0), (1, 0), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(problem)
    story.append(Spacer(1, 16))

    story.extend(section_heading("The Perseus system", st))
    modules = Table([[
        module_card("01  /  CONTEXT", "Before the agent acts", "Resolves repository, ticket, deployment, and decision state into bounded context before a model uses it.", PALE_BLUE, st),
        module_card("02  /  MEMORY", "After the session ends", "Vault retains encrypted, bitemporal memory with durable journaling and explicit authority boundaries.", PALE_GREEN, st),
        module_card("03  /  EVIDENCE", "When the work is reviewed", "Ledger links actions and decisions to evidence, authority, and time instead of leaving the record in an opaque dashboard.", PALE_GOLD, st),
    ]], colWidths=[2.36 * inch, 2.36 * inch, 2.36 * inch])
    modules.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 7),
        ("RIGHTPADDING", (1, 0), (1, 0), 7),
        ("RIGHTPADDING", (2, 0), (2, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(modules)
    story.append(Spacer(1, 16))

    story.extend(section_heading("Where this fits", st))
    story.append(fit_table(profile, st))
    story.append(Spacer(1, 15))
    first = Table([[rich(f"<b>FIRST CONVERSATION</b>&nbsp;&nbsp; {escape(profile['discussion'])}", st["callout"])]], colWidths=[7.35 * inch])
    first.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, -1), WHITE),
        ("BOX", (0, 0), (-1, -1), 0.5, NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.append(first)

    # PAGE 2: evidence and procurement details with more room to breathe.
    story.append(PageBreak())
    story.append(header(st, "Evidence and procurement"))
    story.append(Spacer(1, 14))
    story.append(rich("EVIDENCE AND PROCUREMENT", st["eyebrow"]))
    story.append(rich("Proof first. Claims stay attached to their method.", st["hero_title_compact"]))
    story.append(p("The figures below are drawn from the public claims registry. They are presented with the measurement family and condition that give each number meaning.", st["lead"]))
    story.append(Spacer(1, 16))

    story.extend(section_heading("Measured evidence", st))
    metrics = [
        metric_card(c["longmemeval_cot"]["value"], "LongMemEval QA", "Official-CoT mean of three signed runs.", st),
        metric_card(c["longmemeval_retrieval_recall10"]["value"], "Session retrieval recall@10", "Retrieval-only session-level result.", st),
        metric_card(c["beam_correctness"]["value"], "BEAM correctness", "Every 128K–10M token tier; deterministic gauntlet.", st),
        metric_card(c["vault_durable_write_100k"]["value"], "Durable sustained write", "Signed scale report at 100K entities; not an in-memory insert rate.", st),
    ]
    metric_grid = Table([[metrics[0], metrics[1]], [metrics[2], metrics[3]]], colWidths=[3.68 * inch, 3.68 * inch])
    metric_grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 7),
        ("LEFTPADDING", (1, 0), (1, -1), 0),
        ("RIGHTPADDING", (1, 0), (1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
    ]))
    story.append(metric_grid)
    story.append(Spacer(1, 7))
    story.append(p("Measured on named hardware with signed or committed reports and rerunnable methods. Methodology variants remain separately labeled. No customer ROI, customer cost savings, or compliance certification is implied by these figures.", st["body_tiny"]))
    story.append(Spacer(1, 17))

    story.extend(section_heading("Procurement facts", st))
    facts = Table([[
        fact_block("Company", [
            ("Legal name", "Perseus Computing LLC"),
            ("Business", "U.S. small business · technical access"),
            ("UEI / CAGE", "PJS2LW7HAK35 / 22JC5"),
            ("NAICS", "541715 · 541511 · 541512"),
            ("SAM.gov", "Active — All Awards"),
        ], PALE_BLUE, st),
        fact_block("Security and deployment", [
            ("Boundary", "On-premises, air-gapped, private VPC, or controlled network"),
            ("Readiness", "SPRS 110/110 · CMMC Level 2 final self-assessment, enclave scope"),
            ("Software", "MIT license · published SBOM · NIST AI RMF-aligned architecture"),
            ("Data posture", "No required cloud service, API key, or vendor runtime"),
            ("Integration", "Partner-led where mission hardware or sensors are involved"),
        ], PALE_GREEN, st),
    ]], colWidths=[3.68 * inch, 3.68 * inch])
    facts.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 7),
        ("LEFTPADDING", (1, 0), (1, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(facts)
    story.append(Spacer(1, 17))

    display_label = {
        "MASTER CAPABILITY STATEMENT": "Master",
        "CYBER & NETWORKS": "Cyber & Networks",
        "C3BM": "C3BM",
        "ELECTRONIC SYSTEMS": "Electronic Systems",
    }[profile["audience_label"]]
    story.append(Spacer(1, 12))
    boundary = Table([[
        rich("<b>DEPLOYMENT BOUNDARY</b><br/>Run the context, memory, and evidence layers where the program keeps its working data. Air-gapped, on-premises, private VPC, and controlled-network deployment are supported postures.", st["body_tiny"]),
        rich("<b>CONTACT</b><br/>perseus@perseus.observer", st["body_tiny"]),
    ]], colWidths=[4.72 * inch, 2.63 * inch])
    boundary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), PALE_BLUE),
        ("BACKGROUND", (1, 0), (1, 0), PALE_GREEN),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(boundary)
    story.append(Spacer(1, 5))
    story.append(rich(f"Updated {escape(str(c['_meta']['updated']))} · {escape(display_label)} version · Source-linked public claims", st["footer"]))

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
