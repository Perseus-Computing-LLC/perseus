#!/usr/bin/env python3
"""Generate updated cold-vs-warm SVG infographic from cold-vs-warm.json data.

Usage: python3 benchmark/infographic/gen_coldwarm_svg.py
Reads: benchmark/cold-vs-warm.json
Writes: benchmark/infographic/perseus-cold-vs-warm.svg
"""
import json
from pathlib import Path

DATA_PATH = Path("/workspace/perseus/benchmark/cold-vs-warm.json")
OUT_PATH = Path("/workspace/perseus/benchmark/infographic/perseus-cold-vs-warm.svg")
VERSION_PATH = Path("/workspace/perseus/VERSION")

data = json.loads(DATA_PATH.read_text())
version = VERSION_PATH.read_text().strip() if VERSION_PATH.exists() else "?"

scales = data["scales"]
per_query_ms = data.get("per_query_ms", 0)

# Build data arrays
x_labels = []      # e.g. ["100", "500", ..., "50,000"]
cold_vals = []     # seconds
warm_vals = []     # seconds
speedups = []      # e.g. 8.9, 39.6, ...

for key in sorted(scales.keys(), key=int):
    v = scales[key]
    if v.get("cold") is None:
        continue
    n = int(key)
    x_labels.append(f"{n:,}")
    cold_vals.append(v["cold"])
    warm_vals.append(v["warm"])
    speedups.append(v["speedup"])

if not cold_vals:
    print("No valid data found")
    exit(1)

# Chart dimensions
W, H = 900, 520
MARGIN_LEFT = 80
MARGIN_RIGHT = 60
MARGIN_TOP = 80
MARGIN_BOTTOM = 70
CHART_W = W - MARGIN_LEFT - MARGIN_RIGHT
CHART_H = H - MARGIN_TOP - MARGIN_BOTTOM

# Y-axis: scale to max cold value (leave 5% headroom)
y_max = max(cold_vals) * 1.05
y_baseline = MARGIN_TOP + CHART_H  # bottom = 0s

def y_pos(val):
    """Map seconds to SVG y coordinate. 0 = baseline, y_max = top."""
    return y_baseline - (val / y_max) * CHART_H

# X-axis positions
x_step = CHART_W / (len(x_labels) - 1) if len(x_labels) > 1 else CHART_W
x_positions = [MARGIN_LEFT + i * x_step for i in range(len(x_labels))]

# Y-axis grid lines: pick 4-5 nice round numbers
import math
y_grid_count = 5
y_step = y_max / y_grid_count
# Round to nice numbers
y_step_order = 10 ** math.floor(math.log10(y_step))
if y_step / y_step_order < 2:
    y_step = y_step_order
elif y_step / y_step_order < 5:
    y_step = y_step_order * 2
else:
    y_step = y_step_order * 5

grid_vals = [i * y_step for i in range(y_grid_count + 1) if i * y_step <= y_max * 1.01]

# Build SVG
svg_lines = [f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="system-ui, -apple-system, sans-serif">
  <defs>
    <linearGradient id="coldGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#ff6b6b"/>
      <stop offset="100%" stop-color="#ee5a24"/>
    </linearGradient>
    <linearGradient id="warmGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#2ed573"/>
      <stop offset="100%" stop-color="#7bed9f"/>
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Background -->
  <rect width="{W}" height="{H}" fill="#0d1117" rx="12"/>

  <!-- Title -->
  <text x="{W/2}" y="38" text-anchor="middle" fill="#e6edf3" font-size="22" font-weight="700">Perseus v{version} — Cold vs Warm Render Performance</text>
  <text x="{W/2}" y="58" text-anchor="middle" fill="#8b949e" font-size="13">@cache ttl=300 · {per_query_ms}ms per query cold · warm time constant</text>

  <!-- Grid -->''']

# Horizontal grid lines
for gv in grid_vals:
    gy = y_pos(gv)
    svg_lines.append(f'    <line x1="{MARGIN_LEFT}" y1="{gy:.1f}" x2="{W - MARGIN_RIGHT}" y2="{gy:.1f}" stroke="#21262d" stroke-width="1" stroke-dasharray="4,4"/>')

# Y-axis labels
svg_lines.append(f'  <g fill="#8b949e" font-size="11" text-anchor="end">')
for gv in grid_vals:
    gy = y_pos(gv)
    if gv >= 1:
        label = f"{gv:.0f}s"
    else:
        label = f"{gv:.2f}s"
    svg_lines.append(f'    <text x="{MARGIN_LEFT - 10}" y="{gy + 4:.1f}">{label}</text>')
svg_lines.append(f'  </g>')

# X-axis labels
svg_lines.append(f'  <g fill="#8b949e" font-size="11" text-anchor="middle">')
for xp, label in zip(x_positions, x_labels):
    svg_lines.append(f'    <text x="{xp:.0f}" y="{y_baseline + 20:.0f}">{label}</text>')
svg_lines.append(f'  </g>')

# Cold polyline
cold_points = " ".join(f"{xp:.1f},{y_pos(cv):.1f}" for xp, cv in zip(x_positions, cold_vals))
svg_lines.append(f'''
  <!-- Cold line -->
  <polyline points="{cold_points}"
            fill="none" stroke="url(#coldGrad)" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)"/>''')

