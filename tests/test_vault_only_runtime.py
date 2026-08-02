"""Contract tests for the canonical Perseus Vault runtime surface."""

from pathlib import Path

from conftest import perseus


ROOT = Path(__file__).parents[1]
LEGACY_A = "mi" + "mir"
LEGACY_B = "mne" + "me"


def test_runtime_modules_and_exports_are_vault_named():
    source_dir = ROOT / "src" / "perseus"
    for name in (
        "vault_connector.py",
        "vault_index.py",
        "vault_narrative.py",
        "vault_federation.py",
    ):
        assert (source_dir / name).exists(), name
    assert not (source_dir / f"{LEGACY_A}_connector.py").exists()
    assert not (source_dir / f"{LEGACY_B}_connector.py").exists()
    assert hasattr(perseus, "VaultConnector")
    assert hasattr(perseus, "_vault_recall")
    assert not hasattr(perseus, LEGACY_B + "Connector")


def test_only_canonical_connector_config_is_resolved():
    config = perseus.DEFAULT_CONFIG
    assert "perseus_vault" in config
    assert config["perseus_vault"]["command"][0] == "perseus-vault"
    assert LEGACY_A not in config
    assert LEGACY_B not in config
    assert perseus._resolve_vault_config({LEGACY_A: {"enabled": False}}) == {}
    assert perseus._resolve_vault_config({LEGACY_B: {"enabled": False}}) == {}
    assert perseus._resolve_vault_config(
        {"perseus_vault": {"enabled": False}}
    ) == {"enabled": False}
