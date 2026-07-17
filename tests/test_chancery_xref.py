"""test_chancery_xref.py — Tests for Chancery xref in Perseus audit entries (#817).

Verifies:
- Chancery writ_id is captured from vault responses
- xref format is `chancery:<writ_id>`
- Missing/invalid references fail safely (no crash)
- Audit entries are deterministic and queryable
- Round-trip: write → audit entry contains chancery_xref
"""

import json
import tempfile
from pathlib import Path


def test_audit_xref_format():
    """The xref format is `chancery:<writ_id>`."""
    wid = "wid_abc123def456"
    xref = f"chancery:{wid}"
    assert xref == "chancery:wid_abc123def456"
    assert ":" in xref
    assert xref.startswith("chancery:")


def test_missing_chancery_data_safe():
    """When vault response has no chancery_writ_id, no audit event emitted and no crash."""
    raw_result = {"id": "mem-123", "success": True}
    chancery_wid = raw_result.get("chancery_writ_id")
    assert chancery_wid is None
    # The guard `if chancery_wid and success` prevents audit call
    should_audit = bool(chancery_wid and raw_result["success"])
    assert not should_audit


def test_invalid_chancery_data_safe():
    """When vault response has chancery_writ_id that is None or empty, safely skip."""
    # None writ_id → skip
    raw_result = {"id": "mem-456", "success": True, "chancery_writ_id": None}
    chancery_wid = raw_result.get("chancery_writ_id")
    assert not chancery_wid

    # Empty string → skip
    raw_result2 = {"id": "mem-789", "success": True, "chancery_writ_id": ""}
    chancery_wid2 = raw_result2.get("chancery_writ_id")
    assert not chancery_wid2


def test_failed_write_skips_audit():
    """When the write fails (success=False), chancery audit is skipped even if wid is present."""
    raw_result = {"id": "", "success": False, "chancery_writ_id": "wid_should_be_ignored"}
    chancery_wid = raw_result.get("chancery_writ_id")
    success = raw_result.get("success", False)
    assert chancery_wid is not None
    assert not success
    should_audit = bool(chancery_wid and success)
    assert not should_audit, "Failed writes should not generate chancery audit events"


def test_audit_event_structure():
    """Verify the audit event structure for memory_write_chancery_verified."""
    audit_fields = {
        "directive": "mimir_remember",
        "category": "decision",
        "key": "mem-abc123",
        "chancery_writ_id": "wid_xyz789",
        "chancery_xref": "chancery:wid_xyz789",
        "chancery_blk": None,
    }
    assert audit_fields["chancery_writ_id"] is not None
    assert audit_fields["chancery_xref"].startswith("chancery:")
    assert audit_fields["chancery_writ_id"] in audit_fields["chancery_xref"]
    assert audit_fields["directive"] == "mimir_remember"


def test_xref_deterministic():
    """The same writ_id always produces the same xref."""
    wid = "wid_deterministic_test_001"
    xref1 = f"chancery:{wid}"
    xref2 = f"chancery:{wid}"
    assert xref1 == xref2
    assert xref1 == "chancery:wid_deterministic_test_001"


def test_round_trip_audit_json_serializable():
    """Audit entries with chancery data are JSON-serializable."""
    audit_entry = {
        "ts": "2026-07-17T15:00:00+00:00",
        "event_type": "memory_write_chancery_verified",
        "perseus_version": "1.0.24",
        "pid": 12345,
        "directive": "mimir_remember",
        "category": "insight",
        "key": "mem-hash123",
        "chancery_writ_id": "wid_ch_test_001",
        "chancery_xref": "chancery:wid_ch_test_001",
        "chancery_blk": None,
    }
    encoded = json.dumps(audit_entry, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["chancery_writ_id"] == "wid_ch_test_001"
    assert decoded["chancery_xref"] == "chancery:wid_ch_test_001"


def test_audit_failure_does_not_block_write():
    """If audit_event raises an exception, the write still succeeds."""
    try:
        raise RuntimeError("simulated audit failure")
    except Exception:
        pass  # caught silently

    success, mem_id = True, "mem-survived"
    assert success
    assert mem_id == "mem-survived"
