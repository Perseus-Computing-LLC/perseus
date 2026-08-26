from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_SPEC = spec_from_file_location('check_mcp_reference', ROOT / 'scripts' / 'check_mcp_reference.py')
assert _SPEC and _SPEC.loader
_CHECKER = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CHECKER)

_LIVE_SPEC = spec_from_file_location('check_live_mcp_reference', ROOT / 'scripts' / 'check_live_mcp_reference.py')
assert _LIVE_SPEC and _LIVE_SPEC.loader
_LIVE_CHECKER = module_from_spec(_LIVE_SPEC)
_LIVE_SPEC.loader.exec_module(_LIVE_CHECKER)


def test_published_mcp_reference_is_self_consistent():
    assert _CHECKER.validate(ROOT) == []


def test_live_checker_covers_the_published_contract():
    assert _LIVE_CHECKER.DEFAULT_BASE.endswith('/vault/mcp-reference/')
    assert set(_LIVE_CHECKER.REQUIRED) >= {
        'index.html',
        'mcp-tools.html',
        'metadata.json',
        'mcp.raw.json',
        'mcp.render.json',
        'publication.json',
        'search-index.json',
        'sitemap.xml',
        'llms.txt',
        'llms-full.txt',
        'sourcey.css',
        'sourcey.js',
        '_og/mcp-tools.png',
    }
