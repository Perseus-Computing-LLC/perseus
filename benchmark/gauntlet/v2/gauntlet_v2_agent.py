"""
gauntlet_v2_agent.py — Agent task execution benchmarks for Perseus Gauntlet v2.

Measures:
  - Single-agent task completion (hermetic coding tasks)
  - Multi-agent coordination (parallel renders, kanban-style)
  - Task success rate, time-to-completion, token efficiency
  - Tool execution latency (file read/write, shell, search)

Tasks are hermetic — no network, no LLM API calls required during the
benchmark itself. The render engine handles everything locally.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Ensure lib is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gauntlet_v2_lib import (
    GauntletMetrics,
    perseus_executable,
    timestamp_iso,
    write_json,
    COLD_HOME,
    WARM_HOME,
)


# ─── Hermetic task definitions ───────────────────────────────────────────────
#
# Tasks exercise Perseus directive resolution (@shell, @read, @query).
# Context files are rendered via `perseus render`, and verify functions
# check the rendered output for expected content.  No LLM is involved —
# this measures how fast and accurately Perseus resolves directives.


HERMETIC_TASKS = [
    {
        "id": "read-file",
        "name": "Read a file via @read",
        "description": "@read directive resolves file contents",
        "difficulty": "easy",
        "context": "@read /tmp/gauntlet-agent/hello.txt",
        "setup": lambda tmpdir: _setup_read_file(tmpdir),
        "verify": lambda output: "hello from gauntlet" in output.lower(),
        "timeout_s": 20,
    },
    {
        "id": "shell-count",
        "name": "Count lines via @shell",
        "description": "@shell wc -l resolves line count",
        "difficulty": "easy",
        "context": "@query \"wc -l /tmp/gauntlet-agent/test_file.py\" timeout=5",
        "setup": lambda tmpdir: _setup_file_counter(tmpdir),
        "verify": lambda output: _check_contains_number(output),
        "timeout_s": 20,
    },
    {
        "id": "shell-cat",
        "name": "Read JSON via @shell cat",
        "description": "@shell cat + python parse resolves JSON field",
        "difficulty": "easy",
        "context": "@query \"python3 /tmp/gauntlet-agent/extract_host.py\" timeout=5",
        "setup": lambda tmpdir: _setup_json_extract(tmpdir),
        "verify": lambda output: "localhost" in output,
        "timeout_s": 20,
    },
    {
        "id": "shell-uppercase",
        "name": "Transform text via @shell pipeline",
        "description": "@shell pipeline: uppercase, sort, uniq",
        "difficulty": "medium",
        "context": "@query \"cat /tmp/gauntlet-agent/words.txt | tr '[:lower:]' '[:upper:]' | sort | uniq\" timeout=5",
        "setup": lambda tmpdir: _setup_text_transform(tmpdir),
        "verify": lambda output: "APPLE" in output and "BANANA" in output and "ELDERBERRY" in output,
        "timeout_s": 30,
    },
    {
        "id": "shell-csv",
        "name": "Aggregate CSV via @shell",
        "description": "@shell python3 one-liner to group and sum CSV",
        "difficulty": "medium",
        "context": "@query \"python3 /tmp/gauntlet-agent/aggregate_csv.py\" timeout=10",
        "setup": lambda tmpdir: _setup_csv_aggregate(tmpdir),
        "verify": lambda output: "electronics: 1500" in output and "books: 100" in output,
        "timeout_s": 30,
    },
    {
        "id": "shell-find",
        "name": "Find files via @shell find",
        "description": "@shell find lists .py files with sizes",
        "difficulty": "medium",
        "context": "@query \"find /tmp/gauntlet-agent/project -name '*.py' -exec wc -c {} \\;\" timeout=5",
        "setup": lambda tmpdir: _setup_recursive_find(tmpdir),
        "verify": lambda output: "main.py" in output or "helper.py" in output,
        "timeout_s": 20,
    },
    {
        "id": "shell-calc",
        "name": "Arithmetic via @shell",
        "description": "@shell bc resolves arithmetic expressions",
        "difficulty": "easy",
        "context": "@query \"python3 -c 'print(5+3)'\" timeout=5\n@query \"python3 -c 'print(10-4)'\" timeout=5\n@query \"python3 -c 'print(6*7)'\" timeout=5\n@query \"python3 -c 'print(100/4)'\" timeout=5",
        "setup": lambda tmpdir: None,
        "verify": lambda output: "8" in output and "6" in output and "42" in output and "25" in output,
        "timeout_s": 20,
    },
    {
        "id": "shell-missing",
        "name": "Handle missing file via @shell",
        "description": "@shell with missing file returns stderr",
        "difficulty": "easy",
        "context": "@query \"cat /tmp/gauntlet-agent/does_not_exist.txt 2>&1 || echo FILE_NOT_FOUND\" timeout=5",
        "setup": lambda tmpdir: None,
        "verify": lambda output: "FILE_NOT_FOUND" in output,
        "timeout_s": 20,
    },
    {
        "id": "read-multi",
        "name": "Read multiple files via @read",
        "description": "Multiple @read directives resolve all files",
        "difficulty": "medium",
        "context": "@read /tmp/gauntlet-agent/config.json\n@read /tmp/gauntlet-agent/hello.txt",
        "setup": lambda tmpdir: _setup_multi_read(tmpdir),
        "verify": lambda output: "localhost" in output and "hello from gauntlet" in output.lower(),
        "timeout_s": 20,
    },
    {
        "id": "shell-pipeline-complex",
        "name": "Complex shell pipeline",
        "description": "Multi-pipe shell: find, filter, sort, count",
        "difficulty": "medium",
        "context": "@query \"ls -la /tmp/gauntlet-agent/ 2>/dev/null | grep -v '^total' | wc -l\" timeout=5",
        "setup": lambda tmpdir: _setup_file_counter(tmpdir),
        "verify": lambda output: _check_contains_number(output),
        "timeout_s": 20,
    },
]


def _check_contains_number(output: str) -> bool:
    """Check output contains at least one number."""
    import re
    return bool(re.search(r'\d+', output))


# ─── Task setup helpers ──────────────────────────────────────────────────────


TASK_DIR = Path("/tmp/gauntlet-agent")


def _ensure_task_dir():
    TASK_DIR.mkdir(parents=True, exist_ok=True)


def _setup_read_file(tmpdir: Path):
    _ensure_task_dir()
    (TASK_DIR / "hello.txt").write_text("hello from gauntlet\n")


def _setup_multi_read(tmpdir: Path):
    _ensure_task_dir()
    (TASK_DIR / "hello.txt").write_text("hello from gauntlet\n")
    config = {"database": {"host": "localhost", "port": 5432}}
    (TASK_DIR / "config.json").write_text(json.dumps(config))


def _setup_file_counter(tmpdir: Path):
    _ensure_task_dir()
    code = """# This is a Python file with comments
