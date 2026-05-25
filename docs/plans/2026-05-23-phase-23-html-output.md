# Perseus HTML Output — Implementation Plan (Phase 23)

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add `perseus render --format html` so Perseus can output self-contained HTML dashboards instead of plain markdown.

**Architecture:** A new `html_format.py` module that sits after the resolution pipeline. Directives resolve exactly as they do today — the HTML formatter wraps their results in semantic HTML containers and embeds everything in a self-contained dark-theme document. Zero new dependencies.

**Tech Stack:** Python 3.10+, stdlib only, inline CSS (no CDN).

**Design decisions resolved before handoff:**
- **No Jinja2, no templating library.** The HTML template lives as a Python f-string constant. `perseus.py` is a single file — the template comes with it.
- **Dark theme matches landing page.** Same color palette, same typography (system font stack), same "museum plate" aesthetic where it fits.
- **Self-contained.** No external CSS/JS/fonts. The file opens in any browser, offline.
- **Post-processing approach.** Resolve directives as markdown first, then smart-convert to HTML. This keeps the render pipeline unchanged — no risk of breaking existing markdown output.
- **@services gets special treatment.** The `@services` block is parsed into `<div class="service-card">` elements with green/red status dots. This is the highest-value visual upgrade.
- **Line-count assertion.** The generated artifact must stay under 11,200 lines. Baseline is ~10,600. HTML template adds ~200 lines of CSS + ~150 lines of Python. Budget: 300-400 lines net.
- **Tests before build.** Write the test suite first, verify it fails, then implement. Don't touch `perseus.py` until all tests pass against `src/` modules.

---

## Files Overview

| Action | File | Purpose |
|---|---|---|
| **Create** | `src/perseus/html_format.py` | HTML template, CSS, markdown→HTML converter |
| **Create** | `tests/test_html_format.py` | Test suite: template output, directive wrapping, self-contained check |
| **Modify** | `src/perseus/cli.py` | Add `--format html` to render command |
| **Modify** | `src/perseus/renderer.py` | Add `render_source_html()` entry point |
| **Modify** | `scripts/build.py` | Add `src/perseus/html_format.py` to MODULE_ORDER |
| **Modify** | `ROADMAP.md` | Add Phase 23 entry |

---

### Task 1: Create HTML template module stub

**Objective:** Create the module file with the HTML template and CSS, before any integration.

**Files:**
- Create: `src/perseus/html_format.py`

**Step 1: Write the HTML CSS constant**

```python
# ─────────────────────────────── HTML Template ────────────────────────────────

_HTML_CSS = """\
:root {
    --bg: #0f0f0f;
    --surface: #1a1a1a;
    --border: #2a2a2a;
    --text: #e0e0e0;
    --text-dim: #888;
    --accent: #c9a96e;
    --green: #4caf50;
    --red: #e53935;
    --amber: #ffa726;
    --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --mono: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    line-height: 1.6;
    padding: 2rem;
    max-width: 960px;
    margin: 0 auto;
}
header {
    text-align: center;
    padding: 2rem 0 3rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 2rem;
}
header h1 {
    font-size: 2rem;
    font-weight: 300;
    letter-spacing: 0.05em;
    color: var(--accent);
}
header time {
    display: block;
    margin-top: 0.5rem;
    color: var(--text-dim);
    font-size: 0.85rem;
}
section { margin-bottom: 2.5rem; }
section h2 {
    font-size: 1.1rem;
    font-weight: 500;
    color: var(--accent);
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.4rem;
    margin-bottom: 1rem;
}
section h3 {
    font-size: 1rem;
    font-weight: 500;
    margin: 1rem 0 0.5rem;
    color: var(--text);
}
p { margin-bottom: 0.6rem; }
pre {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1rem;
    overflow-x: auto;
    font-family: var(--mono);
    font-size: 0.85rem;
    line-height: 1.5;
    margin-bottom: 0.8rem;
}
code {
    font-family: var(--mono);
    font-size: 0.9em;
    background: var(--surface);
    padding: 0.15em 0.35em;
    border-radius: 3px;
}
pre code { background: none; padding: 0; }
table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1rem;
}
th, td {
    text-align: left;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border);
}
th {
    font-weight: 500;
    color: var(--text-dim);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.service-card {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.5rem 0.75rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    margin-bottom: 0.4rem;
}
.status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}
.status-dot.up { background: var(--green); }
.status-dot.down { background: var(--red); }
.status-dot.unknown { background: var(--amber); }
.service-name { font-weight: 500; }
.service-detail { color: var(--text-dim); font-size: 0.85rem; margin-left: auto; }
blockquote {
    border-left: 3px solid var(--accent);
    padding: 0.5rem 1rem;
    margin: 0.8rem 0;
    color: var(--text-dim);
    font-style: italic;
}
details { margin-bottom: 0.5rem; }
details summary {
    cursor: pointer;
    padding: 0.4rem 0;
    color: var(--accent);
    font-weight: 500;
}
details summary:hover { color: var(--text); }
details .detail-content {
    padding: 0.5rem 0 0.5rem 1rem;
    border-left: 1px solid var(--border);
}
footer {
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--border);
    text-align: center;
    color: var(--text-dim);
    font-size: 0.8rem;
}
@media (max-width: 600px) {
    body { padding: 1rem; }
    header h1 { font-size: 1.5rem; }
}
"""
```

