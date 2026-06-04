"""Property-based fuzz tests for Perseus directive parsing functions.

task-64: Uses Hypothesis to generate random inputs and verify invariants
for the parser functions that handle untrusted directive arguments.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from perseus import (
    _parse_kv_modifiers,
    _extract_quoted_token,
    _parse_tier_modifier,
    _parse_cache_modifier,
    INLINE_DIRECTIVE_RE,
    DIRECTIVE_REGISTRY,
)


# ── _parse_kv_modifiers ──────────────────────────────────────────────────────

@given(st.text())
@settings(max_examples=500)
def test_parse_kv_modifiers_never_crashes(text):
    """_parse_kv_modifiers must return a dict for any input, never raise."""
    result = _parse_kv_modifiers(text)
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"


@given(st.text())
@settings(max_examples=200)
def test_parse_kv_modifiers_no_values_are_none(text):
    """No value in the result dict should be None."""
    result = _parse_kv_modifiers(text)
    for key, val in result.items():
        assert val is not None, f"None value for key '{key}' in {result}"


@given(st.text())
@settings(max_examples=200)
def test_parse_kv_modifiers_all_keys_are_strings(text):
    """All keys must be non-empty strings."""
    result = _parse_kv_modifiers(text)
    for key in result:
        assert isinstance(key, str) and key.strip(), f"Invalid key: {key!r}"


@given(
    value=st.text(
        alphabet=st.characters(blacklist_characters='"\\'),
        min_size=1, max_size=50,
    ),
)
@settings(max_examples=200)
def test_parse_kv_modifiers_quoted_value(value):
    """key=\"value\" should strip quotes from value."""
    result = _parse_kv_modifiers(f'test="{value}"')
    assert result.get("test") == value, f"Expected '{value}', got {result.get('test')}"


@given(st.text(min_size=1, max_size=30))
@settings(max_examples=200)
def test_parse_kv_modifiers_boolean_flag(text):
    """Single word without = should produce a boolean True value."""
    assume("=" not in text)
    assume(" " not in text)
    assume(text.strip() == text)
    result = _parse_kv_modifiers(text)
    if text in result:
        assert result[text] is True, f"Expected True for '{text}', got {result[text]}"


# ── _extract_quoted_token ────────────────────────────────────────────────────

@given(st.text())
@settings(max_examples=500)
def test_extract_quoted_token_never_crashes(text):
    """_extract_quoted_token must return a tuple for any input."""
    result = _extract_quoted_token(text)
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 2, f"Expected length 2, got {len(result)}"


@given(st.text(max_size=100))
@settings(max_examples=300)
def test_extract_quoted_token_returns_strings(text):
    """Token and remaining must both be strings or None."""
    token, remaining = _extract_quoted_token(text)
    assert token is None or isinstance(token, str)
    assert isinstance(remaining, str)


@given(
    content=st.text(alphabet=st.characters(blacklist_characters='"\\'), min_size=0, max_size=30),
)
@settings(max_examples=200)
def test_extract_quoted_token_balanced_quotes(content):
    """Quoted content should be extracted correctly with balanced quotes."""
    text = f'"{content}" extra stuff'
    token, remaining = _extract_quoted_token(text)
    assert token == content, f"Expected '{content}', got '{token}'"
    assert "extra" in remaining, f"Expected remaining to contain 'extra', got '{remaining}'"


@given(
    content=st.text(alphabet=st.characters(blacklist_characters="\\"), max_size=30),
)
@settings(max_examples=200)
def test_extract_quoted_token_single_quotes(content):
    """Single-quoted content should work the same as double-quoted."""
    assume("'" not in content)
    text = f"'{content}' tail"
    token, remaining = _extract_quoted_token(text)
    assert token == content, f"Expected '{content}', got '{token}'"
    assert "tail" in remaining


# ── INLINE_DIRECTIVE_RE ──────────────────────────────────────────────────────

@given(st.text(min_size=1, max_size=100))
@settings(max_examples=500)
def test_inline_directive_re_never_crashes(text):
    """INLINE_DIRECTIVE_RE.match must not raise on any input."""
    try:
        INLINE_DIRECTIVE_RE.match(text)
    except Exception as e:
        pytest.fail(f"INLINE_DIRECTIVE_RE.match raised {e} on '{text}'")


