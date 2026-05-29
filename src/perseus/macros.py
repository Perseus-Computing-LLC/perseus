import re
from pathlib import Path

# ── Directive Macros (task-66) ────────────────────────────────────────────────
MACRO_START_RE = re.compile(r'^@macro\s+([\w-]+)\s*(.*)$', re.IGNORECASE)
MACRO_END_RE = re.compile(r'^@endmacro\s*$', re.IGNORECASE)
MACRO_PARAM_RE = re.compile(r'%(\w+)%')
MAX_MACRO_DEPTH = 10
# Note: _parse_macros_from_lines, _load_macros, _expand_macros, and
# _strip_macro_defs are defined in renderer.py (parameterized macros
# with fork-bomb width caps). The older non-parameterized copies that
# lived here were dead code — MODULE_ORDER placed renderer.py after
# macros.py, so renderer's definitions always shadowed these.
