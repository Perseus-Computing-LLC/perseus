"""test_vault_export.py — Golden tests for `perseus vault export` (#816).

Covers: default (machine-readable) mode, prose mode (--prose), empty
vault, file output, and missing vault path.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PERSEUS_SCRIPT = Path(__file__).resolve().parent.parent / "perseus.py"
SRC_PERSEUS = Path(__file__).resolve().parent.parent / "src"


def _run_perseus(*args):
    """Run perseus with given args, return (returncode, stdout, stderr)."""
    env = {"PERSEUS_HOME": str(tempfile.mkdtemp(prefix="perseus-test-"))}
    cmd = [sys.executable, str(PERSEUS_SCRIPT)] + list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
    return proc.returncode, proc.stdout, proc.stderr


def _make_vault_dir(vault_path: Path, entries: dict[str, str]):
    """Create a vault directory with .md entries."""
    vault_path.mkdir(parents=True, exist_ok=True)
    for filename, body in entries.items():
        filepath = vault_path / f"{filename}.md"
        if isinstance(body, str):
            filepath.write_text(body, encoding="utf-8")
        else:
            filepath.write_text(body["full"], encoding="utf-8")


def test_export_empty_vault():
    """Export from an empty vault should not error."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "empty-vault"
        vault.mkdir()
        # Create a minimal config that points to this vault
        home = Path(td) / "home"
        home.mkdir()
        cfg = home / "config.yaml"
        cfg.write_text(f"memory:\n  store: {vault}\n")
        
        env = {"PERSEUS_HOME": str(home)}
        cmd = [sys.executable, str(PERSEUS_SCRIPT), "vault", "export"]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        
        # Should succeed, possibly with "No vault entries found" to stderr
        assert proc.returncode == 0, f"Expected rc=0, got {proc.returncode}: {proc.stderr}"


def test_export_machine_readable():
    """Default mode preserves frontmatter and returns structured output."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "test-vault"
        vault.mkdir()
        home = Path(td) / "home"
        home.mkdir()
        
        # Write entries with frontmatter
        (vault / "entry1.md").write_text("""---
title: Test Entry
type: insight
---
This is the body of entry 1.
It has multiple lines.
""", encoding="utf-8")
        
        (vault / "entry2.md").write_text("""---
title: Second Entry
type: decision
---
Body of entry 2.
""", encoding="utf-8")
        
        cfg = home / "config.yaml"
        cfg.write_text(f"memory:\n  store: {vault}\n")
        
        env = {"PERSEUS_HOME": str(home)}
        cmd = [sys.executable, str(PERSEUS_SCRIPT), "vault", "export"]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        
        assert proc.returncode == 0, f"Export failed: {proc.stderr}"
        output = proc.stdout
        
        # Machine-readable mode should preserve frontmatter
        assert "---" in output, "Should have YAML frontmatter"
        assert "Test Entry" in output, "Should contain first entry title"
        assert "Second Entry" in output, "Should contain second entry title"
        assert "Body of entry 2" in output, "Should contain entry body"


def test_export_prose_mode():
    """Prose mode strips frontmatter, outputs clean markdown."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "test-vault"
        vault.mkdir()
        home = Path(td) / "home"
        home.mkdir()
        
        (vault / "note1.md").write_text("""---
title: My Note
type: insight
---
This is pure prose content.

With multiple paragraphs.
""", encoding="utf-8")
        
        (vault / "note2.md").write_text("""---
title: Decision Record
type: decision
status: accepted
---
We decided to use prose mode for CoalWash.
""", encoding="utf-8")
        
        cfg = home / "config.yaml"
        cfg.write_text(f"memory:\n  store: {vault}\n")
        
        env = {"PERSEUS_HOME": str(home)}
        cmd = [sys.executable, str(PERSEUS_SCRIPT), "vault", "export", "--prose"]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        
        assert proc.returncode == 0, f"Prose export failed: {proc.stderr}"
        output = proc.stdout
        
        # Prose mode strips frontmatter
        assert "title:" not in output, "Should NOT contain YAML frontmatter keys"
        assert "type:" not in output, "Should NOT contain YAML frontmatter keys"
        
        # Should have heading markers from filenames
        assert "--- note1" in output, "Should have note1 heading"
        assert "--- note2" in output, "Should have note2 heading"
        
        # Should have body content
        assert "pure prose content" in output
        assert "CoalWash" in output


def test_export_prose_to_file():
    """Prose mode with --output writes to file instead of stdout."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "test-vault"
        vault.mkdir()
        home = Path(td) / "home"
        home.mkdir()
        
        (vault / "entry.md").write_text("""---
title: Test
---
File output test.
""", encoding="utf-8")
        
        cfg = home / "config.yaml"
        cfg.write_text(f"memory:\n  store: {vault}\n")
        
        out_file = Path(td) / "exported.md"
        env = {"PERSEUS_HOME": str(home)}
        cmd = [sys.executable, str(PERSEUS_SCRIPT), "vault", "export", "--prose", "-o", str(out_file)]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        
        assert proc.returncode == 0, f"Export to file failed: {proc.stderr}"
        assert out_file.exists(), "Output file should exist"
        
        content = out_file.read_text()
        assert "File output test" in content
        assert "title:" not in content, "Frontmatter should be stripped"


def test_export_prose_no_frontmatter_entries():
    """Entries without frontmatter are passed through in prose mode."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "test-vault"
        vault.mkdir()
        home = Path(td) / "home"
        home.mkdir()
        
        (vault / "plain.md").write_text("Just plain text, no frontmatter at all.", encoding="utf-8")
        
        cfg = home / "config.yaml"
        cfg.write_text(f"memory:\n  store: {vault}\n")
        
        env = {"PERSEUS_HOME": str(home)}
        cmd = [sys.executable, str(PERSEUS_SCRIPT), "vault", "export", "--prose"]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        
        assert proc.returncode == 0, f"Export failed: {proc.stderr}"
        output = proc.stdout
        assert "plain text" in output, "Plain text entry should pass through"


def test_export_missing_vault_path():
    """Export with missing vault path reports error gracefully."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "home"
        home.mkdir()
        
        vault = Path(td) / "nonexistent-vault"
        cfg = home / "config.yaml"
        cfg.write_text(f"memory:\n  store: {vault}\n")
        
        env = {"PERSEUS_HOME": str(home)}
        cmd = [sys.executable, str(PERSEUS_SCRIPT), "vault", "export"]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        
        # Should fail with non-zero exit
        assert proc.returncode != 0, f"Should fail for missing path, got {proc.returncode}"
        assert "vault path not found" in proc.stderr.lower() or "Error" in proc.stderr
