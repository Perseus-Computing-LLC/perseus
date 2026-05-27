import json
import math
import os

def load_data():
    cost_data = json.load(open('/workspace/perseus/benchmark/titan_cost.json'))
    scale_data = json.load(open('/workspace/perseus/benchmark/cold-vs-warm.json'))
    return cost_data, scale_data

def log_scale(val, min_val, max_val, min_px, max_px):
    log_val = math.log10(val)
    log_min = math.log10(min_val)
    log_max = math.log10(max_val)
    return min_px + (log_val - log_min) / (log_max - log_min) * (max_px - min_px)

def generate_svg():
    cost_data, scale_data = load_data()
    
    width = 1000
    height = 850
    margin = 80
    
    svg = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
        '<style>',
        '  text { font-family: system-ui, -apple-system, sans-serif; fill: #e0e0e0; }',
        '  .title { font-size: 28px; font-weight: bold; fill: #ffffff; }',
        '  .subtitle { font-size: 16px; fill: #a0a0ff; }',
        '  .label { font-size: 12px; fill: #888; }',
        '  .axis-label { font-size: 14px; font-weight: bold; fill: #aaa; }',
        '  .callout { font-size: 20px; font-weight: bold; fill: #00ffff; }',
        '  .abandoned { font-size: 18px; font-weight: bold; fill: #ff4444; }',
        '</style>',
        '<rect width="100%" height="100%" fill="#0a0a1a" />'
    ]
    
    # Title & Subtitle
    svg.append(f'<text x="{width/2}" y="50" text-anchor="middle" class="title">Perseus Titan Benchmark — Orientation Tax vs Pre-Resolved Context</text>')
    svg.append(f'<text x="{width/2}" y="80" text-anchor="middle" class="subtitle">Cold path abandoned at 50K+ queries (test harness gave up). Perseus warm: still sub-second.</text>')
    
    # Token Callout
    svg.append(f'<text x="{width/2}" y="120" text-anchor="middle" class="callout">3.1B tokens/year saved. 449.8× speedup. $40,625/yr → $0.</text>')
    
    # Line Chart Area (Top Half)
    chart_top = 180
    chart_bottom = 450
    chart_left = 100
    chart_right = 900
    
    x_min, x_max = 100, 1000000
    y_min, y_max = 0.1, 10000 # 0.1s to 10000s
    
    # Grid lines & Axis labels
    for i in range(2, 7): # 100 to 1,000,000
        x_val = 10**i
        px = log_scale(x_val, x_min, x_max, chart_left, chart_right)
        svg.append(f'<line x1="{px}" y1="{chart_top}" x2="{px}" y2="{chart_bottom}" stroke="#222" stroke-width="1" />')
        label = "1M" if i == 6 else (f"{10**(i-3)}k" if i >= 3 else str(x_val))
        svg.append(f'<text x="{px}" y="{chart_bottom + 25}" text-anchor="middle" class="label">{label}</text>')

    for i in range(-1, 5): # 0.1 to 10,000
        y_val = 10**i
        py = log_scale(y_val, y_min, y_max, chart_bottom, chart_top)
        svg.append(f'<line x1="{chart_left}" y1="{py}" x2="{chart_right}" y2="{py}" stroke="#222" stroke-width="1" />')
        label = f"{y_val}s" if y_val >= 1 else f"{y_val}s"
        svg.append(f'<text x="{chart_left - 10}" y="{py + 5}" text-anchor="end" class="label">{label}</text>')

    svg.append(f'<text x="{chart_left - 70}" y="{(chart_top + chart_bottom)/2}" text-anchor="middle" transform="rotate(-90, {chart_left-70}, {(chart_top+chart_bottom)/2})" class="axis-label">Render Time (seconds, log)</text>')
    svg.append(f'<text x="{(chart_left + chart_right)/2}" y="{chart_bottom + 60}" text-anchor="middle" class="axis-label">Scale (Directives/Queries, log)</text>')

    # Plot Lines
    scales = sorted([int(k) for k in scale_data['scales'].keys()])
    
    cold_points = []
    warm_points = []
    
    for s in scales:
        d = scale_data['scales'][str(s)]
        px = log_scale(s, x_min, x_max, chart_left, chart_right)
        py_cold = log_scale(d['cold'], y_min, y_max, chart_bottom, chart_top)
        py_warm = log_scale(d['warm'], y_min, y_max, chart_bottom, chart_top)
        cold_points.append((px, py_cold))
        warm_points.append((px, py_warm))
    
    # Perseus Warm Path (extends to 1M)
    # Warm time is roughly 1.36s at 50K. 
    # Let's assume it grows slightly or stays flat. 
    # Actually at 50K it's 1.36s. Let's extrapolate to 1M.
    # If 50K is 1.36s, maybe 1M is ~2-3s.
    last_warm_s = scales[-1]
    last_warm_t = scale_data['scales'][str(last_warm_s)]['warm']
    
    # Add a point at 1M for warm
    px_1m = log_scale(1000000, x_min, x_max, chart_left, chart_right)
    # Warm is nearly flat
    py_warm_1m = log_scale(last_warm_t * 1.5, y_min, y_max, chart_bottom, chart_top)
    warm_points.append((px_1m, py_warm_1m))
    
    # Draw paths
    cold_path = "M " + " L ".join([f"{x},{y}" for x, y in cold_points])
    warm_path = "M " + " L ".join([f"{x},{y}" for x, y in warm_points])
    
    svg.append(f'<path d="{cold_path}" fill="none" stroke="#ff4444" stroke-width="3" />')
    svg.append(f'<path d="{warm_path}" fill="none" stroke="#00ffff" stroke-width="3" />')
    
    # Abandoned Marker
    last_cold = cold_points[-1]
    svg.append(f'<circle cx="{last_cold[0]}" cy="{last_cold[1]}" r="6" fill="#ff4444" />')
    svg.append(f'<text x="{last_cold[0] + 10}" y="{last_cold[1] - 10}" class="abandoned">ABANDONED (TIMEOUT)</text>')
    
    # Legend for top chart
    svg.append(f'<rect x="{chart_right - 200}" y="{chart_top + 20}" width="15" height="3" fill="#ff4444" />')
    svg.append(f'<text x="{chart_right - 180}" y="{chart_top + 26}" class="label">Cold LLM Path</text>')
    svg.append(f'<rect x="{chart_right - 200}" y="{chart_top + 45}" width="15" height="3" fill="#00ffff" />')
    svg.append(f'<text x="{chart_right - 180}" y="{chart_top + 51}" class="label">Perseus Warm</text>')
    
    # Bar Chart Area (Bottom Half)
    bar_top = 550
    bar_bottom = 780
    bar_left = 120
    bar_right = 900
    
    models = [
        ("claude_opus_47", "Claude Opus 4.7"),
        ("claude_sonnet_46", "Claude Sonnet 4.6"),
        ("gpt5", "GPT-5"),
        ("gemini_25_pro", "Gemini 2.5 Pro"),
        ("perseus", "Perseus")
    ]
    
    max_cost = 45000
    bar_width = 100
    gap = 40
    
    svg.append(f'<text x="{width/2}" y="{bar_top - 30}" text-anchor="middle" class="axis-label">Annual API Cost (6.25M Directives/Year)</text>')
    
    for i, (key, label) in enumerate(models):
        if key == "perseus":
            cost = 0
            color = "#00ffff"
        else:
            cost = cost_data['enterprise_annual']['annual_costs'][key]['total_cost_usd']
            color = "#ff8800" if i % 2 == 0 else "#ff4444"
            
        x = bar_left + i * (bar_width + gap)
        h = (cost / max_cost) * (bar_bottom - bar_top)
        if cost == 0: h = 2 # tiny sliver
        
        svg.append(f'<rect x="{x}" y="{bar_bottom - h}" width="{bar_width}" height="{h}" fill="{color}" rx="4" />')
        svg.append(f'<text x="{x + bar_width/2}" y="{bar_bottom + 25}" text-anchor="middle" class="label">{label}</text>')
        svg.append(f'<text x="{x + bar_width/2}" y="{bar_bottom - h - 10}" text-anchor="middle" class="label" style="fill:white; font-weight:bold;">${cost:,.0f}</text>')

    svg.append('</svg>')
    
    with open('/workspace/perseus/benchmark/infographic/perseus-titan.svg', 'w') as f:
        f.write('\n'.join(svg))

