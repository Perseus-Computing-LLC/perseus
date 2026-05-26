#!/usr/bin/env python3
"""
gen_xeb_svg.py — Extreme Enterprise Benchmark SVG Infographic Generator

Reads extreme_enterprise_results.json (or the full-run variant) and produces
a multi-panel dark-theme SVG suitable for README badges, Confluence pages,
and Discord embeds.

No external graphics libraries required — pure Python string SVG generation.

Panels:
  A — Cold vs. Warm speedup (dual line, per directive count × tier 3)
  B — Concurrency throughput curve (TPS vs concurrency, warm)
  C — Regression probes bar chart (mean latency per probe)
  D — Gate scorecard (hard + soft pass/fail ring)

Usage:
    python3 infographic/gen_xeb_svg.py
    python3 infographic/gen_xeb_svg.py --input ../extreme_enterprise_results_full.json
    python3 infographic/gen_xeb_svg.py --input ../extreme_enterprise_results_full.json \
        --output perseus-xeb-infographic.svg
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_IN  = ROOT.parent / "extreme_enterprise_results.json"
DEFAULT_OUT = ROOT / "perseus-xeb-infographic.svg"

# ── Colour palette (GitHub dark) ──────────────────────────────────────────
BG          = "#0d1117"
SURFACE     = "#161b22"
BORDER      = "#30363d"
TEXT        = "#e6edf3"
TEXT_DIM    = "#8b949e"
COLD_CLR    = "#ff6b6b"   # red  — cold renders
WARM_CLR    = "#2ed573"   # green — warm renders
CONC_CLR    = "#58a6ff"   # blue  — concurrency TPS
PROBE_CLR   = "#f0883e"   # orange — regression probes
PASS_CLR    = "#3fb950"   # green — gates passing
FAIL_CLR    = "#f85149"   # red   — gates failing
SOFT_CLR    = "#d29922"   # yellow — soft gate

# ── Canvas layout ─────────────────────────────────────────────────────────
W, H        = 1000, 700
PAD         = 20
PANEL_GAP   = 12

# Panel grid: 2 × 2
PA_X, PA_Y  = PAD, PAD
PA_W, PA_H  = 460, 300

PB_X, PB_Y  = PAD + PA_W + PANEL_GAP, PAD
PB_W, PB_H  = W - PB_X - PAD, 300

PC_X, PC_Y  = PAD, PAD + PA_H + PANEL_GAP
PC_W, PC_H  = 460, H - PC_Y - PAD

PD_X, PD_Y  = PAD + PC_W + PANEL_GAP, PC_Y
PD_W, PD_H  = W - PD_X - PAD, H - PD_Y - PAD


# ── SVG primitives ────────────────────────────────────────────────────────

def _rect(x, y, w, h, fill=SURFACE, rx=8, stroke=BORDER, sw=1, opacity=1.0):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" '
            f'opacity="{opacity}"/>')

def _text(x, y, s, fill=TEXT, size=12, anchor="middle", weight="normal", family="monospace"):
    return (f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
            f'text-anchor="{anchor}" font-weight="{weight}" '
            f'font-family="{family}">{s}</text>')

def _line(x1, y1, x2, y2, stroke=BORDER, sw=1, dash=""):
    dash_attr = f'stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}" {dash_attr}/>'

def _polyline(pts: list[tuple[float, float]], stroke=COLD_CLR, sw=2.5, fill="none"):
    pts_str = " ".join(f"{round(x,1)},{round(y,1)}" for x, y in pts)
    return (f'<polyline points="{pts_str}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}" '
            f'stroke-linejoin="round" stroke-linecap="round"/>')

def _circle(cx, cy, r, fill=COLD_CLR, stroke=BG, sw=1.5):
    return f'<circle cx="{round(cx,1)}" cy="{round(cy,1)}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'

def _path_arc(cx, cy, r, start_deg, end_deg, color, sw=12):
    """SVG arc path from start_deg to end_deg (0=top, clockwise)."""
    def _pt(deg):
        rad = math.radians(deg - 90)
        return cx + r * math.cos(rad), cy + r * math.sin(rad)
    large = 1 if (end_deg - start_deg) > 180 else 0
    x1, y1 = _pt(start_deg)
    x2, y2 = _pt(end_deg)
    return (f'<path d="M {round(x1,1)} {round(y1,1)} '
            f'A {r} {r} 0 {large} 1 {round(x2,1)} {round(y2,1)}" '
            f'fill="none" stroke="{color}" stroke-width="{sw}" '
            f'stroke-linecap="round"/>')

def _panel_header(px, py, pw, title, subtitle=""):
    lines = []
    lines.append(_text(px + pw // 2, py + 22, title, size=13, weight="bold"))
    if subtitle:
        lines.append(_text(px + pw // 2, py + 38, subtitle, fill=TEXT_DIM, size=10))
    return lines


# ── Panel A: Cold vs. Warm line chart ─────────────────────────────────────

def panel_a(data: dict) -> list[str]:
    """Dual-line chart: cold and warm mean latency (ms) vs directive count, tier 3."""
    p3 = data.get("phase_3", {})
    deltas = [d for d in p3.get("deltas", []) if d.get("tier") == 3]
    deltas.sort(key=lambda d: d["n_directives"])

    lines = []
    lines.append(_rect(PA_X, PA_Y, PA_W, PA_H))
    lines += _panel_header(PA_X, PA_Y, PA_W,
                           "Cold vs. Warm Latency",
                           "tier 3 · mean render time (ms)")

    if not deltas:
        lines.append(_text(PA_X + PA_W // 2, PA_Y + PA_H // 2,
                           "No data", fill=TEXT_DIM))
        return lines

    MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 52, 16, 52, 36
    cx0 = PA_X + MARGIN_L
    cy0 = PA_Y + MARGIN_T
    cw  = PA_W - MARGIN_L - MARGIN_R
    ch  = PA_H - MARGIN_T - MARGIN_B

    # Value ranges
    all_ms = ([d["cold_mean_ms"] for d in deltas if d["cold_mean_ms"]] +
              [d["warm_mean_ms"] for d in deltas if d["warm_mean_ms"]])
    y_max = max(all_ms) * 1.15 if all_ms else 1000
    y_min = 0
    x_vals = [d["n_directives"] for d in deltas]
    x_min, x_max = x_vals[0], x_vals[-1]

    def xp(v):
        if x_max == x_min:
            return cx0 + cw // 2
        return cx0 + (v - x_min) / (x_max - x_min) * cw

    def yp(v):
        return cy0 + ch - (v - y_min) / (y_max - y_min) * ch

    # Grid lines (4)
    for i in range(5):
        gy = cy0 + i * ch // 4
        gv = y_max - i * y_max / 4
        lines.append(_line(cx0, gy, cx0 + cw, gy, stroke=BORDER, dash="4,4"))
        lines.append(_text(cx0 - 6, gy + 4, f"{int(gv)}", fill=TEXT_DIM,
                           size=9, anchor="end"))

    # X-axis labels
    for d in deltas:
        lines.append(_text(xp(d["n_directives"]), cy0 + ch + 16,
                           str(d["n_directives"]), fill=TEXT_DIM, size=9))
    lines.append(_text(cx0 + cw // 2, cy0 + ch + 30,
                       "Directive count", fill=TEXT_DIM, size=9))
    lines.append(_text(cx0 - 38, cy0 + ch // 2,
                       "ms", fill=TEXT_DIM, size=9, anchor="middle"))

    # Cold line
    cold_pts = [(xp(d["n_directives"]), yp(d["cold_mean_ms"]))
                for d in deltas if d["cold_mean_ms"] is not None]
    if cold_pts:
        lines.append(_polyline(cold_pts, stroke=COLD_CLR, sw=2.5))
        for pt in cold_pts:
            lines.append(_circle(*pt, 4, fill=COLD_CLR))

    # Warm line
    warm_pts = [(xp(d["n_directives"]), yp(d["warm_mean_ms"]))
                for d in deltas if d["warm_mean_ms"] is not None]
    if warm_pts:
        lines.append(_polyline(warm_pts, stroke=WARM_CLR, sw=2.5))
        for pt in warm_pts:
            lines.append(_circle(*pt, 4, fill=WARM_CLR))

    # Regression highlight: red band around regressions
    for d in deltas:
        if d.get("regression") and d["cold_mean_ms"] and d["warm_mean_ms"]:
            rx = xp(d["n_directives"])
            ry = min(yp(d["cold_mean_ms"]), yp(d["warm_mean_ms"])) - 4
            rh = abs(yp(d["cold_mean_ms"]) - yp(d["warm_mean_ms"])) + 8
            lines.append(_rect(rx - 8, ry, 16, rh,
                               fill=FAIL_CLR, rx=3, stroke=FAIL_CLR, sw=0, opacity=0.25))
            lines.append(_text(rx, ry - 5, "!", fill=FAIL_CLR, size=9, weight="bold"))

    # Legend
    lx = cx0 + cw - 110
    ly = cy0 + 8
    lines.append(_rect(lx - 4, ly - 2, 108, 36, fill=BG, rx=4, stroke=BORDER))
    lines.append(_line(lx, ly + 8,  lx + 18, ly + 8,  stroke=COLD_CLR, sw=2))
    lines.append(_line(lx, ly + 22, lx + 18, ly + 22, stroke=WARM_CLR, sw=2))
    lines.append(_text(lx + 22, ly + 12, "Cold", fill=COLD_CLR, size=9, anchor="start"))
    lines.append(_text(lx + 22, ly + 26, "Warm", fill=WARM_CLR, size=9, anchor="start"))

    return lines


# ── Panel B: Concurrency throughput curve ─────────────────────────────────

def panel_b(data: dict) -> list[str]:
    """TPS vs concurrency — warm, tier 3."""
    p4 = data.get("phase_4", {})
    warm = sorted(p4.get("warm", []), key=lambda r: r["n_concurrent"])

    lines = []
    lines.append(_rect(PB_X, PB_Y, PB_W, PB_H))
    lines += _panel_header(PB_X, PB_Y, PB_W,
                           "Concurrency Throughput",
                           "warm · renders per second vs concurrent agents")

    if not warm:
        lines.append(_text(PB_X + PB_W // 2, PB_Y + PB_H // 2,
                           "No data", fill=TEXT_DIM))
        return lines

    MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 52, 16, 52, 36
    cx0 = PB_X + MARGIN_L
    cy0 = PB_Y + MARGIN_T
    cw  = PB_W - MARGIN_L - MARGIN_R
    ch  = PB_H - MARGIN_T - MARGIN_B

    tps_vals = [r["throughput_renders_per_s"] for r in warm]
    conc_vals = [r["n_concurrent"] for r in warm]
    y_max = max(tps_vals) * 1.2 if tps_vals else 10
    x_min, x_max = conc_vals[0], conc_vals[-1]

    def xp(v):
        if x_max == x_min:
            return cx0 + cw // 2
        # log scale for concurrency
        log_v   = math.log(max(v, 1))
        log_min = math.log(max(x_min, 1))
        log_max = math.log(max(x_max, 1))
        if log_max == log_min:
            return cx0 + cw // 2
        return cx0 + (log_v - log_min) / (log_max - log_min) * cw

    def yp(v):
        return cy0 + ch - v / y_max * ch

    # Grid
    for i in range(5):
        gy = cy0 + i * ch // 4
        gv = y_max * (1 - i / 4)
        lines.append(_line(cx0, gy, cx0 + cw, gy, stroke=BORDER, dash="4,4"))
        lines.append(_text(cx0 - 6, gy + 4, f"{gv:.0f}", fill=TEXT_DIM,
                           size=9, anchor="end"))

    for r in warm:
        lines.append(_text(xp(r["n_concurrent"]), cy0 + ch + 16,
                           str(r["n_concurrent"]), fill=TEXT_DIM, size=9))
    lines.append(_text(cx0 + cw // 2, cy0 + ch + 30,
                       "Concurrent agents (log scale)", fill=TEXT_DIM, size=9))

    # TPS line
    tps_pts = [(xp(r["n_concurrent"]), yp(r["throughput_renders_per_s"])) for r in warm]
    lines.append(_polyline(tps_pts, stroke=CONC_CLR, sw=2.5))
    for r, pt in zip(warm, tps_pts):
        err_rate = r["errors"] / max(r["n_concurrent"], 1)
        dot_clr = FAIL_CLR if err_rate > 0.01 else CONC_CLR
        lines.append(_circle(*pt, 5, fill=dot_clr))
        # P99 band: fill between mean and p99 with translucent strip
        p99_y = yp(r["wall_ms"]["p99"]) if r["wall_ms"]["p99"] else pt[1]
        lines.append(_line(pt[0], pt[1], pt[0], p99_y,
                           stroke=CONC_CLR, sw=1.5, dash="2,2"))

    # Axis label
    lines.append(_text(cx0 - 38, cy0 + ch // 2,
                       "TPS", fill=TEXT_DIM, size=9, anchor="middle"))

    # Legend
    lx, ly = cx0 + cw - 110, cy0 + 8
    lines.append(_rect(lx - 4, ly - 2, 130, 50, fill=BG, rx=4, stroke=BORDER))
    lines.append(_line(lx, ly + 8, lx + 18, ly + 8, stroke=CONC_CLR, sw=2))
    lines.append(_text(lx + 22, ly + 12, "TPS (warm)", fill=CONC_CLR, size=9, anchor="start"))
    lines.append(_circle(lx + 9, ly + 26, 4, fill=FAIL_CLR))
    lines.append(_text(lx + 22, ly + 30, "Error rate >1%", fill=FAIL_CLR, size=9, anchor="start"))
    lines.append(_line(lx, ly + 40, lx + 18, ly + 40, stroke=CONC_CLR, sw=1.5, dash="2,2"))
    lines.append(_text(lx + 22, ly + 44, "P99 range", fill=TEXT_DIM, size=9, anchor="start"))

    return lines


# ── Panel C: Regression probes bar chart ──────────────────────────────────

def panel_c(data: dict) -> list[str]:
    """Horizontal bar chart of mean latency for each regression probe."""
    p6 = data.get("phase_6", {})
    probes_raw = p6.get("probes", {})

    PROBE_LABELS = {
        "A_tiny_cold":       "A: tiny cold (1 dir)",
        "B_massive_cold":    "B: massive cold (120 dir)",
        "C_single_shot":     "C: single-shot",
        "D_single_dir_warm": "D: 1 dir warm",
        "E_cache_miss_storm":"E: cache-miss storm",
        "F_state_a_baseline":"F: state-A baseline",
    }

    probe_data = []
    for key, label in PROBE_LABELS.items():
        entry = probes_raw.get(key, {})
        ms = entry.get("wall_ms", {}).get("mean")
        if ms is not None:
            probe_data.append({
                "key": key, "label": label, "mean_ms": ms,
                "p99": entry.get("wall_ms", {}).get("p99") or ms,
            })

    lines = []
    lines.append(_rect(PC_X, PC_Y, PC_W, PC_H))
    lines += _panel_header(PC_X, PC_Y, PC_W,
                           "Regression Probes",
                           "mean render latency (ms) — nothing hidden")

    if not probe_data:
        lines.append(_text(PC_X + PC_W // 2, PC_Y + PC_H // 2,
                           "No data", fill=TEXT_DIM))
        return lines

    MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 150, 20, 50, 24
    bx0 = PC_X + MARGIN_L
    by0 = PC_Y + MARGIN_T
    bw  = PC_W - MARGIN_L - MARGIN_R
    bh  = PC_H - MARGIN_T - MARGIN_B

    n = len(probe_data)
    bar_slot = bh / n
    bar_h = min(bar_slot * 0.55, 28)
    x_max = max(p["p99"] for p in probe_data) * 1.15

    # X-axis grid
    for i in range(5):
        gx = bx0 + i * bw // 4
        gv = x_max * i / 4
        lines.append(_line(gx, by0, gx, by0 + bh, stroke=BORDER, dash="3,3"))
        lines.append(_text(gx, by0 + bh + 14, f"{int(gv)}", fill=TEXT_DIM,
                           size=9, anchor="middle"))
    lines.append(_text(bx0 + bw // 2, by0 + bh + 26,
                       "ms", fill=TEXT_DIM, size=9))

    overhead_flagged = p6.get("overhead_detected", False)

    for i, probe in enumerate(probe_data):
        by = by0 + i * bar_slot + (bar_slot - bar_h) / 2
        bar_len = probe["mean_ms"] / x_max * bw if x_max else 0
        p99_len = probe["p99"] / x_max * bw if x_max else 0

        # Colour: baseline = dim, overhead-flagged = orange, else normal
        is_baseline = probe["key"] == "F_state_a_baseline"
        is_flagged  = overhead_flagged and probe["key"] in (
            "A_tiny_cold", "C_single_shot"
        )
        bar_fill = (TEXT_DIM if is_baseline
                    else FAIL_CLR if is_flagged
                    else PROBE_CLR)

        # P99 background (faint)
        lines.append(_rect(bx0, by, p99_len, bar_h,
                           fill=bar_fill, rx=3, stroke="none", sw=0, opacity=0.2))
        # Mean bar
        lines.append(_rect(bx0, by + bar_h * 0.15,
                           bar_len, bar_h * 0.7,
                           fill=bar_fill, rx=3, stroke="none", sw=0))

        # Label
        lines.append(_text(bx0 - 6, by + bar_h / 2 + 4,
                           probe["label"], fill=TEXT if not is_baseline else TEXT_DIM,
                           size=9, anchor="end"))
        # Value
        lines.append(_text(bx0 + bar_len + 4, by + bar_h / 2 + 4,
                           f"{probe['mean_ms']}ms",
                           fill=bar_fill, size=9, anchor="start"))

    # Overhead annotation
    if overhead_flagged:
        lines.append(_text(PC_X + PC_W // 2, PC_Y + PC_H - 6,
                           "⚠ Overhead-dominant scenarios detected",
                           fill=FAIL_CLR, size=9))
    else:
        lines.append(_text(PC_X + PC_W // 2, PC_Y + PC_H - 6,
                           "✓ No overhead-dominant scenarios",
                           fill=WARM_CLR, size=9))

    return lines


# ── Panel D: Gate scorecard ring ──────────────────────────────────────────

def panel_d(data: dict) -> list[str]:
    """Ring chart of hard + soft gate pass/fail rates plus a gate list."""
    p10 = data.get("phase_10", {})
    all_gates = p10.get("gates", [])
    hard = p10.get("hard", {})
    soft = p10.get("soft", {})

    passed_hard = hard.get("passed", 0)
    total_hard  = hard.get("total", 1)
    passed_soft = soft.get("passed", 0)
    total_soft  = soft.get("total", 1)
    overall_pass = data.get("overall_pass", False)

    lines = []
    lines.append(_rect(PD_X, PD_Y, PD_W, PD_H))
    lines += _panel_header(PD_X, PD_Y, PD_W,
                           "Gate Scorecard",
                           "hard gates block PASS · soft are advisory")

    # Outer ring — hard gates
    RING_CX = PD_X + PD_W // 2
    RING_CY = PD_Y + 75 + 70
    R_OUTER = 58
    R_INNER = 38

    # Background ring (grey)
    lines.append(_path_arc(RING_CX, RING_CY, R_OUTER, 0, 359.9, BORDER, sw=14))
    lines.append(_path_arc(RING_CX, RING_CY, R_INNER, 0, 359.9, BORDER, sw=10))

    # Hard gate arc (green/red)
    hard_deg = (passed_hard / max(total_hard, 1)) * 360
    if hard_deg > 0:
        lines.append(_path_arc(RING_CX, RING_CY, R_OUTER, 0,
                               min(hard_deg, 359.9),
                               PASS_CLR if passed_hard == total_hard else FAIL_CLR,
                               sw=14))
    # Soft gate arc (yellow)
    soft_deg = (passed_soft / max(total_soft, 1)) * 360
    if soft_deg > 0:
        lines.append(_path_arc(RING_CX, RING_CY, R_INNER, 0,
                               min(soft_deg, 359.9), SOFT_CLR, sw=10))

    # Centre text
    verdict = "PASS" if overall_pass else "FAIL"
    verdict_clr = PASS_CLR if overall_pass else FAIL_CLR
    lines.append(_text(RING_CX, RING_CY - 8, verdict,
                       fill=verdict_clr, size=16, weight="bold"))
    lines.append(_text(RING_CX, RING_CY + 12,
                       f"{passed_hard}/{total_hard} hard",
                       fill=TEXT, size=10))
    lines.append(_text(RING_CX, RING_CY + 26,
                       f"{passed_soft}/{total_soft} soft",
                       fill=TEXT_DIM, size=9))

    # Ring legend
    leg_y = RING_CY + R_OUTER + 20
    lines.append(_circle(PD_X + 20, leg_y, 5, fill=PASS_CLR))
    lines.append(_text(PD_X + 28, leg_y + 4,
                       "Hard gates", fill=TEXT, size=9, anchor="start"))
    lines.append(_circle(PD_X + 100, leg_y, 5, fill=SOFT_CLR))
    lines.append(_text(PD_X + 108, leg_y + 4,
                       "Soft gates", fill=TEXT, size=9, anchor="start"))

    # Gate list (scrollable text)
    LIST_Y = leg_y + 22
    list_h  = PD_Y + PD_H - LIST_Y - 8
    row_h   = min(18, list_h / max(len(all_gates), 1))

    # Clip to available height
    max_shown = int(list_h / row_h)
    shown = all_gates[:max_shown]
    if len(all_gates) > max_shown:
        shown = all_gates[:max_shown - 1]
        overflow = True
    else:
        overflow = False

    for i, g in enumerate(shown):
        gy = LIST_Y + i * row_h
        sev = g.get("severity", "hard")
        ok = g["pass"]
        dot_clr = (PASS_CLR if ok else FAIL_CLR) if sev == "hard" \
             else (SOFT_CLR if ok else SOFT_CLR) if sev == "soft" \
             else TEXT_DIM
        mark = "●" if sev == "hard" else "○"
        lines.append(_text(PD_X + 10, gy + row_h * 0.75,
                           mark, fill=dot_clr, size=9, anchor="start"))
        name_trunc = g["name"][:38] + ("…" if len(g["name"]) > 38 else "")
        lines.append(_text(PD_X + 22, gy + row_h * 0.75,
                           name_trunc,
                           fill=TEXT if ok else FAIL_CLR,
                           size=8, anchor="start"))
        pass_lbl = "ok" if ok else "FAIL"
        lines.append(_text(PD_X + PD_W - 8, gy + row_h * 0.75,
                           pass_lbl,
                           fill=PASS_CLR if ok else FAIL_CLR,
                           size=8, anchor="end"))

    if overflow:
        lines.append(_text(PD_X + PD_W // 2, PD_Y + PD_H - 8,
                           f"…+{len(all_gates) - max_shown + 1} more gates",
                           fill=TEXT_DIM, size=8))

    return lines


# ── Header banner ─────────────────────────────────────────────────────────

def header_banner(data: dict) -> list[str]:
    generated = data.get("generated_at_utc", "")
    dur = data.get("total_duration_s", "")
    p7 = data.get("phase_7", {})
    roi = p7.get("estimated_roi_pct", "—") if not p7.get("skipped") else "—"
    overall = "PASS" if data.get("overall_pass") else "FAIL"
    overall_clr = PASS_CLR if data.get("overall_pass") else FAIL_CLR

    lines = []
    lines.append(_rect(0, 0, W, H, fill=BG, rx=0, stroke="none"))
    # Title strip
    lines.append(_rect(0, 0, W, 0, fill=BG, rx=0, stroke="none"))  # placeholder
    title_y = H - 14
    lines.append(_text(PAD, title_y,
                       f"Perseus Extreme Enterprise Benchmark  ·  {generated}  ·  "
                       f"duration={dur}s  ·  ROI≈{roi}%  ·  overall={overall}",
                       fill=TEXT_DIM, size=9, anchor="start"))
    lines.append(_rect(W - 80, H - 26, 72, 18,
                       fill=overall_clr, rx=4, stroke="none", opacity=0.2))
    lines.append(_text(W - 44, H - 13, overall,
                       fill=overall_clr, size=11, weight="bold"))
    return lines


# ── Main SVG assembler ────────────────────────────────────────────────────

def generate(data: dict) -> str:
    parts: list[str] = []

    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
                 f'viewBox="0 0 {W} {H}" width="{W}" height="{H}">')

    # Defs: glow filter
    parts.append("""<defs>
  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="blur"/>
    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>""")

    parts += header_banner(data)
    parts += panel_a(data)
    parts += panel_b(data)
    parts += panel_c(data)
    parts += panel_d(data)

    parts.append("</svg>")
    return "\n".join(parts)


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Generate SVG infographic from XEB results JSON"
    )
    ap.add_argument("--input",  "-i", default=str(DEFAULT_IN),
                    help="Path to extreme_enterprise_results.json")
    ap.add_argument("--output", "-o", default=str(DEFAULT_OUT),
                    help="Output SVG path")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.is_file():
        print(f"[gen_xeb_svg] Input not found: {inp}")
        print("  Run the benchmark first:")
        print("    python3 benchmark/extreme_enterprise_benchmark.py --quick")
        return 1

    data = json.loads(inp.read_text())
    svg = generate(data)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    print(f"[gen_xeb_svg] SVG written → {out}  ({len(svg):,} bytes)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