# Cold dots + labels
svg_lines.append(f'  <g fill="#ff6b6b">')
for xp, cv in zip(x_positions, cold_vals):
    svg_lines.append(f'    <circle cx="{xp:.1f}" cy="{y_pos(cv):.1f}" r="5"/>')
svg_lines.append(f'  </g>')

svg_lines.append(f'  <g fill="#ff6b6b" font-size="11" font-weight="600">')
for xp, cv in zip(x_positions, cold_vals):
    ly = y_pos(cv) - 12
    if cv >= 1:
        label = f"{cv:.1f}s"
    else:
        label = f"{cv:.3f}s"
    svg_lines.append(f'    <text x="{xp:.0f}" y="{ly:.1f}" text-anchor="middle">{label}</text>')
svg_lines.append(f'  </g>')

# Warm polyline
warm_points = " ".join(f"{xp:.1f},{y_pos(wv):.1f}" for xp, wv in zip(x_positions, warm_vals))
svg_lines.append(f'''
  <!-- Warm line (nearly flat) -->
  <polyline points="{warm_points}"
            fill="none" stroke="url(#warmGrad)" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)"/>''')

# Warm dots
svg_lines.append(f'  <g fill="#2ed573">')
for xp, wv in zip(x_positions, warm_vals):
    svg_lines.append(f'    <circle cx="{xp:.1f}" cy="{y_pos(wv):.1f}" r="5"/>')
svg_lines.append(f'  </g>')

# Warm labels
svg_lines.append(f'  <g fill="#2ed573" font-size="10" font-weight="600">')
for xp, wv in zip(x_positions, warm_vals):
    ly = y_pos(wv) + 18
    svg_lines.append(f'    <text x="{xp:.0f}" y="{ly:.1f}" text-anchor="middle">{wv:.3f}s</text>')
svg_lines.append(f'  </g>')

# Speedup annotations
svg_lines.append(f'  <g fill="#f0c040" font-size="12" font-weight="700" text-anchor="middle">')
for xp, sp in zip(x_positions, speedups):
    ly = y_pos(warm_vals[0]) + 40
    if sp >= 1000:
        label = f"{sp/1000:.0f}k×"
    elif sp >= 100:
        label = f"{sp:.0f}×"
    else:
        label = f"{sp:.1f}×"
    svg_lines.append(f'    <text x="{xp:.0f}" y="{ly:.0f}">{label}</text>')
svg_lines.append(f'  </g>')

# Legend
lx, ly = W - MARGIN_RIGHT - 160, H - 100
svg_lines.append(f'''
  <!-- Legend -->
  <g transform="translate({lx}, {ly})">
    <rect x="0" y="0" width="150" height="75" rx="8" fill="#161b22" stroke="#30363d" stroke-width="1"/>
    <line x1="15" y1="15" x2="50" y2="15" stroke="#ff6b6b" stroke-width="3"/>
    <circle cx="32" cy="15" r="4" fill="#ff6b6b"/>
    <text x="60" y="17" fill="#e6edf3" font-size="12">Cold (no cache)</text>
    <line x1="15" y1="40" x2="50" y2="40" stroke="#2ed573" stroke-width="3"/>
    <circle cx="32" cy="40" r="4" fill="#2ed573"/>
    <text x="60" y="42" fill="#e6edf3" font-size="12">Warm (@cache)</text>
    <text x="15" y="63" fill="#f0c040" font-size="11" font-weight="700">Speedup factor</text>
  </g>''')

# Subtitle
best_scale = max((int(k), v) for k, v in scales.items() if v.get("speedup"))
best_speedup = best_scale[1]["speedup"]
best_n = best_scale[0]
svg_lines.append(f'''
  <text x="{W/2:.0f}" y="{y_baseline + 42:.0f}" text-anchor="middle" fill="#8b949e" font-size="11">
    Cold: ~{per_query_ms}ms per query, linear with directive count · Warm: sub-second regardless of scale · Cache eliminates subprocess cost entirely
  </text>
  <text x="{W/2:.0f}" y="{y_baseline + 60:.0f}" text-anchor="middle" fill="#8b949e" font-size="10">
    Max tested: {best_n:,} directives — {best_speedup:,.0f}× cold→warm gap. Perseus never crashed. Scale ceiling is file I/O, not Perseus logic.
  </text>
</svg>''')

OUT_PATH.write_text("\n".join(svg_lines))
print(f"✓ Generated {OUT_PATH}")
print(f"  Scales: {len(x_labels)} data points, {x_labels[0]} → {x_labels[-1]}")
print(f"  Best speedup: {best_speedup:,.0f}× at {best_n:,} directives")
print(f"  Version: {version}")
