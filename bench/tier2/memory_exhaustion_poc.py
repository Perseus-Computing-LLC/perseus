#!/usr/bin/env python3
"""bench/tier2/memory_exhaustion_poc.py — Demonstrate pre-read memory exhaustion in @include and @read.

Both resolve_include() and resolve_read() call fp.read_bytes() BEFORE checking
max_*_bytes limits. A large file causes MemoryError before the size check fires.
"""
import sys
import tempfile
import os
from pathlib import Path

# Add workspace to path
sys.path.insert(0, "/workspace/perseus/src")

# Create a moderate-size file to test pre-read behavior
# We'll use a 200MB file (adjust based on available RAM)
def test_include_preread():
    """Test that @include reads entire file before checking max_include_bytes."""
    from perseus.config import DEFAULT_CONFIG
    from perseus.directives.include import resolve_include

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "workspace"
        ws.mkdir()

        # Create a file larger than max_include_bytes
        big_file = ws / "big.md"
        # Use 50MB to be safe but still demonstrate the issue
        size_mb = 50
        with big_file.open("wb") as f:
            f.write(b"# Big file\n" + b"x" * (size_mb * 1024 * 1024))

        cfg = {"render": {"max_include_bytes": 1024}}  # allow only 1KB

        # This should be denied because file > max_include_bytes
        # But the current code reads the ENTIRE 50MB file first
        print(f"Testing @include with {size_mb}MB file, max_include_bytes=1024...")
        print(f"File size: {big_file.stat().st_size:,} bytes")

        try:
            import psutil
            before_mem = psutil.Process().memory_info().rss
            result = resolve_include(f'"{big_file}"', cfg=cfg, workspace=ws)
            after_mem = psutil.Process().memory_info().rss
            mem_delta_mb = (after_mem - before_mem) / (1024 * 1024)
            print(f"  Memory delta: {mem_delta_mb:.1f} MB")
            print(f"  Result starts with: {result[:200]}")
            if mem_delta_mb > 5:
                print(f"  ** BUG CONFIRMED: read ~{mem_delta_mb:.0f}MB before rejecting {size_mb}MB file")
            else:
                print(f"  PASS: memory usage acceptable (likely file cached by OS)")
        except ImportError:
            print("  (psutil not installed — skipped memory measurement)")
            result = resolve_include(f'"{big_file}"', cfg=cfg, workspace=ws)
            print(f"  Result starts with: {result[:200]}")

        # Now try with a file that would cause OOM
        # Skip actual OOM test, just verify the code path
        small_file = ws / "small.md"
        small_file.write_text("# Small\n")
        result = resolve_include(f'"{small_file}"', cfg=cfg, workspace=ws)
        print(f"\n  Small file result: {result[:200]}")
        print(f"  PASS: small file works correctly")


def test_read_preread():
    """Test that @read reads entire file before checking max_read_bytes."""
    from perseus.config import DEFAULT_CONFIG
    from perseus.directives.read import resolve_read

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "workspace"
        ws.mkdir()

        # Create a file larger than max_read_bytes
        big_file = ws / "data.json"
        size_mb = 30
        with big_file.open("wb") as f:
            f.write(b'{"key": "' + b"x" * (size_mb * 1024 * 1024) + b'"}')

        cfg = {"render": {"max_read_bytes": 1024}}

        print(f"\nTesting @read with {size_mb}MB JSON file, max_read_bytes=1024...")
        print(f"File size: {big_file.stat().st_size:,} bytes")

        try:
            import psutil
            before_mem = psutil.Process().memory_info().rss
            result = resolve_read(f'"{big_file}"', cfg=cfg, workspace=ws)
            after_mem = psutil.Process().memory_info().rss
            mem_delta_mb = (after_mem - before_mem) / (1024 * 1024)
            print(f"  Memory delta: {mem_delta_mb:.1f} MB")
            print(f"  Result starts with: {result[:200]}")
            if mem_delta_mb > 5:
                print(f"  ** BUG CONFIRMED: read ~{mem_delta_mb:.0f}MB before rejecting {size_mb}MB file")
        except ImportError:
            print("  (psutil not installed — skipped memory measurement)")
            result = resolve_read(f'"{big_file}"', cfg=cfg, workspace=ws)
            print(f"  Result starts with: {result[:200]}")


if __name__ == "__main__":
    test_include_preread()
    test_read_preread()
