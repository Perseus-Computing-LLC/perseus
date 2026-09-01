"""Canonical product-surface and legacy-asset boundaries."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_site_assets_are_explicitly_isolated():
    # Git does not track empty directories; assert the old public asset/path is
    # gone rather than depending on whether a local checkout retains an empty
    # directory after a generated redirect was removed.
    assert not (ROOT / "plutus" / "index.html").exists()
    assert (ROOT / "legacy" / "plutus").is_dir()
    assert not (ROOT / ".contextforge").exists()
    assert (ROOT / "legacy" / "contextforge").is_dir()
    # The web route is canonical product content, not a legacy asset.
    assert (ROOT / "vault" / "index.html").is_file()


def test_vault_branding_regression_file_uses_canonical_name():
    assert not (ROOT / "tests" / "test_bugfix_662_663_vault_rebrand.py").exists()
    assert (ROOT / "tests" / "test_perseus_vault_branding.py").is_file()


def test_active_cost_savings_harness_uses_ledger_package_name():
    for path in (ROOT / "benchmark" / "cost_savings").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "plutus_agent" not in text
        assert "plutus-agent" not in text