**Step 2: Write the document wrapper function**

```python
def html_document(body: str, title: str, timestamp: str, version: str) -> str:
    """Wrap body HTML in a full self-contained document."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_escape_html(title)} — Perseus</title>
<meta name="generator" content="Perseus v{version}">
<style>
{_HTML_CSS}
</style>
</head>
<body>
<header>
  <h1>{_escape_html(title)}</h1>
  <time>Resolved {_escape_html(timestamp)}</time>
</header>
{body}
<footer>Generated by Perseus v{version}</footer>
</body>
</html>"""
```

**Step 3: Write the `_escape_html` helper**

```python
def _escape_html(text: str) -> str:
    """Escape &, <, >, \", ' for safe HTML text content."""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;'))
```

**Step 4: Commit**

```bash
git add src/perseus/html_format.py
git commit -m "feat(html): stub html_format.py module with template, CSS, and helpers"
```

---

### Task 2: Write markdown-to-HTML body converter

**Objective:** Convert resolved markdown output to semantic HTML. Preserve structure: headings, code blocks, tables, blockquotes — and detect `@services` output to render service cards.

**Files:**
- Modify: `src/perseus/html_format.py`

**Step 1: Write the heading-to-ID helper**

```python
def _heading_id(text: str) -> str:
    """Convert heading text to a URL-safe ID."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    return slug
```

**Step 2: Write the markdown-to-HTML body converter**

This function takes the resolved markdown, splits into sections by headings, and converts each section to appropriate HTML. It has special handling for `@services` blocks (detected by the "Service | Status | Detail" table pattern) and wraps long content in `<details>` elements.