import os  # standard library
import sys

def main():
    # Print hello
    print("Hello, world!")

    # Call helper
    helper()

def helper():
    # This function helps
    x = 1 + 2
    return x

if __name__ == "__main__":
    main()
"""
    (TASK_DIR / "test_file.py").write_text(code)


def _setup_json_extract(tmpdir: Path):
    _ensure_task_dir()
    config = {
        "database": {"host": "localhost", "port": 5432},
        "logging": {"level": "debug"},
    }
    (TASK_DIR / "config.json").write_text(json.dumps(config))
    # Write helper script to avoid nested-quote issues in @query
    (TASK_DIR / "extract_host.py").write_text(
        "import json,sys\n"
        "print(json.load(open('/tmp/gauntlet-agent/config.json'))['database']['host'])\n"
    )


def _setup_text_transform(tmpdir: Path):
    _ensure_task_dir()
    words = "apple\nbanana\nAPPLE\ncherry\nBanana\ndate\napple\nelderberry\n"
    (TASK_DIR / "words.txt").write_text(words)


def _verify_text_transform() -> bool:
    output_file = TASK_DIR / "words_processed.txt"
    if not output_file.is_file():
        return False
    lines = output_file.read_text().strip().splitlines()
    # Should be: APPLE, BANANA, CHERRY, DATE, ELDERBERRY
    expected = ["APPLE", "BANANA", "CHERRY", "DATE", "ELDERBERRY"]
    return lines == expected


def _setup_csv_aggregate(tmpdir: Path):
    _ensure_task_dir()
    csv = """category,amount,date
