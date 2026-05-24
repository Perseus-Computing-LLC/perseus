#!/usr/bin/env bash
# Perseus demo — cold-start eliminated
# Record: asciinema rec demo.cast --command "bash scripts/demo.sh"
# Convert: agg demo.cast demo.gif --font-size 14 --cols 80 --rows 28

clear
printf "\e[1;36m╔════════════════════════════════════════════╗\e[0m\n"
printf "\e[1;36m║   PERSEUS — Live Context for AI Assistants ║\e[0m\n"
printf "\e[1;36m╚════════════════════════════════════════════╝\e[0m\n"
sleep 2

# ── SCENE 1: The Problem ──
clear
printf "\e[1;31m# WITHOUT PERSEUS — Every session starts cold\e[0m\n\n"
printf "\e[90m$ \e[0m\e[1;33mclaude\e[0m\n"
sleep 0.8
printf "\e[90mClaude:\e[0m  Let me check what's running...\n"
printf "       \e[90m[1/12]\e[0m docker ps...              \e[33m1.2s\e[0m\n"
sleep 0.5
printf "       \e[90m[2/12]\e[0m git log...                \e[33m0.8s\e[0m\n"
sleep 0.5
printf "       \e[90m[3/12]\e[0m checking CI status...     \e[33m2.1s\e[0m\n"
sleep 0.5
printf "       \e[90m...\e[0m\n"
sleep 0.5
printf "       \e[90m[12/12]\e[0m reading config...        \e[33m1.5s\e[0m\n"
sleep 0.5
printf "\n\e[1;31m36 discovery calls · 3–5 minutes · every single session\e[0m\n"
sleep 2.5

# ── SCENE 2: Installing Perseus ──
clear
printf "\e[1;32m# WITH PERSEUS — Install once, never cold-start again\e[0m\n\n"
printf "\e[90m$ \e[0mpip install perseus-ctx\n"
sleep 0.7
printf "Successfully installed perseus-ctx-\e[1;32m1.0.2\e[0m\n\n"
sleep 1
printf "\e[90m$ \e[0mperseus init . --output CLAUDE.md\n"
sleep 0.7
printf "✓ Scaffolded \e[1;36m.perseus/context.md\e[0m\n"
sleep 1.5

# ── SCENE 3: Cold render (first time) ──
clear
printf "\e[1;34m# FIRST RENDER — Cold (all probes run live)\e[0m\n\n"
printf "\e[90m$ \e[0mperseus render .perseus/context.md --output CLAUDE.md\n"
sleep 0.7
printf "\e[90m  Resolving:\e[0m\n"
printf "  \e[90m@query\e[0m  docker ps --format '{{.Names}}'    → \e[32m12 containers\e[0m\n"
sleep 0.5
printf "  \e[90m@query\e[0m  git log --oneline -5              → \e[32m5 commits\e[0m\n"
sleep 0.5
printf "  \e[90m@query\e[0m  df -h /                            → \e[32m55%% used\e[0m\n"
sleep 0.5
printf "  \e[90m@query\e[0m  python -m pytest --collect-only    → \e[32m540 tests\e[0m\n"
sleep 0.5
printf "  \e[90m@services\e[0m                             → \e[32m8 healthy\e[0m\n"
sleep 0.5
printf "  \e[90m@skills\e[0m                               → \e[32m82 available\e[0m\n"
sleep 0.7
printf "\n\e[1;36m→ CLAUDE.md · 298 lines · 20KB · 1.7s\e[0m\n"
sleep 2