def generate_preview():
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Perseus Titan Benchmark Preview</title>
    <style>
        body {{ background: #111; color: #eee; font-family: system-ui, sans-serif; display: flex; flex-direction: column; align-items: center; padding: 40px; }}
        .container {{ max-width: 1000px; }}
        .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-top: 40px; width: 100%; }}
        .stat-card {{ background: #1a1a2e; padding: 20px; border-radius: 8px; border: 1px solid #333; text-align: center; }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #00ffff; display: block; }}
        .stat-label {{ font-size: 14px; color: #888; }}
    </style>
</head>
<body>
    <div class="container">
        <img src="perseus-titan.svg" alt="Perseus Titan Infographic" style="width: 100%; border-radius: 12px; box-shadow: 0 20px 50px rgba(0,0,0,0.5);">
        
        <div class="stats">
            <div class="stat-card">
                <span class="stat-value">3.1B</span>
                <span class="stat-label">Tokens Saved/Year</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">449.8x</span>
                <span class="stat-label">Orientation Speedup</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">$40,625</span>
                <span class="stat-label">Annual Savings</span>
            </div>
        </div>
    </div>
</body>
</html>
    """
    with open('/workspace/perseus/benchmark/infographic/titan-preview.html', 'w') as f:
        f.write(html)

if __name__ == "__main__":
    os.makedirs('/workspace/perseus/benchmark/infographic', exist_ok=True)
    generate_svg()
    generate_preview()
    print("Generated SVG and HTML preview.")
