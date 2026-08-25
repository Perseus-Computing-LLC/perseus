#!/usr/bin/env python3
"""Verify the published Perseus Vault MCP reference mount."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


_REQUIRED_FILES = {
    'index.html',
    'mcp-tools.html',
    'sourcey.css',
    'sourcey.js',
    'search-index.json',
    'sitemap.xml',
    'llms.txt',
    'llms-full.txt',
    'metadata.json',
    'mcp.raw.json',
    'mcp.render.json',
    'publication.json',
    'README.md',
}
_ROUTE = '/vault/mcp-reference/'
_TOOLS_ROUTE = f'{_ROUTE}mcp-tools.html'


def _read_json(path: Path, errors: list[str]) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f'{path.name}: invalid JSON ({exc})')
        return {}
    if not isinstance(value, dict):
        errors.append(f'{path.name}: expected a JSON object')
        return {}
    return value


def validate(repo_root: Path) -> list[str]:
    errors: list[str] = []
    route = repo_root / 'vault' / 'mcp-reference'
    if not route.is_dir():
        return [f'missing route directory: {route}']

    names = {path.name for path in route.iterdir() if path.is_file()}
    missing = sorted(_REQUIRED_FILES - names)
    if missing:
        errors.append(f'missing route files: {", ".join(missing)}')
    if not (route / '_og' / 'mcp-tools.png').is_file():
        errors.append('missing route asset: _og/mcp-tools.png')

    metadata = _read_json(route / 'metadata.json', errors)
    publication = _read_json(route / 'publication.json', errors)
    raw = _read_json(route / 'mcp.raw.json', errors)
    rendered = _read_json(route / 'mcp.render.json', errors)

    raw_bytes = (route / 'mcp.raw.json').read_bytes() if (route / 'mcp.raw.json').is_file() else b''
    expected_raw_sha = metadata.get('raw_snapshot_sha256')
    if expected_raw_sha and sha256(raw_bytes).hexdigest() != expected_raw_sha:
        errors.append('mcp.raw.json: SHA-256 differs from metadata.json')

    raw_tools = raw.get('tools', [])
    rendered_tools = rendered.get('tools', [])
    raw_names = [item.get('name') for item in raw_tools if isinstance(item, dict)]
    rendered_names = [item.get('name') for item in rendered_tools if isinstance(item, dict)]
    tool_count = metadata.get('tool_count')
    if not isinstance(tool_count, int) or tool_count <= 0:
        errors.append('metadata.json: tool_count must be a positive integer')
    elif len(raw_names) != tool_count or len(rendered_names) != tool_count:
        errors.append('snapshot tool counts do not match metadata.json')
    if raw_names != rendered_names:
        errors.append('raw and rendered snapshots do not preserve the ordered tool set')
    if len(raw_names) != len(set(raw_names)) or len(rendered_names) != len(set(rendered_names)):
        errors.append('snapshot tool names are not unique')

    html = (route / 'mcp-tools.html').read_text(errors='replace') if (route / 'mcp-tools.html').is_file() else ''
    operation_ids = re.findall(r'id="operation-([^"]+)"', html)
    if isinstance(tool_count, int) and len(operation_ids) != tool_count:
        errors.append('mcp-tools.html operation count does not match metadata.json')
    if len(operation_ids) != len(set(operation_ids)):
        errors.append('mcp-tools.html contains duplicate operation IDs')

    if publication.get('publication_path') != _ROUTE:
        errors.append('publication.json: publication_path is not the mounted route')
    if publication.get('source_commit') != metadata.get('source_commit'):
        errors.append('publication.json and metadata.json disagree on source_commit')
    run = publication.get('source_workflow_run', {})
    if run.get('conclusion') != 'success':
        errors.append('publication.json: source workflow was not successful')
    for key in ('site_artifact', 'snapshot_artifact'):
        artifact = publication.get(key, {})
        digest = artifact.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            errors.append(f'publication.json: invalid {key}.sha256')

    search_path = route / 'search-index.json'
    if search_path.is_file():
        # Sourcey emits an array for this file; validate that shape directly.
        try:
            search_items = json.loads(search_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f'search-index.json: invalid JSON ({exc})')
            search_items = []
        urls = [item.get('url', '') for item in search_items if isinstance(item, dict)]
        if not urls or any(not url.startswith(_TOOLS_ROUTE) for url in urls):
            errors.append('search-index.json: every URL must use the mounted tools route')

    for name, marker in (
        ('llms.txt', '(/mcp-tools.html'),
        ('llms-full.txt', 'Path: `/mcp-tools.html`'),
    ):
        path = route / name
        if path.is_file():
            text = path.read_text(errors='replace')
            if marker in text or _TOOLS_ROUTE not in text:
                errors.append(f'{name}: mounted tools route is not fully rewritten')

    sitemap = route / 'sitemap.xml'
    if sitemap.is_file():
        locs = set(re.findall(r'<loc>([^<]+)</loc>', sitemap.read_text(errors='replace')))
        expected = {
            'https://perseus.observer/vault/mcp-reference/',
            'https://perseus.observer/vault/mcp-reference/mcp-tools.html',
        }
        if locs != expected:
            errors.append('sitemap.xml: expected exactly the two mounted route URLs')

    # Generated HTML should resolve its local assets within this directory.
    for name in ('index.html', 'mcp-tools.html'):
        path = route / name
        if not path.is_file():
            continue
        text = path.read_text(errors='replace')
        refs = re.findall(r'''(?:href|src)=["']([^"']+)["']''', text)
        for ref in refs:
            if ref.startswith(('/', '//')) or ref.startswith(('http:', 'https:', 'data:', '#', 'mailto:', 'javascript:')):
                continue
            local = urlsplit(ref).path
            if local and not (route / local).is_file():
                errors.append(f'{name}: missing relative asset {ref}')

    page = repo_root / 'vault' / 'index.html'
    if page.is_file() and 'href="/vault/mcp-reference/"' not in page.read_text(errors='replace'):
        errors.append('vault/index.html: missing MCP reference entry link')

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate(root)
    if errors:
        for error in errors:
            print(f'ERROR: {error}', file=sys.stderr)
        return 1
    metadata = json.loads((root / 'vault' / 'mcp-reference' / 'metadata.json').read_text())
    print(f"PASS: {_ROUTE} ({metadata['tool_count']} tools, source {metadata['source_commit'][:8]})")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
