#!/usr/bin/env python3
"""
Render the Perseus Titan infographic as PNG using Pillow.
Self-contained — no system deps beyond Pillow.

Output: benchmark/infographic/perseus-titan.png (1200x1600, dark theme)
"""
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Load data ──────────────────────────────────────────────────────────
titan = json.loads(Path("/workspace/perseus/benchmark/titan_coldwarm.json").read_text())
cost  = json.loads(Path("/workspace/perseus/benchmark/titan_cost.json").read_text())

# ── Canvas ─────────────────────────────────────────────────────────────
W, H = 1200, 1600
img = Image.new("RGB", (W, H), "#0a0a1a")
draw = ImageDraw.Draw(img)

# ── Try system fonts, fall back to default ─────────────────────────────
def get_font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()

font_title   = get_font(32, bold=True)
font_head    = get_font(22, bold=True)
font_label   = get_font(14)
font_small   = get_font(12)
font_callout = get_font(18, bold=True)
font_number  = get_font(26, bold=True)

# ── Colors ─────────────────────────────────────────────────────────────
CYAN    = "#00ffff"
RED     = "#ff4444"
ORANGE  = "#ff8800"
WHITE   = "#ffffff"
GRAY    = "#888888"
DARKGRAY = "#333333"
BG2     = "#111128"

# ── Helpers ────────────────────────────────────────────────────────────
def text(x, y, s, font=font_label, fill=WHITE, anchor="lt"):
    """Draw text with optional anchor: lt, mt (mid-top), rt, lm, mm (center), rm, lb, mb, rb."""
    bbox = draw.textbbox((0, 0), s, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if anchor == "mm":
        x, y = x - tw // 2, y - th // 2
    elif anchor == "mt":
        x = x - tw // 2
    elif anchor == "rt":
        x = x - tw
    elif anchor == "rm":
        x, y = x - tw, y - th // 2
    elif anchor == "lm":
        y = y - th // 2
    elif anchor == "mb":
        x, y = x - tw // 2, y - th
    elif anchor == "rb":
        x, y = x - tw, y - th
    draw.text((x, y), s, fill=fill, font=font)

def rect(x, y, w, h, fill, radius=0):
    """Draw a rectangle."""
    if radius:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill)
    else:
        draw.rectangle([x, y, x + w, y + h], fill=fill)

def line(x1, y1, x2, y2, fill=DARKGRAY, width=1):
    draw.line([x1, y1, x2, y2], fill=fill, width=width)

def hline(y, fill=DARKGRAY):
    line(0, y, W, y, fill)

