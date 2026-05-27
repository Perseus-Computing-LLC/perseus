#!/usr/bin/env bash
# scripts/demo.sh — run with: asciinema rec demo.cast --command "bash scripts/demo.sh"

clear
sleep 0.5

# SCENE 1: The Problem (with color)
printf "\e[1;31m# WITHOUT Perseus — stale config:\e[0m\n"
sleep 1
printf "\e[90m$ cat .env\e[0m\n"
cat .env
sleep 2
printf "\e[90m$ cat CLAUDE.md\e[0m\n"
cat CLAUDE.md
sleep 3

clear
sleep 0.5

# SCENE 2: With Perseus (with color)
printf "\e[1;32m# WITH Perseus — live context:\e[0m\n"
sleep 1
printf "\e[90m$ perseus render .perseus/context.md --output CLAUDE.md\e[0m\n"
perseus render .perseus/context.md --output CLAUDE.md
sleep 2
printf "\e[90m$ cat CLAUDE.md\e[0m\n"
cat CLAUDE.md
sleep 3

# CLOSE
printf "\e[36mhttps://github.com/tcconnally/perseus\e[0m\n"
sleep 1.5