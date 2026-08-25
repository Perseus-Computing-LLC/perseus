from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_SPEC = spec_from_file_location('check_mcp_reference', ROOT / 'scripts' / 'check_mcp_reference.py')
assert _SPEC and _SPEC.loader
_CHECKER = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CHECKER)


def test_published_mcp_reference_is_self_consistent():
    assert _CHECKER.validate(ROOT) == []