# ═══════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════
y = 30
text(W // 2, y, "Perseus Titan Benchmark", font=font_title, fill=WHITE, anchor="mt")
y += 45
text(W // 2, y, "Orientation Tax vs Pre-Resolved Context", font=font_head, fill="#a0a0ff", anchor="mt")
y += 35

# Callout bar
rect(100, y, 1000, 40, BG2, radius=6)
text(W // 2, y + 20, "3.1B tokens/year saved  •  424.7× speedup  •  $40,625/yr → $0  •  1M directives: cold abandoned, warm 31.6s",
     font=font_callout, fill=CYAN, anchor="mm")
y += 60

# ═══════════════════════════════════════════════════════════════════════
# CHART 1: Cold vs Warm (Line Chart, Log-Log)
# ═══════════════════════════════════════════════════════════════════════
chart_y = y
chart_h = 500
chart_bottom = chart_y + chart_h
margin_l = 120
margin_r = 80

text(W // 2, chart_y, "Render Time vs Scale (log-log)", font=font_head, fill=WHITE, anchor="mt")
chart_y += 40

# Chart area
plot_l = margin_l
plot_r = W - margin_r
plot_t = chart_y + 10
plot_b = chart_y + chart_h - 30
plot_w = plot_r - plot_l
plot_h = plot_b - plot_t

# Grid
scales = [("100", 100), ("1K", 1000), ("10K", 10000), ("100K", 100000), ("1M", 1000000)]
time_labels = ["0.1s", "1s", "10s", "100s", "1000s", "10000s"]
time_values = [0.1, 1, 10, 100, 1000, 10000]

def log_x(val):
    """Map scale value to x pixel (log)."""
    return plot_l + (math.log10(val) - 2) / (6 - 2) * plot_w

def log_y(val):
    """Map time value to y pixel (log)."""
    if val <= 0:
        return plot_b
    return plot_b - (math.log10(val) - math.log10(0.1)) / (math.log10(10000) - math.log10(0.1)) * plot_h

# Draw grid
for tv in time_values:
    ly = log_y(tv)
    line(plot_l, ly, plot_r, ly, DARKGRAY)
    text(plot_l - 10, ly, f"{tv}s" if tv >= 1 else f"{int(tv*1000)}ms", font=font_small, fill=GRAY, anchor="rm")

for _, sv in scales:
    lx = log_x(sv)
    line(lx, plot_t, lx, plot_b, DARKGRAY)

# Axis labels
for label, sv in scales:
    text(log_x(sv), plot_b + 20, label, font=font_small, fill=GRAY, anchor="mt")
text(W // 2, plot_b + 45, "Directives / Queries (log scale)", font=font_label, fill=GRAY, anchor="mt")
# Y-axis label (rotated text approximation)
text(15, plot_t + plot_h // 2, "Render Time (log)", font=font_label, fill=GRAY, anchor="mm")

# ── Plot cold line ─────────────────────────────────────────────────
cold_points = []
warm_points = []
for k in sorted(titan["scales"].keys(), key=int):
    v = titan["scales"][k]
    scale = v.get("scale", int(k))
    if v.get("cold") is not None:
        cold_points.append((log_x(scale), log_y(v["cold"])))
    if v.get("warm") is not None:
        warm_points.append((log_x(scale), log_y(v["warm"])))

# Cold path (red)
if len(cold_points) >= 2:
    for i in range(len(cold_points) - 1):
        x1, y1 = cold_points[i]
        x2, y2 = cold_points[i + 1]
        draw.line([x1, y1, x2, y2], fill=RED, width=3)

# Mark last cold point as ABANDONED
if cold_points:
    cx, cy = cold_points[-1]
    draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=RED)
    text(cx + 12, cy - 10, "ABANDONED", font=font_small, fill=RED, anchor="lm")
    text(cx + 12, cy + 6, "(104 min)", font=font_small, fill=RED, anchor="lm")

# Warm path (cyan)
if len(warm_points) >= 2:
    for i in range(len(warm_points) - 1):
        x1, y1 = warm_points[i]
        x2, y2 = warm_points[i + 1]
        draw.line([x1, y1, x2, y2], fill=CYAN, width=3)

# Legend
lx = plot_r - 180
ly = plot_t + 10
rect(lx, ly, 14, 14, RED)
text(lx + 20, ly + 7, "Cold LLM Path", font=font_small, fill=RED, anchor="lm")
rect(lx, ly + 22, 14, 14, CYAN)
text(lx + 20, ly + 29, "Perseus Warm", font=font_small, fill=CYAN, anchor="lm")

# ── Speedup callouts ────────────────────────────────────────────────
# Show key speedup values
speedup_annotations = [
    (10000, "219×"),
    (200000, "425×"),
]
for scale, label in speedup_annotations:
    sx = log_x(scale)
    sy = plot_t + 15
    text(sx, sy, label, font=font_small, fill=ORANGE, anchor="mt")

# ═══════════════════════════════════════════════════════════════════════
# CHART 2: Annual Cost Comparison (Bar Chart)
# ═══════════════════════════════════════════════════════════════════════
y = plot_b + 70
text(W // 2, y, "Annual API Cost — 500 Developers × 250 Days", font=font_head, fill=WHITE, anchor="mt")
y += 45

pc = cost["enterprise_annual"]["perseus_comparison"]
models_order = [
    ("claude_opus_47", "Claude\nOpus 4.7", ORANGE),
    ("claude_sonnet_46", "Claude\nSonnet 4.6", "#cc6600"),
    ("gpt5", "GPT-5", "#ff9944"),
    ("gemini_25_pro", "Gemini\n2.5 Pro", "#cc4444"),
]

bar_w = 100
bar_gap = 50
bar_max_h = 250
max_cost = 50000  # $50K ceiling

bars_start_x = (W - (len(models_order) + 1) * (bar_w + bar_gap) + bar_gap) // 2
bar_bottom = y + bar_max_h + 30

# Draw bars
for i, (key, label, color) in enumerate(models_order):
    cost_val = pc[key]["llm_api_cost_usd"]
    bar_h = int(cost_val / max_cost * bar_max_h)
    bx = bars_start_x + i * (bar_w + bar_gap)
    by = bar_bottom - bar_h

    rect(bx, by, bar_w, bar_h, color, radius=4)
    text(bx + bar_w // 2, by - 8, f"${cost_val:,.0f}", font=font_small, fill=WHITE, anchor="mb")
    text(bx + bar_w // 2, bar_bottom + 12, label, font=font_small, fill=GRAY, anchor="mt")

# Perseus bar (tiny)
px = bars_start_x + len(models_order) * (bar_w + bar_gap)
pers_h = 3
rect(px, bar_bottom - pers_h, bar_w, pers_h, CYAN, radius=2)
text(px + bar_w // 2, bar_bottom - pers_h - 8, "$0", font=font_small, fill=CYAN, anchor="mb")
text(px + bar_w // 2, bar_bottom + 12, "Perseus", font=font_small, fill=CYAN, anchor="mt")

# ═══════════════════════════════════════════════════════════════════════
# STAT CARDS
# ═══════════════════════════════════════════════════════════════════════
y = bar_bottom + 60
card_w = 280
card_h = 90
card_gap = 30
cards_x = (W - (3 * card_w + 2 * card_gap)) // 2

stats = [
    ("3.1B", "Tokens Saved / Year", CYAN),
    ("424.7×", "Max Orientation Speedup", CYAN),
    ("$40,625", "Annual Savings (Opus 4.7)", CYAN),
]

for i, (value, label, color) in enumerate(stats):
    cx = cards_x + i * (card_w + card_gap)
    rect(cx, y, card_w, card_h, BG2, radius=8)
    text(cx + card_w // 2, y + 25, value, font=font_number, fill=color, anchor="mt")
    text(cx + card_w // 2, y + 60, label, font=font_small, fill=GRAY, anchor="mt")

# ═══════════════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════════════
y = H - 60
text(W // 2, y, f"Perseus v1.0.3  •  {titan['timestamp'][:10]}  •  {titan['cpu_count']} CPUs  •  Python {titan['python']}",
     font=font_small, fill=GRAY, anchor="mt")

# ── Save ───────────────────────────────────────────────────────────────
out = Path("/workspace/perseus/benchmark/infographic/perseus-titan.png")
img.save(str(out), "PNG")
print(f"✓ Saved {out} ({W}×{H})")
print(f"  File size: {out.stat().st_size / 1024:.0f} KB")