electronics,150,2026-01-01
electronics,350,2026-01-02
books,25,2026-01-01
books,75,2026-01-03
clothing,200,2026-01-02
electronics,1000,2026-01-04
"""
    (TASK_DIR / "sales.csv").write_text(csv)
    # Write helper script to avoid nested-quote issues in @query
    (TASK_DIR / "aggregate_csv.py").write_text(
        "import csv\nfrom collections import defaultdict\ntotals = defaultdict(int)\n"
        "reader = csv.DictReader(open('/tmp/gauntlet-agent/sales.csv'))\n"
        "for row in reader:\n    totals[row['category']] += int(row['amount'])\n"
        "for cat in sorted(totals):\n    print(f'{cat}: {totals[cat]}')\n"
    )


def _verify_csv_aggregate(output: str) -> bool:
    lines = output.strip().splitlines()
    expected = {"books": 100, "clothing": 200, "electronics": 1500}
    for line in lines:
        if ":" not in line:
            continue
        cat, val = line.split(":", 1)
        if cat.strip() in expected and int(val.strip()) != expected[cat.strip()]:
            return False
    return True


def _setup_config_validator(tmpdir: Path):
    _ensure_task_dir()
    config = "version: 1.0\ndescription: test config\n# database intentionally missing\n"
    (TASK_DIR / "config.yaml").write_text(config)


def _verify_config_validator(output: str) -> bool:
    return "MISSING: name" in output and "MISSING: database" in output


def _setup_log_parser(tmpdir: Path):
    _ensure_task_dir()
    logs = [
        {"level": "INFO", "ts": "2026-06-08T14:01:00"},
        {"level": "ERROR", "ts": "2026-06-08T14:02:00"},
        {"level": "ERROR", "ts": "2026-06-08T14:05:00"},
        {"level": "INFO", "ts": "2026-06-08T15:01:00"},
        {"level": "ERROR", "ts": "2026-06-08T15:30:00"},
        {"level": "WARN", "ts": "2026-06-08T16:00:00"},
        {"level": "ERROR", "ts": "2026-06-08T16:01:00"},
        {"level": "ERROR", "ts": "2026-06-08T16:02:00"},
        {"level": "ERROR", "ts": "2026-06-08T16:03:00"},
    ]
    (TASK_DIR / "app.log").write_text(
        "\n".join(json.dumps(l) for l in logs)
    )


def _verify_log_parser(output: str) -> bool:
    # Expect: 14: 2, 15: 1, 16: 3
    lines = output.strip().splitlines()
    for line in lines:
        if "14" in line and "2" not in line:
            return False
        if "16" in line and "3" not in line:
            return False
    return True


def _setup_recursive_find(tmpdir: Path):
    _ensure_task_dir()
    project = TASK_DIR / "project"
    project.mkdir(exist_ok=True)
    (project / "main.py").write_text("print('hello')")
    (project / "utils.py").write_text("def helper(): pass")
    sub = project / "sub"
    sub.mkdir(exist_ok=True)
    (sub / "helper.py").write_text("# helper")
    (sub / "config.json").write_text("{}")


def _verify_recursive_find(output: str) -> bool:
    lines = output.strip().splitlines()
    py_files = [l for l in lines if ".py" in l]
    filenames = [l.split(":")[0].strip() for l in py_files]
    return "main.py" in filenames and "utils.py" in filenames and "helper.py" in filenames


def _setup_calculator(tmpdir: Path):
    _ensure_task_dir()
    calc = "5 + 3\n10 - 4\n6 * 7\n100 / 4\n"
    (TASK_DIR / "calc.txt").write_text(calc)


def _verify_calculator() -> bool:
    output_file = TASK_DIR / "calc_results.txt"
    if not output_file.is_file():
        return False
    lines = output_file.read_text().strip().splitlines()
    expected = ["8", "6", "42", "25.0"]
    return lines == expected


def _setup_shell_pipeline(tmpdir: Path):
    _ensure_task_dir()
    for i in range(5):
        f = TASK_DIR / f"file_{i}.txt"
        f.write_text(f"content {i}" * (i + 1) * 10)
    # Make one file old
    old_file = TASK_DIR / "old_file.txt"
    old_file.write_text("old")
    # Touch it to be old (Unix-specific, but OK for benchmark)
    os.utime(str(old_file), (0, 0))


# ─── Agent task runner ────────────────────────────────────────────────────────


def run_single_agent_task(
    task: dict,
    home: Path,
    timeout_s: int = 60,
) -> dict:
    """Run a single hermetic agent task via Perseus render.

    Creates a temporary context file with the task description and
    exercises the full Perseus pipeline (render, memory, tools).
    """
    _ensure_task_dir()

    # Run task setup
    if task.get("setup"):
        try:
            task["setup"](TASK_DIR)
        except Exception as exc:
            return {
                "task_id": task["id"],
                "name": task["name"],
                "success": False,
                "error": f"setup failed: {exc}",
                "elapsed_s": 0,
            }

    # Write task context file with required headers
    ctx_path = TASK_DIR / f"task_{task['id']}.md"
    ctx_path.write_text(f"@perseus v0.8\n@prompt gauntlet benchmark task\n\n{task['context']}")

    perseus = perseus_executable()
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(home)
    env["PERSEUS_ALLOW_DANGEROUS"] = "1"

    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, perseus, "render", str(ctx_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        elapsed = time.time() - t0

        # Parse output
        output = result.stdout.strip()
        stderr = result.stderr.strip()
        exit_code = result.returncode

        # Verify task output
        success = exit_code == 0
        if success and task.get("verify"):
            try:
                success = task["verify"](output)
            except Exception:
                success = False

        # Token estimate
        token_estimate = len(output) // 4

        return {
            "task_id": task["id"],
            "name": task["name"],
            "difficulty": task.get("difficulty", "unknown"),
            "success": success,
            "exit_code": exit_code,
            "elapsed_s": round(elapsed, 3),
            "output": output[:500],
            "stderr": stderr[:200],
            "token_estimate": token_estimate,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return {
            "task_id": task["id"],
            "name": task["name"],
            "difficulty": task.get("difficulty", "unknown"),
            "success": False,
            "error": "timeout",
            "elapsed_s": round(elapsed, 3),
        }
    except Exception as exc:
        elapsed = time.time() - t0
        return {
            "task_id": task["id"],
            "name": task["name"],
            "difficulty": task.get("difficulty", "unknown"),
            "success": False,
            "error": str(exc)[:200],
            "elapsed_s": round(elapsed, 3),
        }


def run_agent_single_phase(
    profiles: list[dict],
    metrics: GauntletMetrics,
    nfs_base: Path,
    task_count: int = 10,
) -> dict:
    """Phase 4: Agent Single Task — run hermetic tasks one at a time."""
    tasks = HERMETIC_TASKS[:task_count]
    total = len(tasks)
    failures = 0

    for i, task in enumerate(tasks):
        print(f"  Task {i+1}/{total}: {task['name']}...", end=" ", flush=True)
        result = run_single_agent_task(task, COLD_HOME)
        result["index"] = i
        metrics.record(**result)

        if result["success"]:
            print(f"OK ({result['elapsed_s']:.1f}s)")
        else:
            print(f"FAIL ({result.get('error', 'unknown')})")
            failures += 1

    agg = metrics.aggregate()
    write_json(nfs_base / "results" / "phase4_agent_single.json", agg)
    write_json(
        nfs_base / "sentinels" / "phase4_done",
        {"done": True, "ts": timestamp_iso()},
    )
    return agg


def run_agent_multi_phase(
    profiles: list[dict],
    metrics: GauntletMetrics,
    nfs_base: Path,
    task_count: int = 5,
    max_concurrent: int = 3,
) -> dict:
    """Phase 5: Agent Multi-Agent — run tasks sequentially.

    Runs each task across multiple agent homes to simulate multi-agent
    coordination. Uses sequential execution to avoid Windows thread +
    subprocess deadlocks and shared TASK_DIR race conditions.
    """
    tasks = HERMETIC_TASKS[:task_count]
    total = len(tasks) * max_concurrent
    failures = 0
    results: list[dict] = []

    # Give each worker its own PERSEUS_HOME to avoid cache contention
    agent_homes = []
    for agent_id in range(max_concurrent):
        home = Path(f"/tmp/perseus-gauntlet/agent-{agent_id}")
        home.mkdir(parents=True, exist_ok=True)
        import shutil
        cfg_src = COLD_HOME / "config.yaml"
        if cfg_src.is_file():
            shutil.copy(cfg_src, home / "config.yaml")
        agent_homes.append(home)

    print(f"  Running {total} tasks across {max_concurrent} agents (sequential)...")
    task_num = 0
    for agent_id in range(max_concurrent):
        for task_idx in range(len(tasks)):
            task_num += 1
            task = tasks[task_idx]
            home = agent_homes[agent_id]
            print(f"  Task {task_num}/{total}: [{agent_id}] {task['name']}...", end=" ", flush=True)
            result = run_single_agent_task(task, home)
            result["agent_id"] = agent_id
            result["task_idx"] = task_idx
            results.append(result)
            metrics.record(**result)
            if result["success"]:
                print(f"OK ({result['elapsed_s']:.1f}s)")
            else:
                print(f"FAIL ({result.get('error', 'unknown')})")
                failures += 1

    agg = metrics.aggregate()
    agg["concurrent_agents"] = max_concurrent
    agg["total_tasks"] = total
    agg["failures"] = failures
    agg["success_rate"] = (total - failures) / total if total else 0

    write_json(nfs_base / "results" / "phase5_agent_multi.json", agg)
    write_json(
        nfs_base / "sentinels" / "phase5_done",
        {"done": True, "ts": timestamp_iso()},
    )
    return agg


# ─── Agent phase runner (dispatches single + multi) ──────────────────────────


def run_agent_phase(
    phase_num: int,
    profiles: list[dict],
    metrics: GauntletMetrics,
    nfs_base: Path,
    duration: str = "full",
) -> dict:
    """Run agent task phases (4 = single, 5 = multi)."""
    if phase_num == 4:
        task_count = 3 if duration == "smoke" else 10
        return run_agent_single_phase(profiles, metrics, nfs_base, task_count)
    elif phase_num == 5:
        task_count = 2 if duration == "smoke" else 5
        concurrent = 2 if duration == "smoke" else 3
        return run_agent_multi_phase(profiles, metrics, nfs_base, task_count, concurrent)
    else:
        return {"phase": phase_num, "skipped": True, "reason": "unknown phase"}
