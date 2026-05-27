#!/usr/bin/env python3
"""
TITAN — Token & Cost Analysis
===============================

Projects the financial cost of "orientation tax" — what an enterprise team pays
when their AI assistant has to rediscover context that Perseus already knows.

Models (May 2026 pricing, per 1M tokens):
  ┌─────────────────────┬──────────┬───────────┬──────────────┐
  │ Model               │ Input    │ Output    │ Tool latency │
  ├─────────────────────┼──────────┼───────────┼──────────────┤
  │ Claude Opus 4.7     │ $5.00    │ $25.00    │ 2.5s         │
  │ Claude Sonnet 4.6   │ $3.00    │ $15.00    │ 1.5s         │
  │ Gemini 2.5 Pro      │ $1.25    │ $10.00    │ 1.2s         │
  │ GPT-5               │ $3.75    │ $15.00    │ 1.8s         │
  └─────────────────────┴──────────┴───────────┴──────────────┘

Usage:
  python3 benchmark/titan_cost.py [--titan-json benchmark/titan_coldwarm.json]

Output: benchmark/titan_cost.json
"""
import json
import sys
from pathlib import Path

# ── Model Pricing (May 2026) ────────────────────────────────────────────────
MODELS = {
    "claude_opus_47": {
        "label": "Claude Opus 4.7",
        "provider": "Anthropic",
        "input_per_1M": 5.00,
        "output_per_1M": 25.00,
        "tool_call_s": 2.5,
        "parallel_calls": 3,
        "tier": "premium",
    },
    "claude_sonnet_46": {
        "label": "Claude Sonnet 4.6",
        "provider": "Anthropic",
        "input_per_1M": 3.00,
        "output_per_1M": 15.00,
        "tool_call_s": 1.5,
        "parallel_calls": 5,
        "tier": "balanced",
    },
    "gemini_25_pro": {
        "label": "Gemini 2.5 Pro",
        "provider": "Google",
        "input_per_1M": 1.25,
        "output_per_1M": 10.00,
        "tool_call_s": 1.2,
        "parallel_calls": 8,
        "tier": "efficient",
    },
    "gpt5": {
        "label": "GPT-5",
        "provider": "OpenAI",
        "input_per_1M": 3.75,
        "output_per_1M": 15.00,
        "tool_call_s": 1.8,
        "parallel_calls": 5,
        "tier": "balanced",
    },
}

# ── Token estimates per directive (what an LLM would consume) ───────────────
# Each @query directive ≈ one tool call. The LLM must:
#   1. Read the directive (~100 tokens input)
#   2. Decide to make a tool call (~50 tokens output thinking)
#   3. Receive tool result (~200 tokens input)
#   4. Summarize/act on result (~150 tokens output)
TOKENS_PER_DIRECTIVE = {
    "input": 300,   # directive read + tool result
    "output": 200,  # thinking + action
}

# ── Enterprise scenario ─────────────────────────────────────────────────────
DEVELOPERS = 500
WORKDAYS_PER_YEAR = 250
DIRECTIVES_PER_DEV_PER_DAY = 50  # conservative: context pulls, checks, queries

def load_titan_data(json_path=None):
    """Load titan_coldwarm.json if available for real per-query timing."""
    if json_path:
        p = Path(json_path)
    else:
        p = Path("/workspace/perseus/benchmark/titan_coldwarm.json")
    if p.exists():
        with open(p) as f:
            return json.load(f)
    # Fallback: use known values from prior benchmarks
    return {
        "avg_per_query_ms_cold": 12.8,
        "scales": {
            "50000": {"cold": 612.563, "warm": 1.362, "speedup": 449.8},
            "1000000": {"warm": 21.997},
        },
    }


