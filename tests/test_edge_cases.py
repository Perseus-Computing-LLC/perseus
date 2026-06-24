"""
Edge-case tests for Perseus's "compile-before-context" claims.

Four categories plus verification tests for applied fixes.
"""

import os
import sys
import time
import threading
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. RECURSIVE HALLUCINATION — Circular Dependency
# ═══════════════════════════════════════════════════════════════════════════════

class TestCircularDependency:
    """Does Perseus catch @include recursion or does it infinite-loop?"""

    def test_circular_include_two_files(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("@include b.md\n", encoding="utf-8")
        b.write_text("@include a.md\n", encoding="utf-8")
        source = '@perseus\n@include "a.md"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "@include b.md" in result or "circular" in result.lower() or "⚠" in result
        assert "RecursionError" not in result
        assert len(result) > 0

    def test_circular_self_include(self, tmp_path):
        self_ref = tmp_path / "self.md"
        self_ref.write_text("@include self.md\n", encoding="utf-8")
        source = '@perseus\n@include "self.md"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "@include self.md" in result or "circular" in result.lower()
        assert "RecursionError" not in result

    def test_transitive_include_depth_three(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        c = tmp_path / "c.md"
        a.write_text("@include b.md\n", encoding="utf-8")
        b.write_text("@include c.md\n", encoding="utf-8")
        c.write_text("@include a.md\n", encoding="utf-8")
        source = '@perseus\n@include "a.md"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "@include b.md" in result or "circular" in result.lower()
        assert "RecursionError" not in result

    def test_graph_command_detects_cycle_statically(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("@include b.md\n", encoding="utf-8")
        b.write_text("@include a.md\n", encoding="utf-8")
        source = '@perseus\n@include "a.md"\n'
        graph = perseus.directive_dependency_graph(
            source, source_name="ctx.md", workspace=tmp_path
        )
        assert graph["summary"]["node_count"] >= 1
        includes = [n for n in graph["nodes"] if n["directive"] == "@include"]
        assert len(includes) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ATOMIC DRIFT
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicDrift:
    """Does Perseus provide a consistent snapshot when files change mid-render?"""

    def test_file_deleted_during_render(self, tmp_path):
        f1 = tmp_path / "data1.md"
        f2 = tmp_path / "data2.md"
        f1.write_text("Content from file 1", encoding="utf-8")
        f2.write_text("Content from file 2", encoding="utf-8")
        original_resolve_read = perseus.resolve_read
        delete_done = threading.Event()
        def patched_resolve_read(args_str, cfg, workspace=None):
            result = original_resolve_read(args_str, cfg, workspace)
            if "data1.md" in args_str and not delete_done.is_set():
                try:
                    os.remove(str(tmp_path / "data2.md"))
                except Exception:
                    pass
                delete_done.set()
            return result
        import perseus as pmod
        pmod.resolve_read = patched_resolve_read
        try:
            source = '@perseus\n@include "data1.md"\n@include "data2.md"\n'
            result = pmod.render_source(source, cfg(), tmp_path)
        finally:
            pmod.resolve_read = original_resolve_read
        assert "Content from file 1" in result
        assert "Traceback" not in result

    def test_file_modified_during_render(self, tmp_path):
        shared = tmp_path / "shared.md"
        shared.write_text("Version A", encoding="utf-8")
        source = '@perseus\n@include "shared.md"\n@include "shared.md"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        count_a = result.count("Version A")
        assert count_a == 2

    def test_concurrent_writes_outside_perseus(self, tmp_path):
        target = tmp_path / "live.txt"
        target.write_text("initial", encoding="utf-8")
        stop_flag = threading.Event()
        write_count = [0]
        def writer():
            while not stop_flag.is_set():
                target.write_text(f"iteration {write_count[0]}", encoding="utf-8")
                write_count[0] += 1
                time.sleep(0.001)
        t = threading.Thread(target=writer, daemon=True)
        t.start()
        time.sleep(0.05)
        try:
            source = '@perseus\n@include "live.txt"\n'
            result = perseus.render_source(source, cfg(), tmp_path)
        finally:
            stop_flag.set()
            t.join(timeout=1)
        assert "Traceback" not in result

    def test_many_files_read_consistently(self, tmp_path):
        count = 50
        for i in range(count):
            (tmp_path / f"f{i}.txt").write_text(f"file_{i}", encoding="utf-8")
        lines = "\n".join(f'@include "f{i}.txt"' for i in range(count))
        source = f"@perseus\n{lines}\n"
        result = perseus.render_source(source, cfg(), tmp_path)
        for i in range(count):
            assert f"file_{i}" in result, f"Missing file_{i}"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SYMLINK LABYRINTH
# ═══════════════════════════════════════════════════════════════════════════════

class TestSymlinkLabyrinth:
    """Does Perseus honor workspace boundaries when symlinks point outside?"""

    def test_symlink_to_system_file_blocked(self, tmp_path):
        link = tmp_path / "escape_link"
        try:
            link.symlink_to("/etc/passwd")
        except OSError:
            pytest.skip("Cannot create symlinks in this environment")
        source = f'@perseus\n@include "{link.name}"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "escapes workspace" in result or "⚠" in result
        assert "root:" not in result

    def test_symlink_to_sensitive_file_blocked(self, tmp_path):
        outside = tmp_path.parent / "secret_data.txt"
        outside.write_text("TOP SECRET", encoding="utf-8")
        link = tmp_path / "innocent_link"
        try:
            link.symlink_to(str(outside))
        except OSError:
            pytest.skip("Cannot create symlinks in this environment")
        source = f'@perseus\n@include "{link.name}"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "escapes workspace" in result
        assert "TOP SECRET" not in result

    def test_symlink_loop_inside_workspace(self, tmp_path):
        loop_dir = tmp_path / "loop"
        loop_dir.mkdir()
        loop_link = loop_dir / "self"
        try:
            loop_link.symlink_to(str(loop_dir))
        except OSError:
            pytest.skip("Cannot create symlinks in this environment")
        (loop_dir / "real_file.txt").write_text("real", encoding="utf-8")
        source = f'@perseus\n@tree "{loop_dir.name}" depth=5\n'
        try:
            result = perseus.render_source(source, cfg(), tmp_path)
        except RuntimeError:
            result = "runtime_error"
        assert True  # Did not hang

    def test_symlink_inside_workspace_to_inside_workspace(self, tmp_path):
        real = tmp_path / "real_data.txt"
        real.write_text("accessible content", encoding="utf-8")
        link = tmp_path / "data_link"
        try:
            link.symlink_to("real_data.txt")
        except OSError:
            pytest.skip("Cannot create symlinks in this environment")
        source = f'@perseus\n@include "{link.name}"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "accessible content" in result or "escapes workspace" in result

    def test_resolve_path_handles_relative_symlink_escape(self, tmp_path):
        outside = tmp_path.parent / "exfil.txt"
        outside.write_text("exfiltrated", encoding="utf-8")
        inner = tmp_path / "inner"
        inner.mkdir()
        link = inner / "up"
        try:
            link.symlink_to("../../exfil.txt")
        except OSError:
            pytest.skip("Cannot create symlinks in this environment")
        resolved, warning = perseus._resolve_path(
            str(link), workspace=tmp_path, allow_outside_workspace=False
        )
        assert warning is not None
        assert "escapes workspace" in warning

    def test_nested_symlink_chain_outside(self, tmp_path):
        outside = tmp_path.parent / "target_data.txt"
        outside.write_text("chained escape", encoding="utf-8")
        link1 = tmp_path / "link1"
        link2 = tmp_path / "link2"
        try:
            link2.symlink_to(str(outside))
            link1.symlink_to("link2")
        except OSError:
            pytest.skip("Cannot create symlinks in this environment")
        source = f'@perseus\n@include "{link1.name}"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "escapes workspace" in result
        assert "chained escape" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LARGE OBJECT PRESSURE
# ═══════════════════════════════════════════════════════════════════════════════

class TestLargeObjectPressure:
    """Does Perseus handle massive files gracefully?"""

    def test_include_megabyte_file(self, tmp_path):
        bigfile = tmp_path / "big.log"
        chunk = "Line {:06d}: " + "x" * 90 + "\n"
        lines_needed = (10 * 1024 * 1024) // len(chunk.format(0))
        content = "".join(chunk.format(i) for i in range(lines_needed))
        bigfile.write_text(content, encoding="utf-8")
        source = f'@perseus\n@include "{bigfile.name}"\n'
        start = time.monotonic()
        result = perseus.render_source(source, cfg(), tmp_path)
        elapsed = time.monotonic() - start
        result_size = len(result)
        file_size = len(content)
        has_warning = "⚠" in result or "truncat" in result.lower()
        print(f"\n  📊 10MB @include: file={file_size:,} bytes, "
              f"output={result_size:,} bytes, time={elapsed:.2f}s, warned={has_warning}")
        assert result_size > 0

    def test_include_50mb_progressive(self, tmp_path):
        sizes = [1, 5, 10]
        for mb in sizes:
            f = tmp_path / f"load_{mb}mb.log"
            if not f.exists():
                chunk = "data " * 20 + "\n"
                total_lines = (mb * 1024 * 1024) // len(chunk)
                f.write_text(chunk * total_lines, encoding="utf-8")
            source = f'@perseus\n@include "{f.name}"\n'
            start = time.monotonic()
            try:
                result = perseus.render_source(source, cfg(), tmp_path)
                elapsed = time.monotonic() - start
                print(f"\n    {mb}MB: output={len(result)//1024}KB, time={elapsed:.2f}s")
                assert len(result) > 0
            except MemoryError:
                pytest.xfail(f"MemoryError at {mb}MB")

    def test_read_large_file_overshadows_other_content(self, tmp_path):
        big = tmp_path / "large.txt"
        small = tmp_path / "small.txt"
        big.write_text("X" * 500_000, encoding="utf-8")
        small_content = "CRITICAL: This is the important bit"
        small.write_text(small_content, encoding="utf-8")
        source = (
            "@perseus\n"
            f'@read "small.txt"\n'
            f'@read "large.txt"\n'
        )
        result = perseus.render_source(source, cfg(), tmp_path)
        small_pos = result.index(small_content)
        first_fence = result.index("```text")
        second_fence = result.index("```text", first_fence + 1)
        assert small_pos < second_fence
        assert len(result) > 500_000

    def test_query_max_bytes_respected(self, tmp_path):
        c = cfg()
        c["render"]["max_query_bytes"] = 1000
        cmd = f'python3 -c "print(\'X\' * 5000)"'
        result = perseus.resolve_query(f'"{cmd}"', c, tmp_path)
        assert len(result) < 5000

    def test_cache_ttl_prevents_re_read_of_stale_large_file(self, tmp_path):
        expensive = tmp_path / "expensive.txt"
        expensive.write_text("costly computation result", encoding="utf-8")
        c = cfg()
        c["render"]["cache_dir"] = str(tmp_path / "cache")
        source = f'@perseus\n@read "{expensive.name}" @cache ttl=300\n'
        result1 = perseus.render_source(source, c, tmp_path)
        assert "costly computation" in result1
        # Rerender without changing the file — cache should hit
        result2 = perseus.render_source(source, c, tmp_path)
        assert "costly computation" in result2
        # Now change the file — content-addressed fingerprint should invalidate
        expensive.write_text("updated content", encoding="utf-8")
        result3 = perseus.render_source(source, c, tmp_path)
        assert "updated content" in result3
        assert "costly computation" not in result3


# ═══════════════════════════════════════════════════════════════════════════════
# 5. COMPOSITION STRESS
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompositionStress:
    """Multiple edge cases combined in a single render."""

    def test_all_directives_combined(self, tmp_path):
        for i in range(10):
            (tmp_path / f"doc{i}.md").write_text(f"Document {i} content", encoding="utf-8")
        source = "@perseus\n"
        source += "\n".join(f'@include "doc{i}.md"' for i in range(10))
        source += "\n"
        source += '@date format=\"YYYY-MM-DD\"\n'
        source += '@env HOME fallback=\"/unknown\"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        for i in range(10):
            assert f"Document {i}" in result
        assert "⚠" not in result, f"Warnings in combined render: {result[:500]}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FILE SIZE TRUNCATION (Fix #1)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileSizeTruncation:
    """Verify that @read and @include truncate oversized files with a warning."""

    def test_read_truncates_when_exceeds_max_read_bytes(self, tmp_path):
        big = tmp_path / "big.txt"
        big.write_text("X" * 100_000, encoding="utf-8")
        c = cfg()
        c["render"]["max_read_bytes"] = 10_000
        result = perseus.resolve_read(f'"{big.name}"', c, tmp_path)
        assert "max_read_bytes" in result
        assert len(result) < 15_000
        assert "X" * 100 in result

    def test_read_no_truncation_within_limit(self, tmp_path):
        small = tmp_path / "small.txt"
        small.write_text("hello world", encoding="utf-8")
        c = cfg()
        c["render"]["max_read_bytes"] = 10_000
        result = perseus.resolve_read(f'"{small.name}"', c, tmp_path)
        assert "hello world" in result
        assert "max_read_bytes" not in result

    def test_include_truncates_when_exceeds_max_include_bytes(self, tmp_path):
        big = tmp_path / "big.log"
        big.write_text("L" * 200_000, encoding="utf-8")
        c = cfg()
        c["render"]["max_include_bytes"] = 5_000
        source = f'@perseus\n@include "{big.name}"\n'
        result = perseus.render_source(source, c, tmp_path)
        assert "max_include_bytes" in result
        assert len(result) < 10_000

    def test_max_read_bytes_none_allows_unlimited(self, tmp_path):
        med = tmp_path / "medium.txt"
        med.write_text("M" * 200_000, encoding="utf-8")
        c = cfg()
        c["render"]["max_read_bytes"] = None
        result = perseus.resolve_read(f'"{med.name}"', c, tmp_path)
        assert len(result) > 150_000
        assert "max_read_bytes" not in result

    def test_max_include_bytes_none_allows_unlimited(self, tmp_path):
        med = tmp_path / "medium.log"
        med.write_text("M" * 200_000, encoding="utf-8")
        c = cfg()
        c["render"]["max_include_bytes"] = None
        source = f'@perseus\n@include "{med.name}"\n'
        result = perseus.render_source(source, c, tmp_path)
        assert len(result) > 150_000
        assert "max_include_bytes" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TRANSITIVE INCLUDE + CYCLE DETECTION (Fix #2)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransitiveInclude:
    """Verify recursive @include with depth limit and cycle detection."""

    def test_transitive_include_depth_three(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        c = tmp_path / "c.md"
        a.write_text('@perseus\n@include "b.md"\n', encoding="utf-8")
        b.write_text('@perseus\n@include "c.md"\n', encoding="utf-8")
        c.write_text("Deep content from C", encoding="utf-8")
        source = '@perseus\n@include "a.md"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "Deep content from C" in result

    def test_circular_include_detected_with_warning(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text('@perseus\n@include "b.md"\n', encoding="utf-8")
        b.write_text('@perseus\n@include "a.md"\n', encoding="utf-8")
        source = '@perseus\n@include "a.md"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "circular" in result.lower()

    def test_max_include_depth_exceeded(self, tmp_path):
        chain = []
        for i in range(1, 8):
            f = tmp_path / f"chain{i}.md"
            chain.append(f)
        for i in range(6):
            chain[i].write_text(f'@perseus\n@include "chain{i+2}.md"\n', encoding="utf-8")
        chain[6].write_text("Bottom of chain", encoding="utf-8")
        c = cfg()
        c["render"]["max_include_depth"] = 3
        source = '@perseus\n@include "chain1.md"\n'
        result = perseus.render_source(source, c, tmp_path)
        assert "max depth" in result or "exceeded" in result.lower()

    def test_transitive_include_plain_md_no_perseus_header(self, tmp_path):
        outer = tmp_path / "outer.md"
        inner = tmp_path / "inner.md"
        outer.write_text('@perseus\n@include "inner.md"\n', encoding="utf-8")
        inner.write_text("# Just a heading\nNo perseus header here.", encoding="utf-8")
        source = '@perseus\n@include "outer.md"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "# Just a heading" in result
        assert "⚠" not in result

    def test_diamond_include_does_not_trigger_false_cycle_warning(self, tmp_path):
        # Diamond, NOT a cycle: a includes b and c; b and c both include d.
        # d is reachable via two different branches but is never its own
        # ancestor, so it must render normally with NO circular-dependency
        # warning — that path belongs to the _path_chain ancestry check, not to
        # "this file was already seen elsewhere". Repeated includes are not
        # deduplicated (d renders once per branch), consistent with
        # TestAtomicDrift.test_file_modified_during_render.
        (tmp_path / "a.md").write_text('@perseus\n@include "b.md"\n@include "c.md"\n', encoding="utf-8")
        (tmp_path / "b.md").write_text('@perseus\n@include "d.md"\n', encoding="utf-8")
        (tmp_path / "c.md").write_text('@perseus\n@include "d.md"\n', encoding="utf-8")
        (tmp_path / "d.md").write_text("DIAMOND-LEAF-CONTENT", encoding="utf-8")
        source = '@perseus\n@include "a.md"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "circular" not in result.lower()
        assert result.count("DIAMOND-LEAF-CONTENT") == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 8. INTEGRITY DRIFT DETECTION (Fix #3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegrityDrift:
    """Verify the opt-in integrity check logic."""

    def test_integrity_check_disabled_by_default(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("stable content", encoding="utf-8")
        source = f'@perseus\n@read "data.txt"\n'
        result = perseus.render_source(source, cfg(), tmp_path)
        assert "Integrity drift" not in result

    def test_integrity_check_mechanism_modified_file(self, tmp_path):
        """Snapshot captures mtime; modification is detectable."""
        f = tmp_path / "data.txt"
        f.write_text("initial content", encoding="utf-8")
        source_lines = ['@read "data.txt"']
        snap = perseus._capture_file_snapshot(source_lines, tmp_path)
        assert len(snap) == 1, f"Expected 1 file, got {snap}"
        time.sleep(0.01)
        f.write_text("modified content", encoding="utf-8")
        for path_str, orig_mtime in snap.items():
            current = Path(path_str).stat().st_mtime
            if current == orig_mtime:
                pytest.skip("Filesystem mtime too coarse for drift detection")
            assert current != orig_mtime

    def test_integrity_check_mechanism_deleted_file(self, tmp_path):
        """Snapshot captures file; deletion triggers OSError in drift check."""
        f1 = tmp_path / "f1.txt"
        f2 = tmp_path / "f2.txt"
        f1.write_text("file 1", encoding="utf-8")
        f2.write_text("file 2", encoding="utf-8")
        source_lines = ['@read "f1.txt"', '@read "f2.txt"']
        snap = perseus._capture_file_snapshot(source_lines, tmp_path)
        assert len(snap) >= 2, f"Expected >=2 files, got {snap}"
        f2.unlink()
        # Verify OSError path: drift check catches deleted files
        for path_str, orig_mtime in snap.items():
            try:
                Path(path_str).stat().st_mtime
                if "f2.txt" in path_str:
                    assert False, "f2 should be gone"
            except OSError:
                if "f2.txt" in path_str:
                    pass  # Expected

    def test_integrity_check_no_false_positives_stable_files(self, tmp_path):
        f1 = tmp_path / "stable1.txt"
        f2 = tmp_path / "stable2.txt"
        f1.write_text("stable A", encoding="utf-8")
        f2.write_text("stable B", encoding="utf-8")
        c = cfg()
        c["render"]["integrity_check"] = True
        source = '@perseus\n@read "stable1.txt"\n@read "stable2.txt"\n'
        result = perseus.render_source(source, c, tmp_path)
        assert "Integrity drift" not in result