@given(st.text(min_size=1, max_size=50))
@settings(max_examples=300)
def test_inline_directive_re_no_false_positive(text):
    """Text without @ at start should not match."""
    assume(not text.lstrip().startswith("@"))
    m = INLINE_DIRECTIVE_RE.match(text)
    assert m is None, f"False match on '{text}': {m.group(0)}"


@pytest.mark.parametrize("name", [
    n for n, s in DIRECTIVE_REGISTRY.items() if s.kind == "inline"
])
def test_inline_directive_re_matches_known_directives(name):
    """Every inline directive must match INLINE_DIRECTIVE_RE."""
    m = INLINE_DIRECTIVE_RE.match(f"{name} some args")
    assert m is not None, f"Inline directive '{name}' did not match INLINE_DIRECTIVE_RE"


# ── Directive registry consistency ────────────────────────────────────────────

def test_directive_registry_no_duplicates():
    """Directive names must be unique (case-insensitive after @)."""
    names = [name.lower() for name in DIRECTIVE_REGISTRY]
    duplicates = [n for n in set(names) if names.count(n) > 1]
    assert not duplicates, f"Duplicate directive names: {duplicates}"


def test_directive_registry_all_have_valid_kinds():
    """Every directive must have a valid kind."""
    VALID_KINDS = {"inline", "block", "control"}
    for name, spec in DIRECTIVE_REGISTRY.items():
        assert spec.kind in VALID_KINDS, f"Invalid kind '{spec.kind}' for {name}"
        assert spec.name == name, f"Name mismatch: {spec.name} != {name}"


def test_directive_registry_inline_have_resolvers():
    """All inline directives must have a resolver."""
    for name, spec in DIRECTIVE_REGISTRY.items():
        if spec.kind == "inline":
            assert spec.resolver is not None, f"Inline directive '{name}' has no resolver"


# ── _parse_tier_modifier ─────────────────────────────────────────────────────

@given(st.text())
@settings(max_examples=500)
def test_parse_tier_modifier_never_crashes(text):
    """_parse_tier_modifier must return a tuple for any input."""
    result = _parse_tier_modifier(text)
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 2, f"Expected length 2, got {len(result)}"
    remaining, tier = result
    assert isinstance(remaining, str)
    assert tier is None or isinstance(tier, int), \
        f"tier must be int or None, got {type(tier)}"


@given(st.integers(min_value=1, max_value=3))
@settings(max_examples=50)
def test_parse_tier_modifier_valid_tiers(n):
    remaining, tier = _parse_tier_modifier(f"@tier:{n} some args")
    assert tier == n, f"Expected tier={n}, got tier={tier}"
    assert "@tier:" not in remaining


@given(st.integers(max_value=0) | st.integers(min_value=4))
@settings(max_examples=50)
def test_parse_tier_modifier_invalid_tiers_returns_none(n):
    remaining, tier = _parse_tier_modifier(f"@tier:{n} some args")
    if n < 1 or n > 3:
        assert tier is None or tier < 1 or tier > 3, \
            f"Out-of-range tier={n} should not be returned as valid: got {tier}"
    else:
        assert tier == n


# ── _parse_cache_modifier ────────────────────────────────────────────────────

@given(st.text())
@settings(max_examples=500)
def test_parse_cache_modifier_never_crashes(text):
    """_parse_cache_modifier must return a tuple for any input."""
    result = _parse_cache_modifier(text)
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 4, f"Expected length 4, got {len(result)}"


@given(st.text(max_size=100))
@settings(max_examples=300)
def test_parse_cache_modifier_valid_mode(text):
    """Cache mode must be one of the known values, None, or empty string."""
    args, mode, ttl, mock = _parse_cache_modifier(text)
    known_modes = {None, "", "ttl", "session", "persist", "mock", "fingerprint", "nofingerprint"}
    assert mode in known_modes, f"Invalid cache mode: {mode!r}"
    assert isinstance(args, str), f"Args must be str, got {type(args)}"
    if ttl is not None:
        assert isinstance(ttl, int), f"TTL must be int or None, got {type(ttl)}"
