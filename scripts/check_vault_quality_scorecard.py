#!/usr/bin/env python3
"""Validate the Perseus Vault #779 memory-quality scorecard for Perseus CI."""
import argparse, json
from pathlib import Path

EXPECTED = "perseus-vault-memory-quality-scorecard/v1"

def validate(scorecard: dict) -> list[str]:
    errors=[]
    if scorecard.get("scorecard_version") != EXPECTED: errors.append("unsupported scorecard_version")
    if scorecard.get("verdict") != "release_ready": errors.append("Vault quality verdict is not release_ready")
    if scorecard.get("blocking") is not True: errors.append("scorecard is not marked blocking")
    if float(scorecard.get("accuracy", 0)) < 1.0: errors.append("accuracy below 1.0")
    if scorecard.get("failed_categories"): errors.append("failed_categories present")
    if scorecard.get("missing_categories"): errors.append("missing_categories present")
    return errors

def main():
 p=argparse.ArgumentParser();p.add_argument("scorecard");args=p.parse_args()
 errors=validate(json.loads(Path(args.scorecard).read_text()))
 if errors:
  print("VAULT QUALITY GATE: BLOCKED — " + "; ".join(errors)); return 1
 print("VAULT QUALITY GATE: READY")
 return 0
if __name__=='__main__': raise SystemExit(main())
