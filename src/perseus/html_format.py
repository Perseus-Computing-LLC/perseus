# ─────────────────────────────── HTML Template ────────────────────────────────
# Phase 23: Self-contained HTML output for perseus render --format html.
# Zero external dependencies — all CSS is inline, no CDN, no fonts beyond system stack.
# Design matches the perseus.observer landing page aesthetic: dark, museum-quality.

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
hr {
    border: none;
    border-top: 1px solid var(--border);
    margin: 1.5rem 0;
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


# ─────────────────────────────── Helpers ──────────────────────────────────────

def _escape_html(text: str) -> str:
    """Escape &, <, >, \", ' for safe HTML text content."""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;'))


def _heading_id(text: str) -> str:
    """Convert heading text to a URL-safe ID."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    return slug


def _is_special_start(line: str) -> bool:
    """Check if a line starts a special block (code, heading, table, quote, hr)."""
    s = line.strip()
    return (s.startswith('```') or re.match(r'^#{1,3}\s', s) or
            s.startswith('|') or s.startswith('>') or s in ('---', '***', '___'))


def _inline_markdown(text: str) -> str:
    """Convert inline markdown to HTML within already-escaped text."""
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return text


# ─────────────────────────────── Table / Services Parsers ─────────────────────

def _parse_services_table(lines: list, start: int) -> tuple[str, int]:
    """Parse a @services output table into service cards with status dots.

    Returns (html, new_index).  Consumes table lines from lines[start:].
    """
    rows: list[dict] = []
    i = start

    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith('|'):
            break
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 2:
            # Skip separator rows (e.g. |---|---|)
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
        return '', i

    cards = []
    for row in rows:
        status_lower = row['status'].lower()
        if any(w in status_lower for w in ('up', 'healthy', 'running', 'ok')):
            dot_class = 'up'
        elif any(w in status_lower for w in ('down', 'unhealthy', 'stopped', 'error', 'fail')):
            dot_class = 'down'
        else:
            dot_class = 'unknown'

        detail = ''
        if row['detail']:
            detail = f' — {_escape_html(row["detail"])}'

        cards.append(
            f'<div class="service-card">'
            f'<span class="status-dot {dot_class}"></span>'
            f'<span class="service-name">{_escape_html(row["name"])}</span>'
            f'<span class="service-detail">{_escape_html(row["status"])}{detail}</span>'
            f'</div>'
        )

    return '\n'.join(cards), i


def _render_table(table_lines: list[str]) -> str:
    """Render a markdown pipe table as HTML <table>."""
    rows = []
    header_html = ''
    is_header = True

    for line in table_lines:
        cells = [c.strip() for c in line.strip().split('|')[1:-1]]
        # Skip separator rows (|---|---|)
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


# ─────────────────────────────── Markdown → HTML ──────────────────────────────

def markdown_to_html_body(md_text: str) -> str:
    """Convert resolved Perseus markdown to HTML body content.

    Handles: headings, fenced code blocks, tables, @services cards,
    blockquotes, inline bold/code/italic, collapsible long blocks.
    """
    lines = md_text.splitlines()
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # ── Fenced code block ──
        if line.strip().startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(_escape_html(lines[i]))
                i += 1
            if i < len(lines):
                i += 1  # skip closing fence
            code_html = '\n'.join(code_lines)
            if len(code_lines) > 20:
                code_html = (
                    f'<details><summary>Code block ({len(code_lines)} lines)</summary>'
                    f'<div class="detail-content"><pre><code>{code_html}\n</code></pre></div>'
                    f'</details>'
                )
            else:
                code_html = f'<pre><code>{code_html}\n</code></pre>'
            result.append(code_html)
            continue

        # ── Heading ──
        heading_match = re.match(r'^(#{1,3})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            text = _escape_html(heading_match.group(2).strip())
            id_attr = ''
            if level == 2:
                id_attr = f' id="{_heading_id(heading_match.group(2))}"'
                result.append(f'<section{id_attr}>')
            result.append(f'<h{level}{id_attr}>{text}</h{level}>')
            i += 1
            continue

        # ── Table row ──
        if '|' in line and line.strip().startswith('|'):
            table_lines = [line]
            i += 1
            while i < len(lines) and '|' in lines[i]:
                table_lines.append(lines[i])
                i += 1
            result.append(_render_table(table_lines))
            continue

        # ── Blockquote ──
        if line.strip().startswith('>'):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                quote_lines.append(lines[i].strip()[1:].strip())
                i += 1
            quote_text = _escape_html(' '.join(quote_lines))
            result.append(f'<blockquote>{quote_text}</blockquote>')
            continue

        # ── Horizontal rule ──
        if line.strip() in ('---', '***', '___'):
            result.append('<hr>')
            i += 1
            continue

        # ── Empty line ──
        if not line.strip():
            i += 1
            continue

        # ── Paragraph ──
        para_lines = []
        while i < len(lines) and lines[i].strip() and not _is_special_start(lines[i]):
            para_lines.append(_inline_markdown(_escape_html(lines[i])))
            i += 1
        if para_lines:
            tag = 'p'
            if len(para_lines) == 1:
                result.append(f'<{tag}>{para_lines[0]}</{tag}>')
            else:
                result.append(f'<{tag}>{"<br>".join(para_lines)}</{tag}>')

    # Close any open sections
    html = '\n'.join(result)
    return html


# ─────────────────────────────── Full Document ────────────────────────────────

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
