#!/usr/bin/env python3
"""Build the public master and audience-specific defense capability briefs.

The layout uses equal-width evidence rows, horizontal information bands, and
no unequal decorative cards. Public figures come from claims.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import BaseDocTemplate, Frame, HRFlowable, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "scripts" / "capability_profiles.json"
OUT = ROOT / "government" / "assets"

NAVY = HexColor("#10283D")
BLUE = HexColor("#2E789F")
GREEN = HexColor("#25704D")
INK = HexColor("#17242D")
MUTED = HexColor("#4E626D")
FAINT = HexColor("#6D8089")
RULE = HexColor("#C8D5DB")
PALE = HexColor("#F4F7F8")
PALE_BLUE = HexColor("#EDF4F8")
WHITE = colors.white
PAGE_W, PAGE_H = letter


def styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.2, leading=12.2, textColor=INK)
    return {
        "header_brand": ParagraphStyle("header_brand", fontName="Helvetica-Bold", fontSize=13.6, leading=15, textColor=WHITE),
        "header_meta": ParagraphStyle("header_meta", fontName="Helvetica", fontSize=7.2, leading=8.5, textColor=HexColor("#D6E7F1")),
        "eyebrow": ParagraphStyle("eyebrow", fontName="Helvetica-Bold", fontSize=7.2, leading=8.5, textColor=GREEN),
        "eyebrow_blue": ParagraphStyle("eyebrow_blue", fontName="Helvetica-Bold", fontSize=7.2, leading=8.5, textColor=BLUE),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=25.5, leading=27.5, textColor=NAVY, spaceAfter=7),
        "title_compact": ParagraphStyle("title_compact", fontName="Helvetica-Bold", fontSize=20.5, leading=22.5, textColor=NAVY, spaceAfter=6),
        "lead": ParagraphStyle("lead", parent=base, fontSize=11.0, leading=14.3, textColor=INK),
        "body": ParagraphStyle("body", parent=base, fontSize=9.1, leading=12.0),
        "body_small": ParagraphStyle("body_small", parent=base, fontSize=8.2, leading=10.4, textColor=MUTED),
        "body_tiny": ParagraphStyle("body_tiny", parent=base, fontSize=7.2, leading=9.0, textColor=MUTED),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=10.4, leading=12.2, textColor=NAVY),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=7.0, leading=8.3, textColor=GREEN),
        "label_blue": ParagraphStyle("label_blue", fontName="Helvetica-Bold", fontSize=7.0, leading=8.3, textColor=BLUE),
        "label_muted": ParagraphStyle("label_muted", fontName="Helvetica-Bold", fontSize=7.0, leading=8.3, textColor=FAINT),
        "band_value": ParagraphStyle("band_value", fontName="Helvetica-Bold", fontSize=9.0, leading=10.5, textColor=NAVY),
        "module_title": ParagraphStyle("module_title", fontName="Helvetica-Bold", fontSize=10.4, leading=11.8, textColor=NAVY),
        "metric_value": ParagraphStyle("metric_value", fontName="Helvetica-Bold", fontSize=14.5, leading=16, textColor=GREEN),
        "metric_label": ParagraphStyle("metric_label", fontName="Helvetica-Bold", fontSize=8.0, leading=9.4, textColor=NAVY),
        "metric_detail": ParagraphStyle("metric_detail", parent=base, fontSize=7.2, leading=8.8, textColor=MUTED),
        "footer": ParagraphStyle("footer", fontName="Helvetica", fontSize=6.6, leading=8, textColor=FAINT),
        "callout": ParagraphStyle("callout", parent=base, fontSize=8.6, leading=11.1, textColor=WHITE),
    }


def plain(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def markup(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def rule_section(title: str, st: dict[str, ParagraphStyle]) -> list:
    return [markup(escape(title.upper()), st["section"]), HRFlowable(width="100%", thickness=0.65, color=RULE, spaceBefore=3, spaceAfter=8)]


def header(page_title: str, st: dict[str, ParagraphStyle]) -> Table:
    left = [markup("PERSEUS COMPUTING LLC", st["header_brand"]), markup("PERSEUS CONTEXT ENGINE  ·  PERSEUS VAULT  ·  PERSEUS LEDGER", st["header_meta"])]
    right = [markup(escape(page_title.upper()), st["header_meta"]), markup("DEFENSE CAPABILITY BRIEF  ·  2026", st["header_meta"])]
    t = Table([[left, right]], colWidths=[4.65 * inch, 2.70 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, 0), 12), ("RIGHTPADDING", (0, 0), (0, 0), 4),
        ("LEFTPADDING", (1, 0), (1, 0), 4), ("RIGHTPADDING", (1, 0), (1, 0), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def info_band(profile: dict, st: dict[str, ParagraphStyle]) -> Table:
    focus = str(profile.get("focus_tag") or "Three mission entry points")
    rows = [
        [markup("<b>FOCUS</b><br/>" + escape(focus), st["body_small"]), markup("<b>DEPLOYMENT</b><br/>Local · on-premises · private VPC · disconnected enclave", st["body_small"]), markup("<b>IDENTITY</b><br/>UEI PJS2LW7HAK35 · CAGE 22JC5", st["body_small"]), markup("<b>LICENSE</b><br/>MIT · SBOM published", st["body_small"])],
    ]
    t = Table(rows, colWidths=[1.84 * inch] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("LINEABOVE", (0, 0), (-1, 0), 0.55, RULE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.55, RULE),
        ("LINEBEFORE", (1, 0), (-1, 0), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def two_column_copy(left_label: str, left_text: str, right_label: str, right_text: str, st: dict[str, ParagraphStyle]) -> Table:
    left = [markup(escape(left_label.upper()), st["label_blue"]), Spacer(1, 6), plain(left_text, st["body"])]
    right = [markup(escape(right_label.upper()), st["label"]), Spacer(1, 6), plain(right_text, st["body"])]
    t = Table([[left, right]], colWidths=[3.65 * inch, 3.70 * inch])
    t.setStyle(TableStyle([
        ("LINEBEFORE", (1, 0), (1, 0), 0.7, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 14),
        ("LEFTPADDING", (1, 0), (1, 0), 14), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def system_table(st: dict[str, ParagraphStyle]) -> Table:
    rows = [
        [markup("<b>PERSEUS CONTEXT ENGINE</b><br/><font color='#4E626D'>Before action</font>", st["module_title"]), plain("Resolves live repository, ticket, deployment, and decision state into bounded context before an agent uses it.", st["body_small"])],
        [markup("<b>PERSEUS VAULT</b><br/><font color='#4E626D'>Across sessions</font>", st["module_title"]), plain("Retains governed, bitemporal memory and local retrieval with durable journaling and explicit authority boundaries.", st["body_small"])],
        [markup("<b>PERSEUS LEDGER</b><br/><font color='#4E626D'>After action</font>", st["module_title"]), plain("Records evidence, authority, approvals, and time so captured actions and served context can be reviewed later.", st["body_small"])],
    ]
    t = Table(rows, colWidths=[2.35 * inch, 5.00 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("LINEABOVE", (0, 0), (-1, 0), 0.55, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.55, RULE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def contribution_table(profile: dict, st: dict[str, ParagraphStyle]) -> Table:
    data = [[markup("ROUTE", st["label_muted"]), markup("USE", st["label_muted"]), markup("CONTRIBUTION", st["label_muted"])]]
    for label, text, contribution in profile["contribution_rows"]:
        data.append([markup(f"<b>{escape(label)}</b>", st["body_small"]), plain(text, st["body_small"]), markup(escape(contribution), st["label"])])
    t = Table(data, colWidths=[1.62 * inch, 4.53 * inch, 1.20 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
        ("LINEABOVE", (0, 0), (-1, 0), 0.55, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.55, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def evidence_table(claims: dict, st: dict[str, ParagraphStyle]) -> Table:
    rows = [[markup("MEASURE", st["label_muted"]), markup("RESULT", st["label_muted"]), markup("WHAT IT SHOWS", st["label_muted"]), markup("SCOPE", st["label_muted"])]]
    values = [
        ("LongMemEval-S QA", claims["longmemeval_cot"]["value"], "Latest completed full paired QA result: 410/500 candidate cases under the official-CoT answer prompt.", "500q internal confirmation · control 83.2%"),
        ("Session retrieval", claims["longmemeval_retrieval_recall10"]["value"], "Relevant session memories remain available to the later task.", "Retrieval-only · recall@10"),
        ("BEAM correctness", claims["beam_correctness"]["value"], "The deterministic gauntlet stays correct across token tiers.", "128K–10M token tiers"),
        ("Durable write", claims["vault_durable_write_100k"]["value"], "Sustained write behavior at a 100K-entity scale.", "Signed report · not bulk insert"),
    ]
    for name, value, meaning, scope in values:
        rows.append([markup(f"<b>{escape(name)}</b>", st["metric_label"]), markup(escape(value), st["metric_value"]), plain(meaning, st["body_small"]), plain(scope, st["metric_detail"])])
    t = Table(rows, colWidths=[1.45 * inch, .82 * inch, 3.12 * inch, 1.96 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
        ("LINEABOVE", (0, 0), (-1, 0), 0.55, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.55, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def flat_fact_table(title: str, rows: list[tuple[str, str]], st: dict[str, ParagraphStyle]) -> Table:
    data = [[markup(escape(title.upper()), st["eyebrow_blue"]), ""]]
    data.extend([[markup(f"<b>{escape(k)}</b>", st["body_small"]), plain(v, st["body_small"])] for k, v in rows])
    t = Table(data, colWidths=[1.18 * inch, 2.50 * inch])
    t.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)),
        ("LINEABOVE", (0, 0), (-1, 0), 0.55, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.55, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def engagement_line(profile: dict, st: dict[str, ParagraphStyle]) -> Table:
    data = [[markup("CURRENT ENGAGEMENT", st["label_blue"]), plain(profile["engagement"], st["body_tiny"])]]
    t = Table(data, colWidths=[1.45 * inch, 5.90 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("LINEABOVE", (0, 0), (-1, 0), 0.55, RULE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.55, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(.45)
    canvas.line(doc.leftMargin, .32 * inch, PAGE_W - doc.rightMargin, .32 * inch)
    canvas.setFillColor(FAINT)
    canvas.setFont("Helvetica", 6.6)
    canvas.drawString(doc.leftMargin, .18 * inch, "Perseus Computing LLC  ·  perseus.observer  ·  perseus@perseus.observer")
    canvas.drawRightString(PAGE_W - doc.rightMargin, .18 * inch, f"{doc.page} / 2")
    canvas.restoreState()


def build(name: str, profile: dict, claims: dict) -> Path:
    st = styles()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / profile["filename"]
    doc = BaseDocTemplate(str(path), pagesize=letter, leftMargin=.60*inch, rightMargin=.60*inch, topMargin=.42*inch, bottomMargin=.50*inch, title="Perseus Computing Defense Capability Brief", author="Perseus Computing LLC")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="brief")
    doc.addPageTemplates([PageTemplate(id="brief", frames=[frame], onPage=footer)])
    story: list = []

    # Page 1: platform orientation and mission contribution.
    story += [header("Defense capability", st), Spacer(1, 14), markup("PERSEUS COMPUTING LLC", st["eyebrow"])]
    headline = "Infrastructure for AI agents in controlled environments." if name == "master" else profile["headline"]
    story += [markup(escape(headline), st["title"] if len(headline) < 60 else st["title_compact"]), plain(profile["lead"], st["lead"]), Spacer(1, 12), info_band(profile, st), Spacer(1, 13)]
    story += rule_section("The useful difference", st)
    story += [two_column_copy("The problem", profile["problem"], "The layer", profile["change"], st), Spacer(1, 12)]
    story += rule_section("What Perseus provides", st) + [system_table(st), Spacer(1, 12)]
    story += rule_section("Where the platform contributes", st) + [contribution_table(profile, st), Spacer(1, 8)]
    call = Table([[markup(f"<b>FIRST CONVERSATION</b>&nbsp;&nbsp; {escape(profile['discussion'])}", st["callout"])]], colWidths=[7.35*inch])
    call.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
    story.append(call)

    # Page 2: evidence and procurement without unequal boxes.
    story += [PageBreak(), header("Evidence and procurement", st), Spacer(1, 8), markup("EVIDENCE AND PROCUREMENT", st["eyebrow"]), markup("Proof with the condition attached.", st["title_compact"]), plain("The figures below are kept separate by measurement family so a reviewer can see what each result does—and does not—establish.", st["lead"]), Spacer(1, 10)]
    story += rule_section("Measured evidence", st) + [evidence_table(claims, st), Spacer(1, 4), plain("LongMemEval-S: 82.0% candidate (410/500) vs 83.2% matched full-context control (416/500), -1.2 points. Execution/custody passed, but the preregistered success rule failed; no superiority, independent-holdout, or production-promotion claim is made. The provider-free rerun is provisional.", st["body_tiny"]), Spacer(1, 6)]
    story += rule_section("Procurement and deployment", st)
    left = flat_fact_table("Company", [("Legal name", "Perseus Computing LLC"), ("Business", "U.S. small business · technical access"), ("UEI / CAGE", "PJS2LW7HAK35 / 22JC5"), ("NAICS", "541715 · 541511 · 541512"), ("SAM.gov", "Active — All Awards"), ("JCP / DD2345", claims["jcp_dd2345"]["value"] + " · valid through 2031-08-18")], st)
    right = flat_fact_table("Security and boundary", [("Deployment", "Local, on-premises, private VPC, or customer-configured disconnected enclave"), ("Readiness", "SPRS 110/110 · CMMC Level 2 self-assessment, enclave scope"), ("Software", "MIT license · published SBOM"), ("Data posture", "No required cloud service, API key, or vendor runtime"), ("Integration", "Mission hardware, safety, and test authority remain with the mission owner or qualified partner")], st)
    facts = Table([[left, right]], colWidths=[3.68*inch, 3.67*inch])
    facts.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBEFORE", (1, 0), (1, 0), .7, RULE), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 14), ("LEFTPADDING", (1, 0), (1, 0), 14), ("RIGHTPADDING", (1, 0), (1, 0), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [facts, Spacer(1, 6), engagement_line(profile, st), Spacer(1, 5)]
    story += rule_section("Scope in one sentence", st)
    story += [plain("Perseus is the infrastructure around the model: context before action, governed memory across sessions, and evidence after action. It is not a claim to replace a mission platform, prime integrator, or sensor system.", st["body"]), Spacer(1, 5)]
    contact = Table([[markup("<b>CONTACT</b>&nbsp;&nbsp; perseus@perseus.observer  ·  perseus.observer", st["body_small"]), markup("<b>UPDATED</b>&nbsp;&nbsp; " + escape(str(claims["_meta"]["updated"])), st["body_small"])]], colWidths=[5.75*inch, 1.60*inch])
    contact.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE), ("LINEABOVE", (0, 0), (-1, 0), .55, RULE), ("LINEBELOW", (0, 0), (-1, 0), .55, RULE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.append(contact)
    doc.build(story)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--profile", default="master")
    args = parser.parse_args()
    registry = json.loads((ROOT / "claims.json").read_text(encoding="utf-8"))
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    names = list(profiles) if args.all else [args.profile]
    for name in names:
        print(build(name, profiles[name], registry["claims"] | {"_meta": registry["_meta"]}))


if __name__ == "__main__":
    main()
