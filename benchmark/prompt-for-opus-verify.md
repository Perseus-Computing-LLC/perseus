# Perseus v1.0.2 — Windows Verification Suite

You are running on Windows 11 with native Python 3.14.2 (no WSL). Your job is to
verify that Perseus v1.0.2 actually works on Windows — all four bugs from the
original benchmark are fixed — and to collect cold-vs-warm benchmark numbers.

## Prerequisites

```powershell
pip install perseus-ctx==1.0.2 pyyaml psutil
perseus --version
# Should print: perseus v1.0.2
```

If pip install fails or --version shows 1.0.1, the PyPI publish didn't land yet.
Grab the latest from GitHub:

```powershell
git clone https://github.com/tcconnally/perseus.git
cd perseus
# Use perseus.py directly: python perseus.py render ...
```

## Task 1 — Bug Fix Verification (BLOCKING)

Run each test and report PASS/FAIL with evidence.

### Bug #1: write_text encoding
```powershell
mkdir C:\tmp\perseus-verify
cd C:\tmp\perseus-verify
perseus init . --output .hermes.md
perseus render .perseus\context.md --output .hermes.md
# If this works without UnicodeEncodeError: PASS
# The rendered output will contain 📌 (emoji) — verify it's there
Get-Content .hermes.md | Select-String "📌"
```

### Bug #2: /bin/bash unreachable
```powershell
# Create a minimal context that uses @query
@"
@perseus v0.4
@query "echo Windows-works"
"@ | Out-File -Encoding UTF8 .perseus\context.md
perseus render .perseus\context.md --output .hermes.md
# If it renders without [WinError 3] or "The system cannot find the file": PASS
# If it shows "⚠ @query error": FAIL
Get-Content .hermes.md
```

### Bug #3: binary stdout NoneType
```powershell
# Create a context that produces binary output
@"
@perseus v0.4
@query "python -c ""import sys; sys.stdout.buffer.write(b'\x00\x01\x02')"""
"@ | Out-File -Encoding UTF8 .perseus\context.md
perseus render .perseus\context.md --output .hermes.md
# If it renders without "NoneType" error: PASS
# A warning about binary output or "(no output)" is acceptable
Get-Content .hermes.md
```

### Bug #4: --help crash (Mnēmē macron)
```powershell
perseus --help
# If it prints help text without UnicodeEncodeError: PASS
# You should see "Mnēmē" rendered correctly
```

## Task 2 — Cold vs Warm Benchmark on Windows

Run the scaling sweep with caching enabled to get Windows warm numbers.
This is the number that matters — we have Linux warm at 0.52s for 10K queries.
We need the Windows equivalent.

```powershell
cd C:\tmp\perseus-verify

# Create a test harness
python -c "
import json, os, subprocess, time
from pathlib import Path

PERSEUS = 'perseus'  # or 'python C:\\path\\to\\perseus.py'
RESULTS = {}

for N in [10, 50, 100, 200, 500, 1000, 2000]:
    d = Path(f'C:\\tmp\\perseus-warm\\n{N}')
    d.mkdir(parents=True, exist_ok=True)
    (d / '.perseus').mkdir(exist_ok=True)
    
    cfg = 'render:\n  allow_query_shell: true\n  max_query_bytes: 262144\n'
    (d / '.perseus' / 'config.yaml').write_text(cfg, encoding='utf-8')
    
    # Context with @cache ttl=300 on all queries
    lines = ['@perseus v0.4\n']
    for i in range(N):
        lines.append(f'@query \"echo {i}\" @cache ttl=300\n')
    (d / '.perseus' / 'context.md').write_text(''.join(lines), encoding='utf-8')
    
    # Cold run (prime cache)
    env = {**os.environ, 'PYTHONUTF8': '1'}
    t0 = time.perf_counter()
    subprocess.run([PERSEUS, 'render', str(d/'.perseus'/'context.md'), 
                    '--output', str(d/'cold.md')], capture_output=True, timeout=300)
    cold = time.perf_counter() - t0
    
    # Warm run (cache hit)
    t0 = time.perf_counter()
    subprocess.run([PERSEUS, 'render', str(d/'.perseus'/'context.md'),
                    '--output', str(d/'warm.md')], capture_output=True, timeout=300)
    warm = time.perf_counter() - t0
    
    RESULTS[N] = {'cold': round(cold,2), 'warm': round(warm,3)}
    speedup = cold/warm if warm > 0 else 0
    print(f'N={N:>4}: cold={cold:.1f}s  warm={warm:.2f}s  ({speedup:.0f}x)')

Path('C:\\tmp\\perseus-warm\\results.json').write_text(json.dumps(RESULTS, indent=2))
print('Saved to C:\\tmp\\perseus-warm\\results.json')
"
```

If Python 3.14 behaves differently than 3.12 (subprocess text= behavior, encoding defaults),
note any differences.

## Task 3 — End-to-End pip install Flow

On a CLEAN directory (no prior Perseus state):

```powershell
mkdir C:\tmp\perseus-fresh
cd C:\tmp\perseus-fresh
pip install perseus-ctx==1.0.2
perseus --version
perseus init .
perseus render .perseus\context.md --output .hermes.md
Get-Content .hermes.md | Select-Object -First 30
```

Every step must work without `$env:PYTHONUTF8 = "1"`. If any step requires it,
Bug #4 is not fully fixed (report what step failed and the error).

## Task 4 (Optional) — Adversarial New Features

Test the features shipped in v1.0.2:

### stdout cap
```powershell
# Create a context that generates 5MB output
@"
@perseus v0.4
@query "python -c ""print('x' * 5000000)"""
"@ | Out-File -Encoding UTF8 .perseus\context.md
perseus render .perseus\context.md --output .hermes.md
# Output should be ~256KB, not 5MB. Should contain "truncated" marker.
(Get-Item .hermes.md).Length
Get-Content .hermes.md | Select-String "truncated"
```

### Configurable timeout
```powershell
@"
@perseus v0.4
@query "python -c ""import time; time.sleep(10)""" timeout=3
"@ | Out-File -Encoding UTF8 .perseus\context.md
perseus render .perseus\context.md --output .hermes.md
# Should time out at ~3s and show "(3s)" in the warning, not "(30s)"
Measure-Command { perseus render .perseus\context.md --output .hermes.md }
Get-Content .hermes.md
```

## Deliverables

1. Task 1: PASS/FAIL for each of the 4 bugs with the exact error or confirmation output.
2. Task 2: Cold vs warm numbers for Windows at 10, 50, 100, 200, 500, 1000, 2000 queries.
   Include the results.json.
3. Task 3: Does `pip install perseus-ctx` + `perseus init` + `perseus render` work on a clean
   Windows install without PYTHONUTF8?
4. Task 4 (optional): Do max_query_bytes and timeout=N work correctly on Windows?

## Context (to save you from re-discovering)

- Perseus is a live context engine for AI assistants. It pre-resolves workspace state
  into a markdown document before the AI assistant's context window loads.
- v1.0.2 shipped: 4 Windows bug fixes, stdout cap, configurable timeout, parallel
  @services/@query, 3 integrations (VS Code, Claude Code hook, GitHub Action).
- Linux cold→warm benchmark: 2000 queries at 27s cold → 0.46s warm (59×).
  10000 queries at 0.52s warm. Cache makes render time constant.
- The Perseus repo is at https://github.com/tcconnally/perseus (branch: main).
- The benchmark harness files are in benchmark/heavy/.
- The original benchmark that found the 4 bugs is at COLD-START-BENCHMARK-2026-05-23.md.
