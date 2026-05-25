import re
from pathlib import Path

# ── Directive Macros (task-66) ────────────────────────────────────────────────
MACRO_START_RE = re.compile(r'^@macro\s+([\w-]+)\s*(.*)$', re.IGNORECASE)
MACRO_END_RE = re.compile(r'^@endmacro\s*$', re.IGNORECASE)
MACRO_PARAM_RE = re.compile(r'%(\w+)%')
MAX_MACRO_DEPTH = 10

def _parse_macros_from_lines(lines: list[str], start: int = 0) -> dict[str, tuple[list[str], list[str]]]:
    """Parse @macro ... @endmacro blocks from lines, starting at index start.

    Returns: {macro_name: (body_lines, param_names)} where param_names are
    the ordered %tokens% found in the macro body.
    """
    macros: dict[str, tuple[list[str], list[str]]] = {}
    i = start
    while i < len(lines):
        m = MACRO_START_RE.match(lines[i])
        if m:
            name = m.group(1).lower()
            raw_params = (m.group(2) or "").strip()
            # Parse %param% tokens from the macro header line or infer from body
            header_params = [p for p in MACRO_PARAM_RE.findall(raw_params)]
            i += 1
            body: list[str] = []
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            # Infer params from body if not declared in header
            if not header_params:
                all_body = "\n".join(body)
                body_params = []
                seen = set()
                for param in MACRO_PARAM_RE.findall(all_body):
                    if param not in seen:
                        body_params.append(param)
                        seen.add(param)
                header_params = body_params
            macros[name] = (body, header_params)
            if i < len(lines) and MACRO_END_RE.match(lines[i]):
                i += 1
        else:
            i += 1
    return macros


def _load_macros(source_lines: list[str], workspace: Path | None, cfg: dict) -> dict[str, tuple[list[str], list[str]]]:
    """Load macros from shared macros file, then overlay source-document macros.

    Shared macros are loaded first; source-document macros can shadow them.
    """
    macros: dict[str, tuple[list[str], list[str]]] = {}

    # Load shared macros file if it exists
    # Config key 'macros.file' per spec, default ~/.perseus/macros.md
    macros_file = cfg.get("macros", {}).get("file")
    if not macros_file:
        macros_path = PERSEUS_HOME / "macros.md"
    else:
        macros_path = Path(macros_file)

    try:
        if macros_path.is_file():
            file_lines = macros_path.read_text().splitlines()
            macros.update(_parse_macros_from_lines(file_lines))
    except (OSError, ValueError):
        pass

    # Source-document macros override shared macros
    source_macros = _parse_macros_from_lines(source_lines)
    macros.update(source_macros)

    return macros


def _expand_macros(lines: list[str], macros: dict[str, tuple[list[str], list[str]]]) -> list[str]:
    """Walk lines, expand macro invocations in place. Recursive up to MAX_MACRO_DEPTH.

    A macro invocation is a line that exactly (case-insensitively) matches
    a macro name (e.g. ``@project-health``).

    Returns the expanded lines (macro definitions stripped, invocations replaced).
    """
    # Strip macro definition blocks first
    current_lines = [l for l in _strip_macro_defs(lines)]
    if not macros:
        return current_lines

    depth = 0
    while depth < MAX_MACRO_DEPTH:
        next_lines = []
        changed = False
        for line in current_lines:
            stripped = line.strip()
            if stripped.startswith("@"):
                # Check for macro invocation (whole line)
                parts = stripped.split(None, 1)
                if parts:
                    invocation = parts[0][1:].lower()
                    if invocation in macros:
                        body, _ = macros[invocation]
                        next_lines.extend(body)
                        changed = True
                        continue
            next_lines.append(line)

        current_lines = next_lines
        if not changed:
            break
        depth += 1
    else:
        # MAX_MACRO_DEPTH exceeded
        current_lines.append(f"> ⚠ Macro expansion depth exceeded (max {MAX_MACRO_DEPTH})")

    return current_lines


def _strip_macro_defs(lines: list[str]) -> "iter":
    """Generator: yield lines, skipping @macro...@endmacro definition blocks."""
    i = 0
    while i < len(lines):
        if MACRO_START_RE.match(lines[i]):
            i += 1
            while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                i += 1
            if i < len(lines):
                i += 1  # skip @endmacro
            continue
        yield lines[i]
        i += 1
