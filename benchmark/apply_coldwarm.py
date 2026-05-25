#!/usr/bin/env python3
"""Apply cold-vs-warm benchmark results to README.md and index.html.

Reads benchmark/cold-vs-warm.json and updates:
  1. benchmark/infographic/perseus-cold-vs-warm.svg (via gen_coldwarm_svg.py)
  2. README.md — Proof section stats
  3. index.html — stats section values

Usage: python3 benchmark/apply_coldwarm.py
"""
import json, re, sys
from pathlib import Path

ROOT = Path("/workspace/perseus")
DATA = json.loads((ROOT / "benchmark/cold-vs-warm.json").read_text())
VERSION = (ROOT / "VERSION").read_text().strip()

scales = DATA["scales"]
per_query_ms = DATA["per_query_ms"]

# Find key data points
def get_scale(n):
    return scales.get(str(n), {})

scale_500 = get_scale(500)
scale_10000 = get_scale(10000)
scale_20000 = get_scale(20000)
scale_50000 = get_scale(50000)

# Best speedup
best = max(
    ((int(k), v) for k, v in scales.items() if v.get("speedup")),
    key=lambda x: x[1]["speedup"],
    default=(10000, scale_10000)
)
best_n, best_data = best
best_speedup = best_data["speedup"]
best_cold = best_data["cold"]
best_warm = best_data["warm"]

print(f"Data loaded: {len(scales)} scales, max {best_n:,} directives")
print(f"  Best: {best_n:,} → {best_speedup:,.0f}× (cold={best_cold}s, warm={best_warm}s)")
print(f"  500:  cold={scale_500.get('cold')}s, warm={scale_500.get('warm')}s, {scale_500.get('speedup')}×")
print(f"  10k:  cold={scale_10000.get('cold')}s, warm={scale_10000.get('warm')}s, {scale_10000.get('speedup')}×")

# ============================================================================
# 1. Update cold-vs-warm SVG
# ============================================================================
print("\n--- Generating SVG ---")
import subprocess
r = subprocess.run(
    [sys.executable, str(ROOT / "benchmark/infographic/gen_coldwarm_svg.py")],
    capture_output=True, text=True,
)
print(r.stdout)
if r.returncode != 0:
    print(r.stderr)

# ============================================================================
# 2. Update README.md
# ============================================================================
readme = ROOT / "README.md"
text = readme.read_text()

# Update: "40× speedup" line → new best
old_40x = re.search(r'-\s+\*\*40× speedup\*\*[^\n]*', text)
if old_40x:
    old_line = old_40x.group()
    new_line = (
        f'- **{best_speedup:,.0f}× speedup** — {best_n:,} `@query` directives render in '
        f'{best_warm:.2f}s warm (vs {best_cold:.0f}s cold) with `@cache ttl=300`. '
        f'Cache backend: local filesystem JSON lookups (one file per directive, SHA-256 keyed). '
        f'Warm render time is **constant** regardless of directive count.'
    )
    text = text.replace(old_line, new_line)
    print(f"README: Updated 40× → {best_speedup:,.0f}×")

# Update the SVG subtitle/alt text if needed (references v1.0.2)
text = text.replace(
    "Perseus v1.0.2 — Cold vs Warm Render",
    f"Perseus v{VERSION} — Cold vs Warm Render"
)

readme.write_text(text)
print("README.md updated")

# ============================================================================
# 3. Update index.html
# ============================================================================
html_path = ROOT / "index.html"
html = html_path.read_text()

# Update: "40× faster with @cache" stat
old_stat_40x = re.search(
    r'<div class="sval">40<span class="unit">×</span></div>\s*<div class="sdesc">faster with <b>@cache ttl=300</b> — 500 queries in <b>\d+\.\d+s</b> vs \d+\.\d+s cold[^<]*</div>',
    html
)
if old_stat_40x:
    old_block = old_stat_40x.group()
    new_block = (
        f'<div class="sval">{best_speedup:,.0f}<span class="unit">×</span></div>\n'
        f'        <div class="sdesc">faster with <b>@cache ttl=300</b> — '
        f'{best_n:,} queries in <b>{best_warm:.2f}s</b> vs {best_cold:.0f}s cold. '
        f'The render path becomes free.</div>'
    )
    html = html.replace(old_block, new_block)
    print(f"index.html: Updated 40× → {best_speedup:,.0f}×")

# Update the SVG alt text version
html = html.replace(
    "perseus-cold-vs-warm.svg",
    "perseus-cold-vs-warm.svg"
)
# Add cache-bust to SVG URL
html = html.replace(
    'benchmark/infographic/perseus-cold-vs-warm.svg"',
    f'benchmark/infographic/perseus-cold-vs-warm.svg?v={VERSION}"'
)

# Also update the README SVG reference with cache-bust
readme2 = ROOT / "README.md"
readme2_text = readme2.read_text()
readme2_text = readme2_text.replace(
    'benchmark/infographic/perseus-cold-vs-warm.svg)',
    f'benchmark/infographic/perseus-cold-vs-warm.svg?v={VERSION})'
)
readme2.write_text(readme2_text)

html_path.write_text(html)
print("index.html updated")

# ============================================================================
# Summary
# ============================================================================
print(f"\n{'='*60}")
print(f"Done. Updated for Perseus v{VERSION}")
print(f"  New headline: {best_speedup:,.0f}× speedup at {best_n:,} directives")
print(f"  Cold: {best_cold:.0f}s → Warm: {best_warm:.2f}s")
print(f"  Per-query cold: {per_query_ms}ms")
print(f"  Files: README.md, index.html, perseus-cold-vs-warm.svg")
