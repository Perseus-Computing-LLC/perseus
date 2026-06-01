#!/usr/bin/env python3
"""Apply #103 and #109 fixes to misc.py — single clean pass."""
from pathlib import Path

path = Path('src/perseus/directives/misc.py')
lines = path.read_text().splitlines(keepends=True)
print(f"Read {len(lines)} lines from {path}")

# ── #103: _walk_dot_path (lines 28-37, 1-indexed) ──
# Line 27 = index 27 (0-indexed), line 37 = index 36
assert "def _walk_dot_path" in lines[27], f"Unexpected line 28: {lines[27]}"
assert "return cur" in lines[36], f"Unexpected line 37: {lines[36]}"

new_walk = """def _walk_dot_path(obj: object, dot: str) -> object:
    \"\"\"Traverse a dot-notation path into a nested dict/list structure.

    Supports:
      - Dictionary key access:  "foo.bar.baz"
      - List index access:      "items.0.name"  (numeric path segments)
    Returns None if any segment cannot be resolved.
    \"\"\"
    cur = obj
    if not dot:
        return cur
    for part in dot.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
        else:
            return None
    return cur
"""
lines[27:37] = [new_walk + "\n"]
print("OK #103: _walk_dot_path")

# ── #109: resolve_date (lines 247-266, 1-indexed) ──
assert "def resolve_date" in lines[246], f"Unexpected line 247: {lines[246]}"
assert "def resolve_prompt_block" in lines[270], f"Unexpected line 271: {lines[270]}"

new_date = '''def resolve_date(args_str: str) -> str:
    """Resolve @date with optional format, offset, and days-ago modifiers.

    Modifiers:
      format="..."   — strftime-style format with human tokens (YYYY, MM, DD, HH, mm, ss, z)
      offset="-24h"  — offset from now (e.g. -24h, +7d, -30m); suffix: h=hours, d=days, m=minutes
      days-ago=7     — shorthand for offset=-Nd where N is an integer
    """
    from datetime import timedelta

    # Original regex-based format parsing (preserved for backreference tests)
    fmt_match = re.search(r'format=(["\'])([^"\']*)\\1', args_str)
    if fmt_match:
        fmt = fmt_match.group(2)
    else:
        fmt_match = re.search(r"format='([^']+)'", args_str)
        fmt = fmt_match.group(1) if fmt_match else "YYYY-MM-DD HH:mm z"

    # Parse offset and days-ago from the remaining args
    # Strip format="..." before parsing modifiers so format="" isn't misparsed
    remaining = args_str.strip()
    remaining = re.sub(r'format=(["\'])(?:[^"\']*)\\1', '', remaining)
    remaining = re.sub(r"format='[^']*'", "", remaining)
    remaining = re.sub(r'format=\\S+', '', remaining)
    mods = _parse_kv_modifiers(remaining)

    offset_str = mods.get("offset")
    days_ago = mods.get("days-ago")
    delta = timedelta()
    if offset_str:
        m = re.match(r'^([+-])(\\d+)([hdm])$', offset_str.strip())
        if m:
            sign = 1 if m.group(1) == '+' else -1
            val = int(m.group(2))
            unit = m.group(3)
            if unit == 'h':
                delta = timedelta(hours=sign * val)
            elif unit == 'd':
                delta = timedelta(days=sign * val)
            elif unit == 'm':
                delta = timedelta(minutes=sign * val)
    elif days_ago:
        try:
            delta = timedelta(days=-int(days_ago))
        except (ValueError, TypeError):
            pass

    now = datetime.now() + delta

    # Map human tokens to strftime
    result = fmt
    result = result.replace("YYYY", now.strftime("%Y"))
    result = result.replace("MM", now.strftime("%m"))
    result = result.replace("DD", now.strftime("%d"))
    result = result.replace("HH", now.strftime("%H"))
    result = result.replace("mm", now.strftime("%M"))
    result = result.replace("ss", now.strftime("%S"))
    result = result.replace("z", now.astimezone().strftime("%Z"))
    return result
'''

lines[246:266] = [new_date + "\n"]
print("OK #109: resolve_date")

path.write_text(''.join(lines))
print(f"Written {len(lines)} lines to {path}")
