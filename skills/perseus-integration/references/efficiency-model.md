# Perseus Token Efficiency Model

## Core Insight

Perseus is a long-session efficiency play. Context is injected ONCE at session
start and reused across all turns. The LLM never wastes tokens on orientation.

## The Math

Context cost:     1,600 tokens (one-time, at session start)
Per-turn savings:   300 tokens (avg 1.5 tool calls avoided x 200 tokens each)
Breakeven:         ~5 turns

## Session Length Impact

| Session Type | Turns | Net Tokens | Verdict |
|---|---|---|---|
| One-shot query | 1 | -1,300 | Overhead |
| Quick task | 3 | -700 | Marginal |
| Debug session | 5 | ~0 | Breakeven |
| Debug session | 8 | +800 | Net positive |
| Feature build | 15 | +2,900 | Strong win |
| Deep work | 30 | +7,400 | Major win |

## What Gets Saved

Without Perseus, the LLM burns turns discovering:
- "What services are running?" (2-4 calls, ~400-800 tokens)
- "What tools do I have?" (1-2 calls, ~200-400 tokens)
- "What did we do last?" (1-2 calls, ~200-400 tokens)
- "What machine is this?" (4 commands, ~400-800 tokens)
- "Recent activity?" (1-2 calls, ~200-400 tokens)

Perseus pre-answers ALL of these in ~1,600 tokens.

## Benchmark Script

```bash
cd /path/to/workspace
python3 benchmark_perseus.py
```

Runs 4 task types with and without Perseus context, measuring token consumption.