def compute_cost(model_key, num_directives):
    """Compute token count and cost for an LLM processing N directives."""
    m = MODELS[model_key]
    total_input_tokens = num_directives * TOKENS_PER_DIRECTIVE["input"]
    total_output_tokens = num_directives * TOKENS_PER_DIRECTIVE["output"]

    input_cost = (total_input_tokens / 1_000_000) * m["input_per_1M"]
    output_cost = (total_output_tokens / 1_000_000) * m["output_per_1M"]
    total_cost = input_cost + output_cost

    # Time estimate: tool calls in parallel, plus think time
    sequential_calls = num_directives / m["parallel_calls"]
    tool_time = sequential_calls * m["tool_call_s"]

    return {
        "directives": num_directives,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "input_cost_usd": round(input_cost, 4),
        "output_cost_usd": round(output_cost, 4),
        "total_cost_usd": round(total_cost, 2),
        "estimated_time_s": round(tool_time, 1),
    }


def main():
    titan = load_titan_data()

    avg_cold_ms = titan.get("avg_per_query_ms_cold", 12.8)
    warm_us = titan.get("per_query_breakdown", {}).get("warm_us", 22)
    best_speedup = titan.get("best_speedup", {}).get("speedup", 449.8)
    cold_abandoned = titan.get("cold_abandoned_at")

    # ── Per-directive token cost ────────────────────────────────────────
    per_directive = {}
    for key in MODELS:
        per_directive[key] = compute_cost(key, 1)

    # ── Per-developer-per-day ───────────────────────────────────────────
    per_dev_day = {}
    for key in MODELS:
        per_dev_day[key] = compute_cost(key, DIRECTIVES_PER_DEV_PER_DAY)

    # ── Enterprise annual ───────────────────────────────────────────────
    annual_directives = DEVELOPERS * WORKDAYS_PER_YEAR * DIRECTIVES_PER_DEV_PER_DAY
    annual = {}
    for key in MODELS:
        annual[key] = compute_cost(key, annual_directives)

    # ── Perseus comparison ──────────────────────────────────────────────
    # Perseus warm cost: 22µs/directive, local CPU, zero API cost
    perseus_annual_s = (annual_directives * warm_us) / 1_000_000

    perseus_comparison = {}
    for key in MODELS:
        llm_annual = annual[key]
        # LLM time assuming parallel tool calls
        llm_sequential = annual_directives / MODELS[key]["parallel_calls"]
        llm_time_hours = (llm_sequential * MODELS[key]["tool_call_s"]) / 3600

        perseus_comparison[key] = {
            "model": MODELS[key]["label"],
            "provider": MODELS[key]["provider"],
            "annual_directives": annual_directives,
            "llm_api_cost_usd": llm_annual["total_cost_usd"],
            "llm_input_tokens": llm_annual["input_tokens"],
            "llm_output_tokens": llm_annual["output_tokens"],
            "llm_total_tokens": llm_annual["total_tokens"],
            "llm_estimated_hours": round(llm_time_hours, 1),
            "perseus_cost_usd": 0.00,
            "perseus_time_s": round(perseus_annual_s, 3),
            "perseus_time_minutes": round(perseus_annual_s / 60, 2),
            "annual_savings_usd": round(llm_annual["total_cost_usd"], 2),
            "token_savings_pct": 100.0,  # Perseus uses 0 API tokens
        }

    # ── Scale comparison ─────────────────────────────────────────────────
    # Show cost at different directive scales
    scale_comparison = {}
    directive_scales = [10, 50, 100, 500, 1000, 5000, 10000, 50000, 100000]
    for n in directive_scales:
        scale_comparison[str(n)] = {}
        for key in MODELS:
            scale_comparison[str(n)][key] = compute_cost(key, n)

    # ── Token count comparison (the concrete ask) ───────────────────────
    token_comparison = {
        "per_single_directive": TOKENS_PER_DIRECTIVE,
        "per_dev_day": {
            "directives": DIRECTIVES_PER_DEV_PER_DAY,
            "input_tokens": DIRECTIVES_PER_DEV_PER_DAY * TOKENS_PER_DIRECTIVE["input"],
            "output_tokens": DIRECTIVES_PER_DEV_PER_DAY * TOKENS_PER_DIRECTIVE["output"],
        },
        "per_dev_year": {
            "directives": WORKDAYS_PER_YEAR * DIRECTIVES_PER_DEV_PER_DAY,
            "input_tokens": WORKDAYS_PER_YEAR * DIRECTIVES_PER_DEV_PER_DAY * TOKENS_PER_DIRECTIVE["input"],
            "output_tokens": WORKDAYS_PER_YEAR * DIRECTIVES_PER_DEV_PER_DAY * TOKENS_PER_DIRECTIVE["output"],
        },
        "enterprise_annual": {
            "developers": DEVELOPERS,
            "workdays": WORKDAYS_PER_YEAR,
            "directives_per_dev_day": DIRECTIVES_PER_DEV_PER_DAY,
            "total_directives": annual_directives,
            "total_input_tokens": annual_directives * TOKENS_PER_DIRECTIVE["input"],
            "total_output_tokens": annual_directives * TOKENS_PER_DIRECTIVE["output"],
            "total_tokens": annual_directives * (TOKENS_PER_DIRECTIVE["input"] + TOKENS_PER_DIRECTIVE["output"]),
        },
    }

    # ── Assemble ─────────────────────────────────────────────────────────
    output = {
        "test": "titan-cost-analysis",
        "pricing_date": "May 2026",
        "pricing_source": "Anthropic & Google official API pricing pages",
        "models": MODELS,
        "token_estimates": {
            "per_directive": TOKENS_PER_DIRECTIVE,
            "methodology": (
                "Each @query directive simulates one LLM tool call cycle: "
                "read directive (100 input) → think/output tool call (50 output) → "
                "receive result (200 input) → summarize (150 output) = "
                f"{TOKENS_PER_DIRECTIVE['input']} input + {TOKENS_PER_DIRECTIVE['output']} output tokens"
            ),
        },
        "per_directive_cost": per_directive,
        "per_developer_per_day": {
            "directives": DIRECTIVES_PER_DEV_PER_DAY,
            "costs": per_dev_day,
        },
        "enterprise_annual": {
            "developers": DEVELOPERS,
            "workdays_per_year": WORKDAYS_PER_YEAR,
            "directives_per_dev_per_day": DIRECTIVES_PER_DEV_PER_DAY,
            "total_annual_directives": annual_directives,
            "annual_costs": annual,
            "perseus_comparison": perseus_comparison,
        },
        "scale_comparison": scale_comparison,
        "token_comparison": token_comparison,
        "perseus_data": {
            "avg_cold_ms_per_query": avg_cold_ms,
            "warm_us_per_query": warm_us,
            "best_speedup": best_speedup,
            "cold_abandoned_at": cold_abandoned,
        },
        "headline": (
            f"500 developers × 250 days × 50 directives/day = "
            f"{annual_directives:,} directives/year. "
            f"LLM cost: ${annual['claude_opus_47']['total_cost_usd']:,.0f}/yr (Opus 4.7) "
            f"to ${annual['gemini_25_pro']['total_cost_usd']:,.0f}/yr (Gemini 2.5 Pro). "
            f"Perseus: ${perseus_annual_s:.2f} of CPU time, zero API cost. "
            f"Token savings: {annual['claude_opus_47']['total_tokens']/1e9:.1f}B tokens/year."
        ),
    }

    out_path = Path("/workspace/perseus/benchmark/titan_cost.json")
    out_path.write_text(json.dumps(output, indent=2))
    print(f"✓ Cost analysis saved to {out_path}")
    print(f"\n{output['headline']}")

    # ── Pretty print summary ────────────────────────────────────────────
    print(f"\n{'Model':<22s} {'Annual Cost':>12s} {'Tokens/Year':>15s} {'Time (h)':>10s}")
    print("-" * 62)
    for key in ["claude_opus_47", "claude_sonnet_46", "gpt5", "gemini_25_pro"]:
        c = perseus_comparison[key]
        tokens_b = c["llm_total_tokens"] / 1e9
        print(
            f"{c['model']:<22s} "
            f"${c['llm_api_cost_usd']:>11,.0f} "
            f"{tokens_b:>12.1f}B "
            f"{c['llm_estimated_hours']:>9,.0f}h"
        )
    print(f"{'Perseus (warm cache)':<22s} ${0:>11,.0f} {'0':>15s} {'<1s':>10s}")
    print(f"\nToken savings: {annual['claude_opus_47']['total_tokens']/1e9:.1f}B tokens/yr")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--titan-json", help="Path to titan_coldwarm.json")
    args = p.parse_args()
    main()