```python
def markdown_to_html_body(md_text: str) -> str:
    """Convert resolved Perseus markdown to HTML body content.
    
    Handles:
    - Headings (# → h1, ## → h2, ### → h3)
    - Fenced code blocks (``` → <pre><code>)
    - Tables (pipe tables → <table>)
    - @services output (detected by table pattern → service cards)
    - Blockquotes (> → <blockquote>)
    - Long pre blocks (>20 lines) → wrapped in <details>
    - Inline code (` → <code>)
    - Bold (** → <strong>)
    """
    import re
    lines = md_text.splitlines()
    result: list[str] = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Fenced code block
        if line.strip().startswith('```'):
            fence = line.strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(_escape_html(lines[i]))
                i += 1
            if i < len(lines):
                i += 1  # skip closing fence
            code_html = '\n'.join(code_lines)
            if len(code_lines) > 20:
                code_html = f'<details><summary>Code block ({len(code_lines)} lines)</summary><div class="detail-content"><pre><code>{code_html}\n</code></pre></div></details>'
            else:
                code_html = f'<pre><code>{code_html}\n</code></pre>'
            result.append(code_html)
            continue
        
        # Heading
        heading_match = re.match(r'^(#{1,3})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            text = _escape_html(heading_match.group(2).strip())
            id_attr = f' id="{_heading_id(heading_match.group(2))}"' if level == 2 else ''
            result.append(f'<h{level}{id_attr}>{text}</h{level}>')
            i += 1
            
            # Check if following lines are a @services table
            if text.lower() in ('services', 'what\'s running', 'service status'):
                result.append(_parse_services_table(lines, i))
            continue
        
        # Table row detection
        if '|' in line and line.strip().startswith('|'):
            table_lines = [line]
            i += 1
            while i < len(lines) and '|' in lines[i]:
                table_lines.append(lines[i])
                i += 1
            result.append(_render_table(table_lines))
            continue
        
        # Blockquote
        if line.strip().startswith('>'):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                quote_lines.append(lines[i].strip()[1:].strip())
                i += 1
            quote_text = _escape_html(' '.join(quote_lines))
            result.append(f'<blockquote>{quote_text}</blockquote>')
            continue
        
        # Horizontal rule
        if line.strip() in ('---', '***', '___'):
            result.append('<hr>')
            i += 1
            continue
        
        # Empty line
        if not line.strip():
            i += 1
            continue
        
        # Regular paragraph — collect until blank line or special start
        para_lines = []
        while i < len(lines) and lines[i].strip() and not _is_special_start(lines[i]):
            para_lines.append(_inline_markdown(_escape_html(lines[i])))
            i += 1
        if para_lines:
            result.append(f'<p>{"<br>".join(para_lines) if len(para_lines) > 1 else para_lines[0]}</p>')
    
    return '\n'.join(result)


def _is_special_start(line: str) -> bool:
    """Check if a line starts a special block (code, heading, table, quote, hr)."""
    import re
    s = line.strip()
    return (s.startswith('```') or re.match(r'^#{1,3}\s', s) or
            s.startswith('|') or s.startswith('>') or s in ('---', '***', '___'))


def _inline_markdown(text: str) -> str:
    """Convert inline markdown to HTML within already-escaped text."""
    import re
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return text
```

**Step 3: Write the @services table parser**

```python
def _parse_services_table(lines: list[str], start: int) -> str:
    """Parse a @services output table into service cards with status dots.
    
    Expected format:
    | Service | Status | Detail |
    |---|---|---|
    | mongo-dev | Up | 4h 12m |
    """
    import re
    rows: list[dict] = []
    i = start
    
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith('|'):
            break
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 2:
            # Skip separator row
            if all(re.match(r'^-{2,}$', c) for c in cells if c):
                i += 1
                continue
            rows.append({
                'name': cells[0] if len(cells) > 0 else '',
                'status': cells[1] if len(cells) > 1 else '',
                'detail': cells[2] if len(cells) > 2 else ''
            })
        i += 1
    
    if not rows:
        return ''
    
    cards = []
    for row in rows:
        status_lower = row['status'].lower()
        if 'up' in status_lower or 'healthy' in status_lower or 'running' in status_lower:
            dot_class = 'up'
        elif 'down' in status_lower or 'unhealthy' in status_lower or 'stopped' in status_lower:
            dot_class = 'down'
        else:
            dot_class = 'unknown'
        
        cards.append(
            f'<div class="service-card">'
            f'<span class="status-dot {dot_class}"></span>'
            f'<span class="service-name">{_escape_html(row["name"])}</span>'
            f'<span class="service-detail">{_escape_html(row["status"])}'
            + (f' — {_escape_html(row["detail"])}' if row['detail'] else '') +
            f'</span>'
            f'</div>'
        )
    
    return '\n'.join(cards)


def _render_table(table_lines: list[str]) -> str:
    """Render a markdown pipe table as HTML."""
    rows = []
    header_html = ''
    is_header = True
    
    for line in table_lines:
        cells = [c.strip() for c in line.strip().split('|')[1:-1]]
        # Skip separator rows
        if all(c.replace('-', '').replace(':', '').strip() == '' for c in cells if c):
            is_header = False
            continue
        if is_header and cells:
            header_html = '<thead><tr>' + ''.join(
                f'<th>{_escape_html(c)}</th>' for c in cells
            ) + '</tr></thead>'
            is_header = False
        elif cells:
            rows.append('<tr>' + ''.join(
                f'<td>{_inline_markdown(_escape_html(c))}</td>' for c in cells
            ) + '</tr>')
    
    if not rows:
        return ''
    
    return f'<table>{header_html}<tbody>{"".join(rows)}</tbody></table>'
```

**Step 4: Commit**

```bash
git add src/perseus/html_format.py
git commit -m "feat(html): add markdown-to-HTML body converter with @services card support"
```

---

### Task 3: Add `render_source_html()` entry point to renderer

**Objective:** Add a function to the renderer that calls `render_source()` for markdown resolution, then pipes the result through `html_format.py` to produce a full HTML document.

**Files:**
- Modify: `src/perseus/renderer.py`

**Step 1: Add the HTML render function**

At the end of `src/perseus/renderer.py`, after `render_source()`, add:

```python
def render_source_html(
    source_text: str,
    cfg: dict,
    workspace: Path | None = None,
    title: str = "Workspace Context",
) -> str:
    """Resolve a @perseus source document and return self-contained HTML.
    
    Internally calls render_source() for markdown resolution, then converts
    the resolved markdown to semantic HTML using the built-in template.
    """
    from perseus.html_format import html_document, markdown_to_html_body
    
    md_output = render_source(source_text, cfg, workspace)
    body = markdown_to_html_body(md_output)
    
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    version = _PERSEUS_VERSION
    
    return html_document(body, title, timestamp, version)
```

**Note:** The cross-module import `from perseus.html_format import ...` will be stripped by `build.py` (it matches the `INTERNAL_IMPORT_RE` pattern), so the names will be available from the concatenated file.

**Step 2: Commit**

```bash
git add src/perseus/renderer.py
git commit -m "feat(html): add render_source_html() entry point using html_format module"
```

---

### Task 4: Add `--format` flag to CLI render command

**Objective:** Wire the `--format html` flag so `perseus render --format html source.md` outputs HTML.

**Files:**
- Modify: `src/perseus/cli.py`

**Step 1: Add `--format` argument to render parser**

In `src/perseus/cli.py`, find the render parser definition (around line 13-18) and add the format flag:

```python
p_render = sub.add_parser("render", help="Render a @perseus source file")
p_render.add_argument("source", help="Path to .md file with @perseus header")
p_render.add_argument(
    "--output", "-o", default=None, metavar="FILE",
    help="Write rendered output to FILE instead of stdout",
)
p_render.add_argument(
    "--format", "-f", default="md", choices=["md", "html"],
    help="Output format: md (markdown, default) or html (self-contained dashboard)",
)
```

**Step 2: Update the render command handler**

Find the render command handler in the `main()` function (search for `if args.command == "render"`). Update it to call `render_source_html()` when `--format html`:

The current handler looks something like:
```python
if args.command == "render":
    source = Path(args.source)
    text = source.read_text()
    output = render_source(text, config, source.parent)
    ...
```

Update to:
```python
if args.command == "render":
    source = Path(args.source)
    text = source.read_text()
    fmt = getattr(args, 'format', 'md')
    if fmt == 'html':
        title = source.stem.replace('-', ' ').replace('_', ' ').title()
        output = render_source_html(text, config, source.parent, title=title)
    else:
        output = render_source(text, config, source.parent)
    ...
```

**Step 3: Update smart output extension in CLI**

When `--format html` and no explicit `--output` is given, the default output file should be `.html` instead of `.md`. The watch command (if using render internally) should also respect format when inferring the output extension.

```python
# In the render handler, after computing output path:
if args.output:
    out_path = Path(args.output)
elif fmt == 'html':
    out_path = source.parent / f"{source.stem}.html"
else:
    out_path = None  # stdout

if out_path:
    out_path.write_text(output)
    print(f"✓ wrote {out_path}", file=sys.stderr)
else:
    print(output)
```

**Step 4: Commit**

```bash
git add src/perseus/cli.py
git commit -m "feat(html): add --format html flag to render command"
```

---

### Task 5: Register new module in build script

**Objective:** Add `html_format.py` to the build concatenation order so it's included in `perseus.py`.

**Files:**
- Modify: `scripts/build.py`

**Step 1: Add to MODULE_ORDER**

In `scripts/build.py`, add the new module before `cli.py` (since CLI references it) and after `renderer.py` (since renderer imports from it — wait, renderer imports from html_format, so html_format must come BEFORE renderer).

Actually: `renderer.py` imports from `html_format`, so `html_format.py` must be listed BEFORE `renderer.py` in MODULE_ORDER. And `cli.py` also uses it. So:

```python
MODULE_ORDER = [
    "src/perseus/__init__.py",
    "src/perseus/config.py",
    "src/perseus/registry.py",
    "src/perseus/redaction.py",
    "src/perseus/audit.py",
    "src/perseus/directives/env.py",
    "src/perseus/directives/include.py",
    "src/perseus/directives/read.py",
    "src/perseus/directives/query.py",
    "src/perseus/directives/agent.py",
    "src/perseus/directives/skills.py",
    "src/perseus/directives/waypoint.py",
    "src/perseus/directives/session.py",
    "src/perseus/directives/services.py",
    "src/perseus/directives/misc.py",
    "src/perseus/html_format.py",     # ← NEW — before renderer (renderer imports from it)
    "src/perseus/renderer.py",
    "src/perseus/checkpoint.py",
    "src/perseus/memory.py",
    "src/perseus/inbox.py",
    "src/perseus/agora.py",
    "src/perseus/pythia.py",
    "src/perseus/lsp.py",
    "src/perseus/serve.py",
    "src/perseus/cli.py",
]
```

**Step 2: Update BASELINE_LINES**

The baseline should be updated after the first successful build with all modules. For now, bump by ~400 to accommodate the new module:

```python
BASELINE_LINES = 10900  # was 10494; Phase 23 adds ~400 lines for HTML format
```

(Will be calibrated precisely after first build.)

**Step 3: Regenerate artifact**

```bash
python scripts/build.py
python -m pytest tests/ -q
```

**Step 4: Commit**

```bash
git add scripts/build.py perseus.py
git commit -m "feat(html): register html_format.py in build order and regenerate"
```

---

### Task 6: Write the test suite

**Objective:** Test the HTML output end-to-end: template is self-contained, directives render to correct HTML, services get status cards, the file opens in a browser.

**Files:**
- Create: `tests/test_html_format.py`

**Step 1: Write failing tests**

```python
"""Tests for HTML output format (Phase 23)."""
import pytest
import re
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────

def _render_html(text: str, title: str = "Test Context") -> str:
    """Render a @perseus source to HTML using the HTML format pipeline."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.perseus.renderer import render_source_html
    from src.perseus.config import load_config
    
    cfg = load_config(Path("/tmp/perseus-test"))
    return render_source_html(text, cfg, Path("/tmp/perseus-test"), title=title)


# ── Template Tests ───────────────────────────────────────────────────

def test_html_output_is_valid_html5():
    """HTML output must have DOCTYPE, html, head, body tags."""
    html = _render_html("@perseus v0.4\n\n# Hello\n\nworld.")
    assert "<!DOCTYPE html>" in html
    assert "<html lang=\"en\">" in html
    assert "</html>" in html
    assert "<head>" in html
    assert "</head>" in html
    assert "<body>" in html
    assert "</body>" in html


def test_html_output_is_self_contained():
    """HTML must not reference external resources (no CDN, no external fonts)."""
    html = _render_html("@perseus v0.4\n\n# Test\n\ncontent.")
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert "cdn." not in html.lower()
    # CSS must be inline in a <style> tag
    assert "<style>" in html


def test_html_output_escapes_user_content():
    """User content with HTML special chars must be escaped."""
    html = _render_html("@perseus v0.4\n\n<script>alert('xss')</script>")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_html_output_includes_version():
    """Generated HTML must include the Perseus version."""
    html = _render_html("@perseus v0.4\n\n# Test")
    assert "Perseus v" in html


def test_html_output_includes_timestamp():
    """Generated HTML must include a resolution timestamp."""
    html = _render_html("@perseus v0.4\n\n# Test")
    assert "Resolved" in html
    assert "UTC" in html


# ── Markdown → HTML Tests ─────────────────────────────────────────────

def test_heading_conversion():
    html = _render_html("@perseus v0.4\n\n# Top Heading\n\n## Section\n\ntext")
    assert "<h1>Top Heading</h1>" in html
    assert '<h2 id="section">Section</h2>' in html


def test_code_block_conversion():
    html = _render_html("@perseus v0.4\n\n```\nprint('hello')\n```")
    assert '<pre><code>print' in html
    assert "hello" in html


def test_long_code_blocks_are_collapsible():
    lines = "\n".join(f"line{i}" for i in range(30))
    html = _render_html(f"@perseus v0.4\n\n```\n{lines}\n```")
    assert "<details>" in html
    assert "<summary>" in html


def test_table_conversion():
    html = _render_html("@perseus v0.4\n\n| A | B |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html


def test_blockquote_conversion():
    html = _render_html("@perseus v0.4\n\n> This is wisdom.")
    assert "<blockquote>" in html


def test_bold_conversion():
    html = _render_html("@perseus v0.4\n\n**bold text** here")
    assert "<strong>bold text</strong>" in html


def test_inline_code_conversion():
    html = _render_html("@perseus v0.4\n\nUse `perseus render` command.")
    assert "<code>perseus render</code>" in html


# ── @services HTML Tests ──────────────────────────────────────────────

def test_services_renders_as_cards():
    src = """@perseus v0.4

## Services
@services
  - name: mongo-dev
    url: http://localhost:27017/
"""
    html = _render_html(src)
    # Should produce service-card divs with status dots
    assert '<div class="service-card">' in html
    assert '<span class="status-dot' in html
    assert 'mongo-dev' in html


# ── CLI Integration Tests ─────────────────────────────────────────────

def test_cli_help_shows_format_flag():
    """perseus render --help must document the --format flag."""
    import subprocess
    result = subprocess.run(
        ["python", "perseus.py", "render", "--help"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent)
    )
    assert "--format" in result.stdout
    assert "html" in result.stdout


# ── Edge Case Tests ──────────────────────────────────────────────────

def test_empty_source_still_produces_valid_html():
    """A minimal @perseus source with no content still produces valid HTML shell."""
    html = _render_html("@perseus v0.4\n")
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html


def test_no_xss_in_directive_output():
    """Directive output containing HTML must be escaped."""
    html = _render_html("@perseus v0.4\n\n@query echo '<img src=x onerror=alert(1)>'\n")
    assert "onerror" not in html or "&lt;img" in html
```

**Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_html_format.py -v
# Expected: all FAIL — module not integrated yet
```

**Step 3: Commit**

```bash
git add tests/test_html_format.py
git commit -m "test(html): add HTML format test suite (22 tests)"
```

---

### Task 7: Run full test suite and fix any integration failures

**Objective:** After all modules are integrated and artifact regenerated, run the full test suite to catch regressions.

**Step 1: Run full suite**

```bash
python scripts/build.py
python -m pytest tests/ -q
```

**Step 2: Fix any failures**

Common integration issues:
- `html_format.py` not in MODULE_ORDER → add it
- `render_source_html` not found → check function name, import path
- `_PERSEUS_VERSION` not in scope → add `from perseus.__init__ import` or inline version
- Generated `perseus.py` line count exceeds baseline → update BASELINE_LINES

**Step 3: Commit**

```bash
git add scripts/build.py perseus.py
git commit -m "fix(html): integration fixes, regenerated artifact"
```

---

### Task 8: Update ROADMAP.md

**Objective:** Add Phase 23 to the roadmap.

**Files:**
- Modify: `ROADMAP.md`

**Step 1: Add Phase 23 entry**

Find the last phase entry and add:

```markdown
| 23 | HTML output | ✅ | `perseus render --format html` — self-contained dark-theme dashboard. @services → status cards, code blocks → `<pre>`, long output collapsible. Zero new deps. |
```

**Step 2: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: add Phase 23 (HTML output) to ROADMAP"
```

---

## Executor Flags

1. **html_format.py must be BEFORE renderer.py in MODULE_ORDER.** Renderer imports from html_format — if the order is wrong, `render_source_html()` won't find `html_document` and `markdown_to_html_body`.

2. **Don't edit perseus.py directly.** All changes go in `src/perseus/`. Regenerate with `python scripts/build.py`. The artifact is committed — verify `git diff perseus.py` before committing.

3. **Line count assertion matters.** The existing test `test_release_build_produces_tarball` runs `ast.parse()` on the generated artifact. If the artifact breaks syntax, CI fails. Run tests after every build.

4. **Cross-module imports are stripped by build.py.** When `renderer.py` says `from perseus.html_format import ...`, build.py strips that line. The names `html_document`, `markdown_to_html_body` must be defined BEFORE `render_source_html` in the concatenated file — that's why `html_format.py` comes first in MODULE_ORDER.

5. **CSS is a Python string constant — no newline issues.** The `_HTML_CSS` triple-quoted string contains `\` at line ends. Ensure no trailing whitespace after the `\` — it will silently concatenate or break.

6. **`_PERSEUS_VERSION` must be accessible in `renderer.py`.** It's defined in `__init__.py` (which comes first in build order) and is a module-level variable. Since everything is concatenated into one file, it's in scope.

---

## Verification Checklist

- [ ] `python -m pytest tests/test_html_format.py -v` — all 22 tests pass
- [ ] `python -m pytest tests/ -q` — full suite passes (573+ tests)
- [ ] `python perseus.py render --help` — shows `--format {md,html}`
- [ ] `python perseus.py render examples/local-cli/.perseus/context.md --format html -o /tmp/test.html` — produces valid HTML
- [ ] Open `/tmp/test.html` in a browser — renders correctly with dark theme
- [ ] HTML has no external references — `grep "http"` returns nothing in the body
- [ ] `git diff perseus.py` shows only expected additions (no manual edits)
