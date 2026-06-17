Create a professional infographic following these specifications:

## Image Specifications

- **Type**: Infographic
- **Layout**: dashboard
- **Style**: technical-schematic (Blueprint variant)
- **Aspect Ratio**: landscape

## Core Principles

- Follow the layout structure precisely for information architecture
- Apply style aesthetics consistently throughout
- Keep information concise, highlight keywords and core concepts
- Use ample whitespace for visual clarity
- Maintain clear visual hierarchy

## Text Requirements

- All text must match the blueprint technical style
- Main titles should be prominent and readable
- Key concepts should be visually emphasized
- Labels should be clear and appropriately sized

## Layout Guidelines

Multi-metric dashboard with KPI cards, charts, and performance indicators:
- Top banner: title and subtitle
- Left panel: scaling curve chart (sequential cold vs cached warm)
- Center: large KPI numbers with labels
- Right panel: real-world impact metrics
- Bottom bar: feature highlights
- Grid lines and measurement annotations throughout
- Color-coded status indicators (green for gains, blue for baseline)
- Big numbers for KPIs with trend arrows

## Style Guidelines

Blueprint engineering aesthetic:
- Deep blue (#1E3A5F) background with white grid lines
- White and cyan (#06B6D4) technical annotations
- Amber (#F59E0B) highlights for key metrics
- Clean geometric precision
- Technical sans-serif typography
- Dimension lines and measurement marks
- Consistent stroke weights

---

Generate the infographic based on the content below:

## PERSEUS EFFICIENCY
### Cold-Start Eliminated — Facts Before the First Prompt

### Scaling Curve (Left Panel)
Bar chart or line chart showing render time vs number of @query directives:
X-axis: 10, 50, 100, 200, 500 queries
- Sequential Cold (blue line, rising): 0.7s, 1.4s, 2.6s, 4.8s, 11.5s
- Cached Warm (green line, FLAT): 0.28s, 0.28s, 0.28s, 0.28s, 0.28s
Annotation at 500 queries: "40× FASTER"
Chart title: "Render Time vs @query Count"

### Key KPI Cards (Center Panel)
Four large-number cards in a 2×2 grid:

1. "40×" — WARM SPEEDUP
   Subtitle: "Cache makes render time constant"
   Small text: "@cache ttl=300 delivers 11.5s → 0.28s"

2. "47×" — STDOUT REDUCTION  
   Subtitle: "Runaway output capped at 256KB"
   Small text: "12MB scanner output silently truncated"

3. "1.7s" — ENTERPRISE AUDIT
   Subtitle: "500 microservices in one render"
   Small text: "722 lines, 48KB context document"

4. "539" — TEST SUITE
   Subtitle: "Tests passing at v1.0.2"
   Small text: "4 Windows bugs fixed, 0 regressions"

### Real-World Impact (Right Panel)
Two impact statements with callout styling:

"788 → 0"
Discovery calls eliminated in mega-enterprise audit
"76 → 0"  
cd-and-query operations eliminated in 9-repo cross-org snapshot

Bottom text: "The assistant opens every session already oriented."

### Feature Bar (Bottom)
Horizontal bar showing key features:
@cache ttl=N | max_query_bytes | timeout=N | parallel_queries | parallel_services | Windows fixes

Text labels:

Top title: PERSEUS EFFICIENCY
Subtitle: Cold-Start Eliminated
Chart title: Render Time vs @query Count
Chart X-axis labels: 10, 50, 100, 200, 500 queries
Chart annotation: 40× FASTER at 500 queries
Chart legend: Sequential Cold (blue), Cached Warm (green)
KPI 1: 40× WARM SPEEDUP — Cache makes render time constant
KPI 2: 47× STDOUT REDUCTION — 12MB capped at 256KB
KPI 3: 1.7s ENTERPRISE AUDIT — 500 microservices, 722 lines
KPI 4: 539 TESTS PASSING — 4 Windows bugs fixed
Impact callout 1: 788 → 0 discovery calls
Impact callout 2: 76 → 0 cd-and-query ops
Impact footer: The assistant opens every session already oriented.
Feature bar: @cache ttl=N | max_query_bytes | timeout=N | parallel | Windows
Bottom-right: perseus v1.0.2 · github.com/Perseus-Computing-LLC/perseus
