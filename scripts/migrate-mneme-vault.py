#!/usr/bin/env python3
"""
Mnēmē v2 — Bastra → Perseus Vault Migration
=============================================

Migrates Bastra-format memory vault files to the Perseus-native v2 format.

Usage:
  python scripts/migrate-mneme-vault.py [--from OLD_VAULT] [--to NEW_VAULT] [--dry-run]

Defaults:
  --from  ~/.hermes/mneme-vault/memories/projects/
  --to    ~/.perseus/memory/vault/
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml


def parse_bastra_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from a markdown file. Returns (fm_dict, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}, text
    return fm, parts[2]


def migrate_document(file_path: Path, target_dir: Path, dry_run: bool = False) -> bool:
    """Migrate a single Bastra-format .md file to v2 format. Returns True on success."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        print(f"  ⚠ Cannot read {file_path.name}: permission error")
        return False

    fm, body = parse_bastra_frontmatter(text)
    if not fm:
        print(f"  ⚠ {file_path.name}: no valid frontmatter, skipping")
        return False

    doc_id = str(fm.get("id", file_path.stem) or file_path.stem)
    title = str(fm.get("title", "") or "")
    if not title:
        print(f"  ⚠ {file_path.name}: no title, skipping")
        return False

    # Translate Bastra fields → v2
    v2 = {
        "schema": 2,
        "id": doc_id,
        "title": title,
        "type": str(fm.get("type", "reference") or "reference"),
        "summary": str(fm.get("summary", "") or "")[:400],
        "scope": str(fm.get("scope", "all-projects") or "all-projects"),
        "created": str(fm.get("created", datetime.now().strftime("%Y-%m-%d")) or ""),
        "updated": str(fm.get("updated", datetime.now().strftime("%Y-%m-%d")) or ""),
    }

    # Optional fields
    if fm.get("tags"):
        v2["tags"] = [str(t) for t in fm["tags"] if t]
    if fm.get("topic_path"):
        v2["topic_path"] = [str(t) for t in fm["topic_path"] if t]
    if fm.get("confidence") is not None:
        v2["confidence"] = float(fm["confidence"])
    if fm.get("sensitivity"):
        v2["sensitivity"] = str(fm["sensitivity"])
    if fm.get("related"):
        v2["related"] = [str(r) for r in fm["related"] if r]
    if fm.get("affects_files"):
        v2["affected_files"] = [str(f) for f in fm["affects_files"] if f]
    if fm.get("issues"):
        v2["issues"] = [str(i) for i in fm["issues"] if i]
    if fm.get("source"):
        v2["source"] = str(fm["source"])

    # Handle expiration: valid_until or expires_after_days → expires
    expires = fm.get("valid_until") or fm.get("expires")
    if not expires and fm.get("expires_after_days") is not None:
        try:
            days = int(fm["expires_after_days"])
            expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    if expires:
        v2["expires"] = str(expires)[:10]

    # Build output file
    fm_yaml = yaml.safe_dump(v2, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    output = f"---\n{fm_yaml}\n---\n\n{body.rstrip()}\n"

    if dry_run:
        print(f"  ✓ {doc_id}.md → would write {len(output)} bytes")
        return True

    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{doc_id}.md"
    out_path.write_text(output, encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser(description="Migrate Bastra vault → Mnēmē v2")
    parser.add_argument(
        "--from", dest="old_vault", type=str,
        default=str(Path.home() / ".hermes" / "mneme-vault" / "memories" / "projects"),
        help="Source Bastra vault directory"
    )
    parser.add_argument(
        "--to", dest="new_vault", type=str,
        default=str(Path.home() / ".perseus" / "memory" / "vault"),
        help="Target Mnēmē v2 vault directory"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be migrated without writing files"
    )
    args = parser.parse_args()

    old_vault = Path(getattr(args, "old_vault")).expanduser()
    new_vault = Path(getattr(args, "new_vault")).expanduser()

    if not old_vault.is_dir():
        print(f"Source vault not found: {old_vault}")
        print("Nothing to migrate.")
        return 0

    md_files = sorted(old_vault.rglob("*.md"))
    if not md_files:
        print(f"No .md files found in {old_vault}")
        return 0

    print(f"Source: {old_vault} ({len(md_files)} files)")
    print(f"Target: {new_vault}")
    if args.dry_run:
        print("Mode: DRY RUN (no files will be written)")
    print()

    migrated = 0
    skipped = 0
    for f in md_files:
        if migrate_document(f, new_vault, dry_run=args.dry_run):
            migrated += 1
        else:
            skipped += 1

    print(f"\nDone. {migrated} migrated, {skipped} skipped.")
    if not args.dry_run and migrated > 0:
        print(f"\nNext: run `perseus memory update` to build the FTS5 index.")
        print(f"  Index path: {new_vault / 'mneme.index'}")

    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
