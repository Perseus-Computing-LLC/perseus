"""Regression coverage for canonical Ledger metering configuration."""
from __future__ import annotations

import copy

from conftest import perseus


def test_posture_metering_reads_canonical_ledger_config(monkeypatch, tmp_path):
    observed = []

    class _UnavailableConnector:
        available = False

    def _connector(cfg):
        observed.append(cfg)
        return _UnavailableConnector()

    monkeypatch.setattr(perseus, "_get_connector", _connector)
    config = copy.deepcopy(perseus.DEFAULT_CONFIG)
    config["ledger"].update({
        "enabled": True,
        "db_path": str(tmp_path / "ledger.db"),
        "meter_memory_posture": True,
    })

    perseus._maybe_meter_posture_reduction(
        config, "actual", config["perseus_vault"], 10, None
    )
    assert observed == [config]


def test_posture_metering_honors_legacy_plutus_without_canonical_block(tmp_path):
    config = {
        "plutus": {
            "enabled": True,
            "db_path": str(tmp_path / "legacy-ledger.db"),
            "meter_memory_posture": True,
        }
    }

    assert perseus.metering_enabled(config) is True


def test_posture_metering_canonical_disable_wins_over_legacy_override(tmp_path):
    config = copy.deepcopy(perseus.DEFAULT_CONFIG)
    config["ledger"].update({
        "enabled": False,
        "db_path": str(tmp_path / "canonical-ledger.db"),
    })
    config["plutus"] = {
        "enabled": True,
        "db_path": str(tmp_path / "legacy-ledger.db"),
        "meter_memory_posture": True,
    }

    assert perseus.metering_enabled(config) is False


def test_load_config_normalizes_legacy_plutus_into_ledger(tmp_path):
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".perseus"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "plutus:\n"
        "  enabled: true\n"
        f"  db_path: {tmp_path / 'loaded-legacy.db'}\n"
        "  meter_memory_posture: true\n",
        encoding="utf-8",
    )

    loaded = perseus.load_config(workspace)

    assert "plutus" not in loaded
    assert loaded["ledger"]["enabled"] is True
    assert loaded["ledger"]["meter_memory_posture"] is True
    assert perseus.metering_enabled(loaded) is True
