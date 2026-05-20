#!/usr/bin/env bash
# Perseus demo script for asciinema recording.
# Run with: asciinema rec --overwrite demo.cast --command "bash scripts/demo.sh"

PERSEUS="python3 /workspace/perseus/perseus.py"
WORKSPACE="/workspace/perseus"

# Helper: type text with a typewriter effect
type_out() {
  local text="$1"
  local delay="${2:-0.04}"
  for (( i=0; i<${#text}; i++ )); do
    printf "%s" "${text:$i:1}"
    sleep "$delay"
  done
}

clear
sleep 0.5

# ── SCENE 1: The Problem ──────────────────────────────────────────────────────
printf "\e[1;33m# The AI cold-start problem\e[0m\n"
sleep 0.4
printf "\e[2m# Every session, your assistant starts from zero:\e[0m\n"
sleep 0.3
printf "\e[2m#   \"What services are running?\"\e[0m\n"
sleep 0.2
printf "\e[2m#   \"Where did we leave off?\"\e[0m\n"
sleep 0.2
printf "\e[2m#   \"Is port 3001 still the API port?\"\e[0m\n"
sleep 0.6
printf "\n"

# ── SCENE 2: Without Perseus ─────────────────────────────────────────────────
printf "\e[1;31m# Without Perseus — AGENTS.md is stale:\e[0m\n"
sleep 0.3
printf "\e[90m\$ cat AGENTS.md | head -6\e[0m\n"
sleep 0.3
printf "Port: 3001 \e[31m(check .env — may have changed)\e[0m\n"
printf "Tests: 47 passing \e[31m(may be stale)\e[0m\n"
printf "Services: \e[31m\"run docker ps to verify\"\e[0m\n"
printf "Last session: \e[31munknown\e[0m\n"
sleep 0.8
printf "\n"

# ── SCENE 3: With Perseus — render ───────────────────────────────────────────
printf "\e[1;32m# With Perseus — context resolved live:\e[0m\n"
sleep 0.3
printf "\e[90m\$ perseus render .perseus/context.md 2>/dev/null | head -30\e[0m\n"
sleep 0.5

$PERSEUS render "$WORKSPACE/.perseus/context.md" 2>/dev/null | head -30

sleep 0.8
printf "\n"

# ── SCENE 4: Checkpoint recovery ─────────────────────────────────────────────
printf "\e[1;32m# Pick up exactly where you left off:\e[0m\n"
sleep 0.3
printf "\e[90m\$ perseus recover\e[0m\n"
sleep 0.4
$PERSEUS recover --workspace "$WORKSPACE" 2>/dev/null
sleep 0.8
printf "\n"

# ── SCENE 5: Auto-injection summary ──────────────────────────────────────────
printf "\e[1;32m# Set it and forget it — cron keeps context ≤5 min fresh:\e[0m\n"
sleep 0.3
printf "\e[90m\$ perseus cron .perseus/context.md --output .hermes.md --every 5\e[0m\n"
sleep 0.4
$PERSEUS cron "$WORKSPACE/.perseus/context.md" --output "$WORKSPACE/.hermes.md" --every 5 2>/dev/null
sleep 0.6
printf "\n"
printf "\e[1;37m# Your AI assistant now starts every session fully oriented.\e[0m\n"
printf "\e[1;37m# Zero pre-flight tax. Every time.\e[0m\n"
sleep 0.5
printf "\n"
printf "\e[36mhttps://github.com/tcconnally/perseus\e[0m\n"
sleep 1.5