# ── SCENE 4: Warm render (cache hit) ──
clear
printf "\e[1;35m# SECOND RENDER — Warm (@cache ttl=300)\e[0m\n\n"
printf "\e[90m$ \e[0mperseus render .perseus/context.md --output CLAUDE.md\n"
sleep 0.5
printf "  \e[90m@query\e[0m  docker ps              → \e[90m[cached]\e[0m\n"
sleep 0.25
printf "  \e[90m@query\e[0m  git log                → \e[90m[cached]\e[0m\n"
sleep 0.25
printf "  \e[90m@query\e[0m  df -h                  → \e[90m[cached]\e[0m\n"
sleep 0.25
printf "  \e[90m@query\e[0m  pytest                 → \e[90m[cached]\e[0m\n"
sleep 0.25
printf "  \e[90m@services\e[0m                → \e[90m[cached]\e[0m\n"
sleep 0.25
printf "  \e[90m@skills\e[0m                  → \e[90m[cached]\e[0m\n"
sleep 0.5
printf "\n\e[1;36m→ CLAUDE.md · 298 lines · 20KB · \e[1;32m0.28s ⚡\e[0m\n"
sleep 1

# ── SCENE 5: The scaling advantage ──
clear
printf "\e[1;33m# SCALING — Warm time stays flat no matter how many queries\e[0m\n\n"

# Table with properly aligned columns — each column is a fixed-width field.
# Widths: @queries=10, Cold(seq)=12, Warm(cache)=13, Speedup=10
# Using printf format strings to guarantee alignment.
# ANSI codes are applied per-line, not per-cell, so they don't shift alignment.

printf "┌──────────┬────────────┬─────────────┬──────────┐\n"
printf "│ \e[1m@queries\e[0m │ \e[1;34mCold (seq)\e[0m  │ \e[1;32mWarm (cache)\e[0m │ \e[1;33mSpeedup\e[0m  │\n"
printf "├──────────┼────────────┼─────────────┼──────────┤\n"
printf "│    10    │   0.46s    │    0.34s    │   1.4×   │\n"
sleep 0.6
printf "│   100    │   1.62s    │    0.33s    │   4.9×   │\n"
sleep 0.6
printf "│   500    │   6.72s    │    0.34s    │  19.8×   │\n"
sleep 0.6
printf "│  2000    │  27.00s    │    0.46s    │  58.7×   │\n"
sleep 0.6
printf "│ 10000    │  13.12s    │    0.52s    │  25.2×   │\n"
sleep 0.6
printf "└──────────┴────────────┴─────────────┴──────────┘\n"
sleep 0.7
printf "\n\e[1;36mCache makes render time \e[1;33mCONSTANT\e[0m\e[1;36m at any scale.\e[0m\n"
sleep 2

# ── SCENE 6: Features ──
clear
printf "\e[1;36m# SHIPS WITH\e[0m\n\n"
printf "  \e[32m✓\e[0m 4 directives: @query @services @skills @waypoint\n"
sleep 0.3
printf "  \e[32m✓\e[0m @cache ttl=N — \e[1;33m40×\e[0m warm speedup\n"
sleep 0.3
printf "  \e[32m✓\e[0m max_query_bytes — caps runaway stdout at 256KB\n"
sleep 0.3
printf "  \e[32m✓\e[0m parallel_queries / parallel_services — opt-in concurrency\n"
sleep 0.3
printf "  \e[32m✓\e[0m timeout=N — per-directive timeout control\n"
sleep 0.3
printf "  \e[32m✓\e[0m Windows, macOS, Linux\n"
sleep 0.3
printf "  \e[32m✓\e[0m VS Code extension · Claude Code hook · GitHub Action\n"
sleep 0.3
printf "  \e[32m✓\e[0m Works with Claude, Cursor, Codex, Hermes, Rovo Dev\n"
sleep 1.5

# ── CLOSE ──
clear
printf "\n\e[1;36m╔════════════════════════════════════════════╗\e[0m\n"
printf "\e[1;36m║  \e[1;37mPERSEUS\e[0m\e[1;36m — Cold-Start Eliminated          ║\e[0m\n"
printf "\e[1;36m╠════════════════════════════════════════════╣\e[0m\n"
printf "\e[1;36m║  \e[0mpip install perseus-ctx                  \e[1;36m║\e[0m\n"
printf "\e[1;36m║  \e[0mgithub.com/tcconnally/perseus           \e[1;36m║\e[0m\n"
printf "\e[1;36m╚════════════════════════════════════════════╝\e[0m\n\n"
printf "\e[90mFacts before the first prompt. Zero discovery calls.\e[0m\n"
sleep 3
