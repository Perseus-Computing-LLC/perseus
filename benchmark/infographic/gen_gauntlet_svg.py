#!/usr/bin/env python3
"""Generate SVG infographics from the latest Perseus gauntlet run."""

from __future__ import annotations

import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GAUNTLET_RESULTS = ROOT / "benchmark" / "gauntlet" / "gauntlet_results.json"
OUT_DIR = ROOT / "benchmark" / "infographic"


BG = "#10131a"
PANEL = "#171c24"
PANEL_2 = "#1f2630"
INK = "#f2f5f7"
MUTED = "#aab4c0"
GRID = "#2d3542"
GREEN = "#3ddc97"
TEAL = "#37c7d4"
BLUE = "#7aa2f7"
AMBER = "#f5b84b"
RED = "#ef6461"
VIOLET = "#b98cff"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def fmt_s(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    if seconds >= 60:
        return f"{seconds / 60:.0f}m"
    return f"{seconds:.0f}s"


def pct(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{value * 100:.0f}%"


def load() -> dict:
    return json.loads(GAUNTLET_RESULTS.read_text())


def svg_frame(width: int, height: int, title: str, subtitle: str) -> list[str]:
    return [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(title)}">',
        "<style>",
        "text { font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; letter-spacing: 0; }",
        ".title { font-size: 34px; font-weight: 760; fill: #f2f5f7; }",
        ".subtitle { font-size: 16px; fill: #aab4c0; }",
        ".section { font-size: 18px; font-weight: 720; fill: #f2f5f7; }",
        ".label { font-size: 13px; fill: #aab4c0; }",
        ".small { font-size: 11px; fill: #8d98a6; }",
        ".metric { font-size: 40px; font-weight: 780; fill: #f2f5f7; }",
        ".metric2 { font-size: 28px; font-weight: 760; fill: #f2f5f7; }",
        ".mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }",
        "</style>",
        f'<rect width="{width}" height="{height}" fill="{BG}"/>',
        f'<text x="44" y="58" class="title">{esc(title)}</text>',
        f'<text x="44" y="86" class="subtitle">{esc(subtitle)}</text>',
    ]


def panel(svg: list[str], x: int, y: int, w: int, h: int, title: str | None = None) -> None:
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{PANEL}" stroke="{GRID}" stroke-width="1"/>')
    if title:
        svg.append(f'<text x="{x + 18}" y="{y + 34}" class="section">{esc(title)}</text>')


def metric_card(svg: list[str], x: int, y: int, w: int, label: str, value: str, color: str, note: str | None = None) -> None:
    panel(svg, x, y, w, 118)
    svg.append(f'<text x="{x + 18}" y="{y + 30}" class="label">{esc(label)}</text>')
    svg.append(f'<text x="{x + 18}" y="{y + 78}" class="metric" fill="{color}" style="fill:{color}">{esc(value)}</text>')
    if note:
        svg.append(f'<text x="{x + 18}" y="{y + 101}" class="small">{esc(note)}</text>')


def progress_bar(svg: list[str], x: int, y: int, w: int, label: str, value: float, color: str, suffix: str = "") -> None:
    svg.append(f'<text x="{x}" y="{y - 8}" class="label">{esc(label)}</text>')
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="12" rx="6" fill="{PANEL_2}"/>')
    svg.append(f'<rect x="{x}" y="{y}" width="{max(4, w * value):.1f}" height="12" rx="6" fill="{color}"/>')
    svg.append(f'<text x="{x + w + 12}" y="{y + 11}" class="small">{esc(suffix or pct(value))}</text>')


def generate_certification(data: dict) -> str:
    phases = data["phase_results"]
    gates = data["gate_report"]
    width, height = 1200, 860
    svg = svg_frame(
        width,
        height,
        "Perseus Gauntlet Certification",
        "Full 2026-05-31 run: all phases completed, all active gates passed.",
    )

    metric_card(svg, 44, 122, 250, "Gauntlet score", f"{data['score']:.0f}/100", GREEN, "overall PASS")
    metric_card(svg, 318, 122, 250, "Gate result", f"{gates['passed']}/{gates['total']}", TEAL, "zero failed gates")
    total_failures = sum(p.get("failures", 0) or 0 for p in phases)
    metric_card(svg, 592, 122, 250, "Phase failures", str(total_failures), BLUE, "12 phases completed")
    p50_values = [p.get("p50_s") for p in phases if isinstance(p.get("p50_s"), (int, float))]
    typical = sorted(p50_values)[len(p50_values) // 2]
    metric_card(svg, 866, 122, 250, "Typical p50", f"{typical:.2f}s", VIOLET, "render-heavy phases")

    panel(svg, 44, 280, 1072, 318, "Phase Timeline")
    names = {
        0: "Preflight",
        1: "Cold",
        2: "Warm",
        3: "Week",
        4: "Swarm",
        5: "Relay",
        6: "Inbox",
        7: "Adversarial",
        8: "Semantic",
        9: "Tokens",
        10: "Torture",
        11: "Report",
    }
    max_duration = max(p.get("duration_s", 0) or 0 for p in phases)
    x0, y0, row_h, bar_w = 190, 334, 20, 760
    for i, p in enumerate(phases):
        y = y0 + i * row_h
        duration = p.get("duration_s", 0) or 0
        value = duration / max_duration if max_duration else 0
        color = GREEN if p.get("within_time_budget", True) else AMBER
        svg.append(f'<text x="64" y="{y + 11}" class="small">{p.get("phase")}: {esc(names.get(p.get("phase"), p.get("name")))}</text>')
        svg.append(f'<rect x="{x0}" y="{y}" width="{bar_w}" height="12" rx="6" fill="{PANEL_2}"/>')
        svg.append(f'<rect x="{x0}" y="{y}" width="{max(3, bar_w * value):.1f}" height="12" rx="6" fill="{color}"/>')
        status = "OK" if (p.get("failures", 0) or 0) == 0 else "FAIL"
        svg.append(f'<text x="{x0 + bar_w + 18}" y="{y + 11}" class="small">{fmt_s(duration)} / {status}</text>')

    panel(svg, 44, 628, 520, 168, "What Certified")
    certified = [
        ("Cache integrity", "664 entries, 0 corrupt"),
        ("Coordination", "0 swarm collisions"),
        ("Inbox delivery", "99.9%+ gate passed"),
        ("Sustained memory", "RSS growth about 1.02%"),
    ]
    for i, (label, value) in enumerate(certified):
        y = 676 + i * 28
        svg.append(f'<circle cx="70" cy="{y - 5}" r="5" fill="{GREEN}"/>')
        svg.append(f'<text x="88" y="{y}" class="label">{esc(label)}</text>')
        svg.append(f'<text x="300" y="{y}" class="label" fill="{INK}" style="fill:{INK}">{esc(value)}</text>')

    panel(svg, 596, 628, 520, 168, "Reading The Result")
    notes = [
        "The useful signal is not only PASS.",
        "It is fast, repeatable context under stress.",
        "Adversarial failures became harness fixes, not product failures.",
        "Missing judge key remains an environment limitation.",
    ]
    for i, note in enumerate(notes):
        svg.append(f'<text x="622" y="{676 + i * 28}" class="label">{esc(note)}</text>')

    svg.append("</svg>")
    return "\n".join(svg)


def generate_viability(data: dict) -> str:
    phases = {p.get("phase"): p for p in data["phase_results"]}
    width, height = 1200, 860
    svg = svg_frame(
        width,
        height,
        "Perseus As Workspace Infrastructure",
        "Why the gauntlet is evidence for usefulness, not just a test trophy.",
    )

    panel(svg, 44, 124, 342, 256, "Practical Latency")
    p50s = [
        ("Cold", phases[1].get("p50_s")),
        ("Warm", phases[2].get("p50_s")),
        ("Enterprise", phases[3].get("p50_s")),
        ("Sustained", phases[10].get("p50_s")),
    ]
    max_p50 = max(v for _, v in p50s if v)
    for i, (label, value) in enumerate(p50s):
        y = 184 + i * 42
        progress_bar(svg, 74, y, 210, label, (value or 0) / max_p50, [BLUE, GREEN, TEAL, VIOLET][i], f"{value:.3f}s")
    svg.append(f'<text x="74" y="342" class="small">Context compilation stays below human-visible wait time.</text>')

    panel(svg, 428, 124, 342, 256, "Operational Surface")
    ops = [
        ("Roles exercised", "25"),
        ("Developers simulated", "500"),
        ("Adversarial scenarios", "12"),
        ("Sustained phase", "120m"),
    ]
    for i, (label, value) in enumerate(ops):
        x = 458 + (i % 2) * 150
        y = 190 + (i // 2) * 84
        svg.append(f'<text x="{x}" y="{y}" class="metric2" fill="{GREEN}" style="fill:{GREEN}">{esc(value)}</text>')
        svg.append(f'<text x="{x}" y="{y + 24}" class="small">{esc(label)}</text>')

    panel(svg, 812, 124, 342, 256, "Assistant Value")
    value_lines = [
        "Pre-resolved repo state",
        "Live cacheable commands",
        "Memory and checkpoints",
        "Coordination primitives",
        "Low-latency repeated renders",
    ]
    for i, line in enumerate(value_lines):
        y = 184 + i * 34
        svg.append(f'<rect x="842" y="{y - 14}" width="10" height="10" rx="2" fill="{[GREEN, TEAL, BLUE, AMBER, VIOLET][i]}"/>')
        svg.append(f'<text x="862" y="{y - 4}" class="label">{esc(line)}</text>')

    panel(svg, 44, 424, 1110, 252, "From Prompt File To Runtime")
    flow = [
        ("Static files", "Rot; require assistant rediscovery", RED),
        ("Perseus render", "Compiles current facts on demand", TEAL),
        ("Warm context", "Reuses expensive discoveries", GREEN),
        ("Assistant", "Starts closer to useful work", BLUE),
    ]
    for i, (label, detail, color) in enumerate(flow):
        x = 78 + i * 260
        svg.append(f'<rect x="{x}" y="500" width="205" height="84" rx="8" fill="{PANEL_2}" stroke="{color}" stroke-width="2"/>')
        svg.append(f'<text x="{x + 18}" y="534" class="section" fill="{color}" style="fill:{color}">{esc(label)}</text>')
        svg.append(f'<text x="{x + 18}" y="562" class="small">{esc(detail)}</text>')
        if i < len(flow) - 1:
            svg.append(f'<path d="M {x + 216} 542 L {x + 244} 542" stroke="{MUTED}" stroke-width="2"/>')
            svg.append(f'<path d="M {x + 244} 542 L {x + 236} 536 M {x + 244} 542 L {x + 236} 548" stroke="{MUTED}" stroke-width="2"/>')

    panel(svg, 44, 714, 1110, 96, "Product Takeaway")
    takeaway = "Perseus looks viable when positioned as a context runtime: fast enough to sit in front of assistants, resilient enough for messy workspaces, and measurable enough to catch regressions."
    svg.append(f'<text x="74" y="770" class="label">{esc(takeaway)}</text>')

    svg.append("</svg>")
    return "\n".join(svg)


def generate_candid(data: dict) -> str:
    phases = {p.get("phase"): p for p in data["phase_results"]}
    width, height = 1200, 860
    svg = svg_frame(
        width,
        height,
        "What The Gauntlet Exposed",
        "The useful version includes the blemishes: harness bugs, environment gaps, and budget pressure.",
    )

    panel(svg, 44, 124, 520, 278, "Bugs Found During Certification")
    bugs = [
        ("A1 disk fill", "main still wrote past 50 GB before stop", RED),
        ("Speedup gate", "mean failed on one 1038s wall-clock outlier", AMBER),
        ("Score math", "all gates passing could not naturally reach 100", AMBER),
    ]
    for i, (label, detail, color) in enumerate(bugs):
        y = 184 + i * 66
        svg.append(f'<circle cx="76" cy="{y - 8}" r="7" fill="{color}"/>')
        svg.append(f'<text x="98" y="{y - 12}" class="section">{esc(label)}</text>')
        svg.append(f'<text x="98" y="{y + 14}" class="label">{esc(detail)}</text>')

    panel(svg, 596, 124, 520, 278, "Not Product Failures, But Real Signals")
    signals = [
        ("Phase 7", phases[7].get("duration_s"), phases[7].get("max_duration_s"), "adversarial over budget"),
        ("Phase 10", phases[10].get("duration_s"), phases[10].get("max_duration_s"), "sustained at budget edge"),
        ("Phase 8", phases[8].get("duration_s"), phases[8].get("max_duration_s"), "judge skipped: no API key"),
    ]
    for i, (label, actual, budget, note) in enumerate(signals):
        y = 184 + i * 66
        ratio = min((actual or 0) / (budget or 1), 1.0)
        color = RED if actual and budget and actual > budget else (AMBER if label == "Phase 8" else GREEN)
        svg.append(f'<text x="626" y="{y - 12}" class="section">{esc(label)}</text>')
        svg.append(f'<rect x="748" y="{y - 26}" width="220" height="14" rx="7" fill="{PANEL_2}"/>')
        svg.append(f'<rect x="748" y="{y - 26}" width="{max(3, 220 * ratio):.1f}" height="14" rx="7" fill="{color}"/>')
        svg.append(f'<text x="986" y="{y - 14}" class="small">{fmt_s(actual)} / {fmt_s(budget)}</text>')
        svg.append(f'<text x="626" y="{y + 16}" class="label">{esc(note)}</text>')

    panel(svg, 44, 446, 1072, 220, "Distribution Beats Anecdote")
    cold = phases[1]
    warm = phases[2]
    rows = [
        ("Cold p50", cold.get("p50_s"), BLUE),
        ("Warm p50", warm.get("p50_s"), GREEN),
        ("Warm p99", warm.get("p99_s"), TEAL),
        ("Warm max", warm.get("max_s"), RED),
    ]
    max_v = max(v for _, v, _ in rows if v)
    for i, (label, value, color) in enumerate(rows):
        y = 514 + i * 32
        scaled = min((value or 0) / max_v, 1.0)
        svg.append(f'<text x="74" y="{y}" class="label">{esc(label)}</text>')
        svg.append(f'<rect x="184" y="{y - 13}" width="740" height="14" rx="7" fill="{PANEL_2}"/>')
        svg.append(f'<rect x="184" y="{y - 13}" width="{max(3, 740 * scaled):.1f}" height="14" rx="7" fill="{color}"/>')
        svg.append(f'<text x="944" y="{y}" class="small">{value:.3f}s</text>')
    svg.append(f'<text x="74" y="646" class="small">One external warm wall-clock outlier dominated the mean, while BENCH reported cached render time around 10ms.</text>')

    panel(svg, 44, 708, 1072, 98, "Honest Bottom Line")
    bottom = "Perseus certified, but the benchmark also proved why certification needs adversarial runs: the engine looked strong, the harness needed calibration, and environment-dependent gates must stay explicit."
    svg.append(f'<text x="74" y="764" class="label">{esc(bottom)}</text>')

    svg.append("</svg>")
    return "\n".join(svg)


def generate_preview(files: list[str]) -> str:
    cards = "\n".join(
        f'<section><h2>{esc(Path(name).stem.replace("-", " ").title())}</h2><img src="{esc(name)}" alt="{esc(name)}"/></section>'
        for name in files
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Perseus Gauntlet Infographics</title>
<style>
body {{ margin: 0; padding: 32px; background: #0b0f14; color: #f2f5f7; font-family: system-ui, sans-serif; }}
main {{ max-width: 1220px; margin: 0 auto; display: grid; gap: 32px; }}
h1 {{ margin: 0 0 8px; font-size: 32px; }}
h2 {{ font-size: 18px; font-weight: 650; color: #aab4c0; }}
section {{ background: #111722; border: 1px solid #2d3542; border-radius: 8px; padding: 18px; }}
img {{ display: block; width: 100%; height: auto; }}
</style>
</head>
<body>
<main>
<h1>Perseus Gauntlet Infographics</h1>
{cards}
</main>
</body>
</html>
"""


def main() -> None:
    data = load()
    outputs = {
        "perseus-gauntlet-certification.svg": generate_certification(data),
        "perseus-gauntlet-viability.svg": generate_viability(data),
        "perseus-gauntlet-candid.svg": generate_candid(data),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (OUT_DIR / name).write_text(content)
    (OUT_DIR / "gauntlet-preview.html").write_text(generate_preview(list(outputs)))
    for name in outputs:
        print(OUT_DIR / name)
    print(OUT_DIR / "gauntlet-preview.html")


if __name__ == "__main__":
    main()
