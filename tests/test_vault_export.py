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

        # Should have heading markers from filenames — ATX headings, never a
        # `---`-opening line (a file opening with `---` is fence-checked by
        # CoalWash's input contract and an unclosed fence is refused)
        assert "## note1" in output, "Should have note1 heading"
        assert "## note2" in output, "Should have note2 heading"
        assert not output.startswith("---"), "Prose output must not open with a --- fence"
        
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


def _prose_export_bytes(home: Path, vault: Path) -> subprocess.CompletedProcess:
    """Run `perseus vault export --prose` capturing RAW bytes (no text decode)."""
    cfg = home / "config.yaml"
    cfg.write_text(f"memory:\n  store: {vault}\n")
    env = {"PERSEUS_HOME": str(home)}
    cmd = [sys.executable, str(PERSEUS_SCRIPT), "vault", "export", "--prose"]
    return subprocess.run(cmd, capture_output=True, env=env, timeout=30)


def test_export_prose_coalwash_contract_bytes():
    """Prose output meets CoalWash datasheet §6 byte-level checks.

    Every output file must be valid strict UTF-8 with no NUL byte, and the
    first 64 characters must be clean (no NUL, no U+FFFD, no BOM) — with or
    without frontmatter. The flattener must never introduce U+FFFD by lossy
    re-encoding, and must not open with an unclosed `---` fence.
    """
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        vault = td / "test-vault"
        home = td / "home"
        vault.mkdir(parents=True)
        home.mkdir()

        # A normal entry, a Thai/CJK/emoji entry (valid UTF-8 must survive),
        # an entry with an invalid UTF-8 byte, and a NUL-bearing entry.
        (vault / "note1.md").write_bytes(
            b"---\ntitle: Note\n---\nProse body with unicode: \xe0\xb8\xa0\xe0\xb8\xb2\xe0\xb8\xa9\xe0\xb8\xb2, \xe4\xb8\xad\xe6\x96\x87, and \xf0\x9f\x9a\x80.\n"
        )
        (vault / "bad-encoding.md").write_bytes(
            b"---\ntitle: Bad\n---\nBroken byte here: \x81\n"
        )
        (vault / "binary-note.md").write_bytes(
            b"---\ntitle: Binary\n---\nNUL here: \x00\n"
        )

        proc = _prose_export_bytes(home, vault)
        assert proc.returncode == 0, f"Prose export failed: {proc.stderr!r}"
        data = proc.stdout

        # No NUL anywhere.
        assert b"\x00" not in data, "Prose output must not contain NUL bytes"
        # Strict UTF-8, whole file.
        text = data.decode("utf-8")  # raises if invalid
        # Clean 64-character head (chars, not bytes — same as CoalWash's
        # FM_HEAD_SCAN): no NUL, no U+FFFD, no BOM.
        head = text[:64]
        assert "\ufffd" not in head, "Prose output head must not contain U+FFFD"
        assert "\ufeff" not in head, "Prose output head must not contain a BOM"
        # Never opens with a `---` fence line.
        assert not data.startswith(b"---"), "Prose output must not open with ---"
        # The lossy/undecodable entries were skipped, not silently re-encoded.
        assert b"\xfffd" not in data, "Prose output must not contain U+FFFD anywhere"
        assert "Broken byte" not in proc.stdout.decode("utf-8"), "Undecodable entry should be skipped"
        assert "NUL here" not in proc.stdout.decode("utf-8"), "NUL-bearing entry should be skipped"
        assert "Warning: skipping" in proc.stderr.decode("utf-8"), "Skipped entries should warn"
        # Valid unicode entry survived.
        assert "\u0e20\u0e32\u0e29\u0e32" in proc.stdout.decode("utf-8"), "Valid UTF-8 must survive"


def test_export_machine_readable_skips_binary_entries():
    """Machine-readable mode also skips NUL/undecodable files (fail closed)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        vault = td / "test-vault"
        home = td / "home"
        vault.mkdir(parents=True)
        home.mkdir()

        (vault / "ok.md").write_bytes(b"---\ntitle: OK\n---\nFine body.\n")
        (vault / "bad.md").write_bytes(b"---\ntitle: Bad\n---\nNUL: \x00\n")

        cfg = home / "config.yaml"
        cfg.write_text(f"memory:\n  store: {vault}\n")
        env = {"PERSEUS_HOME": str(home)}
        cmd = [sys.executable, str(PERSEUS_SCRIPT), "vault", "export"]
        proc = subprocess.run(cmd, capture_output=True, env=env, timeout=30)

        assert proc.returncode == 0
        assert b"\x00" not in proc.stdout, "Machine-readable output must not carry NUL"
        assert b"Fine body." in proc.stdout
        assert b"Bad" not in proc.stdout
