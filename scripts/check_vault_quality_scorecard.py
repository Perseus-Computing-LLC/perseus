#!/usr/bin/env python3
"""Validate the Perseus Vault #779 memory-quality scorecard for Perseus CI."""
import argparse, json, math
from pathlib import Path

EXPECTED = "perseus-vault-memory-quality-scorecard/v1"
ACCEPTED_VERSIONS = frozenset({
    EXPECTED,
    "perseus-vault-memory-quality-scorecard/v2",
})

def validate(scorecard: dict) -> list[str]:
    errors=[]
    if not isinstance(scorecard, dict):
        return ["scorecard must be an object"]
    version = scorecard.get("scorecard_version")
    if not isinstance(version, str) or version not in ACCEPTED_VERSIONS: errors.append("unsupported scorecard_version")
    if scorecard.get("verdict") != "release_ready": errors.append("Vault quality verdict is not release_ready")
    if scorecard.get("blocking") is not True: errors.append("scorecard is not marked blocking")
    accuracy = scorecard.get("accuracy")
    try:
        numeric_accuracy = float(accuracy)
    except (TypeError, ValueError, OverflowError):
        numeric_accuracy = float("nan")
    if (isinstance(accuracy, bool) or not isinstance(accuracy, (int, float))
            or not math.isfinite(numeric_accuracy) or not 0.0 <= numeric_accuracy <= 1.0
            or numeric_accuracy < 1.0):
        errors.append("accuracy below 1.0")
    list_fields = (
        "failed_categories", "missing_categories", "invalid_cases",
        "unavailable_categories", "unavailable_cases",
        "unavailable_capabilities", "unavailable_metrics",
        "failed_metrics", "invalid_metrics",
    )
    if version == "perseus-vault-memory-quality-scorecard/v2":
        for field in list_fields:
            if field not in scorecard:
                errors.append(f"{field} missing")
    for field in list_fields:
        if field in scorecard and not isinstance(scorecard[field], list):
            errors.append(f"{field} must be a list")
        elif scorecard.get(field):
            errors.append(f"{field} present")
    return errors

def main():
 p=argparse.ArgumentParser();p.add_argument("scorecard");args=p.parse_args()
 try:
  scorecard=json.loads(Path(args.scorecard).read_text(encoding="utf-8"))
 except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
  print("VAULT QUALITY GATE: BLOCKED — malformed scorecard JSON")
  return 1
 errors=validate(scorecard)
 if errors:
  print("VAULT QUALITY GATE: BLOCKED — " + "; ".join(errors)); return 1
 print("VAULT QUALITY GATE: READY")
 return 0
if __name__=='__main__': raise SystemExit(main())
