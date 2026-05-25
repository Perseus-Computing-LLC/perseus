#!/usr/bin/env python3
"""
CHAOS.md — EXTREME ENTERPRISE WEEK: Perseus Stress Benchmark
=============================================================

THIS IS A SYNTHETIC STRESS BENCHMARK. It simulates 500 developers across 10
independent teams over a 5-day workweek (35 total events) with concurrent
bursts, random cache invalidation, and multi-tier LLM cost comparison.

The burst densities and team counts are designed to push Perseus to its
limits — they are NOT a realistic simulation of any actual team's workflow.

GOAL: Find where Perseus breaks. Every failure is data.
      Measure cold-warm cache lifecycle across a full workweek.

Scale: 500 developers, 10 teams x 50 devs, ~270 directives/team
      35 events = 30 scheduled + 5 chaos
      6 events/day (Mon-Fri), 1 chaos/day

Comparison tiers:
  - Claude Opus 4.5:   $15/$75 per 1M tokens, 2.5s/tool, 3x parallel
  - GPT-5:             $3.75/$15 per 1M tokens, 1.8s/tool, 5x parallel
  - Gemini 3 Pro:      $1.25/$5 per 1M tokens, 1.2s/tool, 8x parallel

Usage:
  python3 benchmark/extreme_week.py
  python3 benchmark/extreme_week.py --team web --day monday
  python3 benchmark/extreme_week.py --day friday
"""
import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# -- Paths ------------------------------------------------------------------
PERSEUS = Path("/workspace/perseus/perseus.py")
PY = sys.executable
BASE = Path("/tmp/perseus-extreme-week")
OUT_DIR = Path("/workspace/perseus/benchmark")
INC_DIR = OUT_DIR / "extreme_week"

# -- LLM Pricing Tiers -------------------------------------------------------
LLM_TIERS = {
    "claude_opus": {
        "label": "Claude Opus 4.5",
        "input_per_1M": 15.0,
        "output_per_1M": 75.0,
        "tool_call_s": 2.5,
        "parallel": 3,
    },
    "gpt5": {
        "label": "GPT-5",
        "input_per_1M": 3.75,
        "output_per_1M": 15.0,
        "tool_call_s": 1.8,
        "parallel": 5,
    },
    "gemini3_pro": {
        "label": "Gemini 3 Pro",
        "input_per_1M": 1.25,
        "output_per_1M": 5.0,
        "tool_call_s": 1.2,
        "parallel": 8,
    },
}

TOKENS_PER_DIRECTIVE_IN = 100
TOKENS_PER_DIRECTIVE_OUT = 200

# ============================================================================
# Team Directive Profiles
# ============================================================================
# All inline Python removed -- every @query is a simple shell command.
# Complex parsing goes through /dev/null fallback patterns.

def _d(*directives):
    """Return a copy of the directive list."""
    return list(directives)


# -- Platform (monorepo, 30 directives) --------------------------------------
def _mk_platform():
    return _d(
        '@env NODE_ENV fallback="production"',
        '@env MONOREPO_ROOT fallback="/workspace"',
        '@env CI fallback="true"',
        '@read .env key="API_GATEWAY_URL" fallback="http://gateway:3000"',
        '@read nx.json',
        '@read turbo.json',
        '@query "git log --oneline -10"',
        '@query "git branch --show-current"',
        '@query "git diff --stat HEAD~3"',
        '@query "git tag --sort=-creatordate | head -5"',
        '@query "npx nx show projects 2>/dev/null | head -20 || echo no-nx"',
        '@query "npx nx show projects 2>/dev/null | wc -l"',
        '@query "du -sh node_modules 2>/dev/null || echo no-node_modules"',
        '@query "npm ls --depth=0 2>/dev/null || echo no-npm"',
        '@query "docker ps --format table 2>/dev/null | head -15 || echo no-docker"',
        '@query "docker compose config --services 2>/dev/null || echo no-compose"',
        '@tree packages depth=3',
        '@tree libs depth=3',
        '@list packages type="files" limit=20 sort="mtime"',
        '@query "npx eslint packages/ 2>/dev/null | wc -l || echo lint-n-a"',
        '@query "npx tsc --noEmit --pretty false 2>/dev/null | tail -5 || echo no-tsc"',
        "@agora status=open limit=10",
        "@health",
        "@drift",
        "@skills limit=15",
        "@inbox unread=true limit=10",
        "@query \"npx nx affected:lint --base=HEAD~1 2>/dev/null | head -5 || echo no-affected\"",
        "@query \"npx nx affected:build --base=HEAD~1 2>/dev/null | head -5 || echo no-affected\"",
        "@waypoint ttl=86400",
        "@session count=5",
    )


# -- Web (Next.js, 28 directives) -------------------------------------------
def _mk_web():
    return _d(
        '@env NODE_ENV fallback="development"',
        '@env NEXT_PUBLIC_API_URL fallback="http://localhost:3001"',
        '@read .env key="VERCEL_TOKEN" fallback="unset"',
        '@read package.json path="dependencies"',
        '@read package.json path="devDependencies"',
        '@read next.config.js',
        '@query "git log --oneline -8"',
        '@query "git branch --show-current"',
        '@query "git status --short | head -20"',
        '@query "npx next build --dry-run 2>/dev/null || echo no-next"',
        '@query "du -sh .next 2>/dev/null || echo no-next-build"',
        '@query "npx next lint 2>/dev/null | tail -5 || echo no-lint"',
        '@tree app depth=3',
        '@tree components depth=3',
        '@tree pages depth=2',
        '@list app type="files" limit=20 sort="mtime"',
        '@query "curl -s -o /dev/null -w %{http_code} http://localhost:3000 2>/dev/null || echo unreachable"',
        '@query "npx next telemetry status 2>/dev/null || echo no-telemetry"',
        "@agora status=open limit=8",
        "@health",
        "@drift",
        "@skills limit=15",
        "@inbox unread=true limit=8",
        '@query "npx webpack-bundle-analyzer --help 2>/dev/null | head -3 || echo no-wba"',
        '@query "npx next info 2>/dev/null | head -5 || echo no-next-info"',
        '@query "npx next dev --help 2>/dev/null | head -3 || echo no-next-dev"',
        "@waypoint ttl=86400",
        "@session count=5",
    )


# -- Mobile (Flutter + React Native, 27 directives) --------------------------
def _mk_mobile():
    return _d(
        '@env ANDROID_HOME fallback="/opt/android"',
        '@env FLUTTER_ROOT fallback="/opt/flutter"',
        '@read .env key="API_URL" fallback="http://localhost:3001"',
        '@read pubspec.yaml',
        '@read package.json',
        '@query "git log --oneline -8"',
        '@query "git branch --show-current"',
        '@query "flutter --version 2>/dev/null | head -1 || echo no-flutter"',
        '@query "flutter analyze 2>/dev/null | tail -5 || echo no-flutter"',
        '@query "flutter test --reporter compact 2>/dev/null | tail -3 || echo no-flutter"',
        '@query "flutter build apk --debug --target-platform android-arm64 2>/dev/null | tail -3 || echo no-flutter-build"',
        '@query "npx react-native --version 2>/dev/null || echo no-rn"',
        '@query "npx react-native info 2>/dev/null | head -10 || echo no-rn"',
        '@query "xcodebuild -version 2>/dev/null | head -1 || echo no-xcode"',
        '@query "java -version 2>&1 | head -1 || echo no-java"',
        '@tree lib depth=3',
        '@tree src depth=3',
        '@tree test depth=2',
        '@list lib type="files" limit=20 sort="mtime"',
        "@agora status=open limit=5",
        "@health",
        "@drift",
        "@skills limit=10",
        "@inbox unread=true limit=5",
        '@query "find ios/ -name Podfile -o -name *.xcodeproj 2>/dev/null | wc -l"',
        "@waypoint ttl=86400",
        "@session count=5",
    )


# -- Data (Python/Spark, 30 directives) -------------------------------------
def _mk_data():
    return _d(
        '@env PYTHONPATH fallback="src"',
        '@env SPARK_HOME fallback="/opt/spark"',
        '@read .env key="DATABASE_URL" fallback="postgres://localhost:5432/db"',
        '@read .env key="REDIS_URL" fallback="redis://localhost:6379"',
        '@read pyproject.toml path="project.dependencies"',
        '@read requirements.txt',
        '@query "git log --oneline -10"',
        '@query "git branch --show-current"',
        '@query "git diff --stat HEAD~3"',
        '@query "python3 -c import pandas 2>/dev/null && echo pandas-ok || echo no-pandas"',
        '@query "python3 -c import pyspark 2>/dev/null && echo spark-ok || echo no-spark"',
        '@query "python3 -c import numpy 2>/dev/null && echo numpy-ok || echo no-numpy"',
        '@query "find data/ -name *.parquet -o -name *.csv -o -name *.orc 2>/dev/null | wc -l"',
        '@query "du -sh data/ 2>/dev/null | cut -f1 || echo no-data-dir"',
        '@query "docker exec postgres psql -U postgres -c \"SELECT count(*) FROM information_schema.tables\" 2>/dev/null || echo no-postgres"',
        '@query "docker exec redis redis-cli DBSIZE 2>/dev/null || echo no-redis"',
        '@query "python -m pytest tests/ --collect-only -q 2>/dev/null | tail -1 || echo no-pytest"',
        '@query "python -m ruff check src/ --statistics 2>/dev/null || echo no-ruff"',
        '@tree src depth=3',
        '@tree notebooks depth=2',
        '@list src type="files" limit=25 sort="mtime"',
        '@query "find data/ -maxdepth 1 -type d 2>/dev/null | tail -5 || echo no-data"',
        "@agora status=open limit=8",
        "@health",
        "@drift",
        "@skills limit=15",
        "@inbox unread=true limit=8",
        '@query "find sql/ -name *.sql -mtime -7 2>/dev/null | wc -l"',
        "@waypoint ttl=86400",
        "@session count=5",
    )


# -- ML (Python/ML, 32 directives) ------------------------------------------
def _mk_ml():
    return _d(
        '@env PYTHONPATH fallback="src"',
        '@env CUDA_VISIBLE_DEVICES fallback="0"',
        '@env MLFLOW_TRACKING_URI fallback="http://localhost:5000"',
        '@read .env key="WANDB_API_KEY" fallback="unset"',
        '@read pyproject.toml path="project.dependencies"',
        '@read requirements.txt',
        '@query "git log --oneline -10"',
        '@query "git branch --show-current"',
        '@query "git diff --stat HEAD~3"',
        '@query "nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv 2>/dev/null || echo no-gpu"',
        '@query "python3 -c import torch 2>/dev/null && echo torch-ok || echo no-torch"',
        '@query "find models/ -name *.safetensors -o -name *.bin -o -name *.gguf 2>/dev/null | wc -l"',
        '@query "du -sh models/ 2>/dev/null | cut -f1 || echo no-models"',
        '@query "find checkpoints/ -type d 2>/dev/null | wc -l"',
        '@query "find datasets/ -type f 2>/dev/null | wc -l"',
        '@query "du -sh datasets/ 2>/dev/null | cut -f1 || echo no-datasets"',
        '@query "pip list 2>/dev/null | grep -E \"torch|transformers|datasets|accelerate\" | head -10 || echo no-pip"',
        '@query "python -m pytest tests/ --collect-only -q 2>/dev/null | tail -1 || echo no-pytest"',
        '@tree src depth=3',
        '@tree configs depth=2',
        '@tree experiments depth=2',
        '@list src type="files" limit=25 sort="mtime"',
        '@query "find mlruns/ -maxdepth 1 -type d 2>/dev/null | wc -l"',
        "@agora status=open limit=8",
        "@health",
        "@drift",
        "@skills limit=20",
        "@inbox unread=true limit=8",
        '@query "find configs/ -name *.yaml -o -name *.json 2>/dev/null | head -10"',
        '@query "find experiments/ -name results.json -mtime -3 2>/dev/null | wc -l"',
        "@waypoint ttl=86400",
        "@session count=5",
    )


# -- DevOps (K8s multi-cluster, 35 directives) HEAVIEST ---------------------
def _mk_devops():
    return _d(
        '@env KUBECONFIG fallback="~/.kube/config"',
        '@env AWS_PROFILE fallback="default"',
        '@env TERRAFORM_VERSION fallback="1.5"',
        '@env HELM_HOME fallback="~/.helm"',
        '@read terraform.tfvars',
        '@read .env',
        '@query "git log --oneline -15"',
        '@query "git diff --stat HEAD~5"',
        '@query "git tag --sort=-creatordate | head -5"',
        '@query "kubectl get nodes -o wide 2>/dev/null | head -20 || echo no-k8s"',
        '@query "kubectl get pods --all-namespaces 2>/dev/null | head -20 || echo no-k8s"',
        '@query "kubectl top nodes 2>/dev/null | head -10 || echo no-metrics"',
        '@query "kubectl top pods --all-namespaces 2>/dev/null | head -10 || echo no-metrics"',
        '@query "kubectl get events --all-namespaces 2>/dev/null | tail -15 || echo no-k8s"',
        '@query "helm list --all-namespaces 2>/dev/null || echo no-helm"',
        '@query "helm history production-api -n production 2>/dev/null | head -10 || echo no-helm"',
        '@query "terraform plan -no-color 2>/dev/null | tail -10 || echo no-terraform"',
        '@query "terraform state list 2>/dev/null | wc -l || echo no-terraform"',
        '@query "docker ps --format table 2>/dev/null | head -25 || echo no-docker"',
        '@query "docker stats --no-stream 2>/dev/null | head -15 || echo no-docker"',
        '@query "docker system df 2>/dev/null | head -20 || echo no-docker"',
        '@query "df -h / /tmp /var"',
        '@query "free -h"',
        '@query "cat /proc/loadavg"',
        '@query "uname -a"',
        '@query "ss -tlnp 2>/dev/null | head -20 || echo no-ss"',
        '@query "curl -s -o /dev/null -w %{http_code} http://localhost:3001/health 2>/dev/null || echo unreachable"',
        '@query "docker exec prometheus promtool query instant http://localhost:9090 up 2>/dev/null | head -10 || echo no-prometheus"',
        "@agora status=open limit=15",
        "@health",
        "@drift",
        "@skills limit=25",
        "@inbox unread=true limit=15",
        "@waypoint ttl=86400",
        "@session count=5",
    )


# -- Security (SAST/DAST, 28 directives) ------------------------------------
def _mk_security():
    return _d(
        '@env SECURITY_SCAN_API_KEY fallback="unset"',
        '@env TRIVY_CACHE_DIR fallback="/tmp/trivy-cache"',
        '@read .env key="SNYK_TOKEN" fallback="unset"',
        '@read .env key="SEMGREP_RULES" fallback="p/default"',
        '@query "git log --oneline -8"',
        '@query "git branch --show-current"',
        '@query "git secrets --scan-history 2>/dev/null | head -5 || echo no-git-secrets"',
        '@query "semgrep --config auto --quiet 2>/dev/null | wc -l || echo no-semgrep"',
        '@query "trivy fs --severity HIGH,CRITICAL --quiet . 2>/dev/null | tail -10 || echo no-trivy"',
        '@query "gitleaks detect --source . --no-git 2>/dev/null | tail -10 || echo no-gitleaks"',
        '@query "trufflehog filesystem . --no-update 2>/dev/null | wc -l || echo no-trufflehog"',
        '@query "grype db status 2>/dev/null || echo no-grype"',
        '@query "find vuln-reports/ -name *.json -mtime -1 2>/dev/null | wc -l"',
        '@query "syft packages . 2>/dev/null | wc -l || echo no-syft"',
        '@query "docker scout quickview 2>/dev/null | head -15 || echo no-scout"',
        '@query "docker images --format table 2>/dev/null | head -15 || echo no-docker"',
        '@tree policies depth=2',
        '@tree rules depth=2',
        '@list vuln-reports type="files" limit=20 sort="mtime"',
        "@agora status=open limit=8",
        "@health",
        "@drift",
        "@skills limit=15",
        "@inbox unread=true limit=8",
        '@query "find policies/ -name *.rego -o -name *.opa 2>/dev/null | wc -l"',
        '@query "dependencytrack-cli --version 2>/dev/null || echo no-dtrack"',
        "@waypoint ttl=86400",
        "@session count=5",
    )


# -- QA (test infra, 26 directives) -----------------------------------------
def _mk_qa():
    return _d(
        '@env TEST_ENV fallback="staging"',
        '@env CI fallback="true"',
        '@read .env key="TEST_API_URL" fallback="http://localhost:3001"',
        '@read cypress.config.js',
        '@read playwright.config.ts',
        '@query "git log --oneline -8"',
        '@query "git branch --show-current"',
        '@query "python -m pytest tests/ --collect-only -q 2>/dev/null | tail -1 || echo no-pytest"',
        '@query "python -m pytest tests/ --tb=no --co -q 2>/dev/null | wc -l || echo no-pytest"',
        '@query "npx playwright test --list 2>/dev/null | tail -5 || echo no-playwright"',
        '@query "npx cypress run --headless 2>/dev/null | tail -5 || echo no-cypress"',
        '@query "python -m coverage report 2>/dev/null | tail -3 || echo no-coverage"',
        '@query "python -m coverage report --show-missing 2>/dev/null | wc -l || echo no-coverage"',
        '@query "gh run list --limit 10 2>/dev/null || echo no-gh"',
        '@query "docker ps 2>/dev/null | grep selenium || echo no-selenium-grid"',
        '@tree tests depth=3',
        '@tree e2e depth=2',
        '@list tests type="files" limit=20 sort="mtime"',
        "@agora status=open limit=8",
        "@health",
        "@drift",
        "@skills limit=12",
        "@inbox unread=true limit=8",
        '@query "npx playwright install --dry-run 2>/dev/null | head -3 || echo no-playwright"',
        "@waypoint ttl=86400",
        "@session count=5",
    )


# -- DevTools (build systems, 25 directives) --------------------------------
def _mk_devtools():
    return _d(
        '@env CI fallback="true"',
        '@env BAZEL_HOME fallback="/opt/bazel"',
        '@read .env key="NPM_REGISTRY" fallback="https://registry.npmjs.org"',
        '@read Makefile',
        '@read Justfile',
        '@query "git log --oneline -8"',
        '@query "git branch --show-current"',
        '@query "bazel info workspace 2>/dev/null || echo no-bazel"',
        '@query "bazel query //... 2>/dev/null | wc -l || echo no-bazel"',
        '@query "make -n 2>/dev/null | head -10 || echo no-make"',
        '@query "npx lerna ls 2>/dev/null | wc -l || echo no-lerna"',
        '@query "npm config get registry 2>/dev/null || echo no-npm"',
        '@query "du -sh .npm 2>/dev/null | cut -f1 || echo no-npm-cache"',
        '@tree tools depth=3',
        '@tree scripts depth=2',
        '@tree packages depth=2',
        '@list tools type="files" limit=20 sort="mtime"',
        "@agora status=open limit=5",
        "@health",
        "@drift",
        "@skills limit=12",
        "@inbox unread=true limit=5",
        '@query "bazel clean --expunge --async 2>/dev/null | head -3 || echo no-bazel-clean"',
        "@waypoint ttl=86400",
        "@session count=5",
    )


# -- Docs (documentation, 22 directives) ------------------------------------
def _mk_docs():
    return _d(
        '@env NODE_ENV fallback="development"',
        '@read .env key="DOCS_BASE_URL" fallback="https://docs.acmecorp.com"',
        '@read docusaurus.config.js',
        '@read sidebars.js',
        '@query "git log --oneline -8"',
        '@query "git branch --show-current"',
        '@query "npx docusaurus build --out-dir /tmp/docs-build 2>/dev/null | tail -5 || echo no-docusaurus"',
        '@query "du -sh build/ 2>/dev/null | cut -f1 || echo no-build"',
        '@query "find docs/ -name *.md -o -name *.mdx 2>/dev/null | wc -l"',
        '@query "npx docusaurus-mdx-checker 2>/dev/null | tail -5 || echo no-checker"',
        '@tree docs depth=3',
        '@tree src depth=2',
        '@list docs type="files" limit=25 sort="mtime"',
        "@agora status=open limit=5",
        "@health",
        "@drift",
        "@skills limit=10",
        "@inbox unread=true limit=5",
        '@query "npx docusaurus swizzle --help 2>/dev/null | head -3 || echo no-swizzle"',
        '@query "npx prettier --check docs/ 2>/dev/null | tail -3 || echo no-prettier"',
        "@waypoint ttl=86400",
        "@session count=5",
    )


TEAM_PROFILES = {
    "platform": {"label": "Platform",    "devs": 50, "fn": _mk_platform},
    "web":      {"label": "Web",         "devs": 50, "fn": _mk_web},
    "mobile":   {"label": "Mobile",      "devs": 50, "fn": _mk_mobile},
    "data":     {"label": "Data",        "devs": 50, "fn": _mk_data},
    "ml":       {"label": "ML",          "devs": 50, "fn": _mk_ml},
    "devops":   {"label": "DevOps/SRE",  "devs": 50, "fn": _mk_devops},
    "security": {"label": "Security",    "devs": 50, "fn": _mk_security},
    "qa":       {"label": "QA",          "devs": 50, "fn": _mk_qa},
    "devtools": {"label": "DevTools",    "devs": 50, "fn": _mk_devtools},
    "docs":     {"label": "Docs",        "devs": 50, "fn": _mk_docs},
}

# -- Event Schedule ----------------------------------------------------------
DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday"]

DAILY_EVENTS = [
    {"name": "Morning Context Pull",    "time_slot": "08:00", "pattern": "staggered"},
    {"name": "Pre-Standup Burst",       "time_slot": "10:00", "pattern": "burst"},
    {"name": "Midday Code Review Wave", "time_slot": "12:00", "pattern": "staggered"},
    {"name": "Post-Lunch Refresh",      "time_slot": "14:00", "pattern": "burst"},
    {"name": "Pre-Deploy Context Check","time_slot": "16:00", "pattern": "burst"},
    {"name": "End-of-Day Wrap",         "time_slot": "18:00", "pattern": "staggered"},
]


# ============================================================================
# Benchmark Logic
# ============================================================================

def estimate_llm_discovery(n_directives, tier):
    """Estimate LLM tool-calling time and cost for N directives."""
    effective_n = n_directives * 0.85
    batches = max(1, effective_n / tier["parallel"])
    tool_time = batches * tier["tool_call_s"]
    orientation_turns = 2
    total_s = tool_time + (orientation_turns * tier["tool_call_s"])
    input_tokens = effective_n * TOKENS_PER_DIRECTIVE_IN
    output_tokens = effective_n * TOKENS_PER_DIRECTIVE_OUT
    cost = (input_tokens / 1_000_000 * tier["input_per_1M"]) + \
           (output_tokens / 1_000_000 * tier["output_per_1M"])
    return {
        "seconds": round(total_s, 1),
        "tool_calls": round(effective_n),
        "turns": round(batches) + orientation_turns,
        "input_tokens": round(input_tokens),
        "output_tokens": round(output_tokens),
        "cost_usd": round(cost, 4),
    }


def setup_team_workspace(ws_dir, team):
    """Create a realistic workspace for one team member. Returns directive count."""
    profile = TEAM_PROFILES[team]
    ws_dir.mkdir(parents=True, exist_ok=True)
    pd = ws_dir / ".perseus"
    pd.mkdir(exist_ok=True)

    import yaml
    cfg = {
        "render": {
            "allow_query_shell": True,
            "allow_services_command": False,
            "allow_remote_services_health": False,
            "shell": "/bin/bash",
            "cache_dir": str(pd / "cache"),
            "services_timeout_s": 3,
            "query_timeout_s": 30,
            "max_query_bytes": 262144,
        }
    }
    (pd / "config.yaml").write_text(yaml.dump(cfg))

    (ws_dir / ".env").write_text(
        "API_PORT=3001\nNODE_ENV=development\n"
        "DB_URL=postgres://localhost:5432/db\n"
        "REDIS_URL=redis://localhost:6379\n"
    )
    (ws_dir / "package.json").write_text(
        '{"name":"project","dependencies":{"react":"^19","next":"^15"},'
        '"devDependencies":{"typescript":"^5","vite":"^6"}}'
    )
    (ws_dir / "pyproject.toml").write_text(
        '[project]\ndependencies=["fastapi","sqlalchemy","redis","pandas","numpy"]\n'
    )
    (ws_dir / "docker-compose.yaml").write_text(
        "services:\n  postgres:\n    image: postgres:16\n  redis:\n    image: redis:7\n  api:\n    build: .\n"
    )
    (ws_dir / "requirements.txt").write_text("pandas>=2.0\nnumpy>=1.24\nscikit-learn>=1.3\n")
    (ws_dir / "pubspec.yaml").write_text(
        "name: mobile_app\ndependencies:\n  flutter:\n    sdk: flutter\n  http: ^1.0\n"
    )
    (ws_dir / "terraform.tfvars").write_text(
        'region = "us-east-1"\ncluster_name = "prod"\nnode_count = 3\n'
    )

    # Config files
    for fname in ["nx.json", "turbo.json", "next.config.js", "cypress.config.js",
                  "playwright.config.ts", "docusaurus.config.js", "sidebars.js",
                  "Makefile", "Justfile"]:
        (ws_dir / fname).write_text("// placeholder\n" if fname.endswith((".js", ".ts"))
                                     else "{}\n" if fname.endswith(".json")
                                     else "# placeholder\n" if fname in ("Makefile", "Justfile")
                                     else "module.exports = {};\n")

    # Directory trees for @tree directives
    for d in ["src", "tests", "lib", "components", "app", "pages",
              "packages", "libs", "data", "datasets", "models",
              "checkpoints", "experiments", "configs", "notebooks",
              "policies", "rules", "vuln-reports", "tools", "scripts",
              "docs"]:
        dd = ws_dir / d
        dd.mkdir(exist_ok=True)
        # 2nd level
        for sub in ["api", "utils", "core", "services", "models", "handlers"]:
            sd = dd / sub
            sd.mkdir(exist_ok=True)
            (sd / "__init__.py").write_text("")
            (sd / "module.py").write_text("# placeholder\n")
        # 3rd level for deep trees
        if d in ("packages", "libs", "src", "tools"):
            for sub in ["api", "utils", "core"]:
                sd2 = dd / sub / "sub"
                sd2.mkdir(exist_ok=True)
                (sd2 / "__init__.py").write_text("")

    for f in ["test_api.py", "test_models.py", "test_utils.py"]:
        (ws_dir / "tests" / f).write_text("def test_placeholder():\n    assert True\n")

    directives = profile["fn"]()
    return len(directives)


def build_context_md(team):
    """Build context.md with @cache ttl=300 on @query directives."""
    profile = TEAM_PROFILES[team]
    directives = profile["fn"]()

    # Add cache modifier
    directives = [
        d + " @cache ttl=300" if d.strip().startswith("@query") else d
        for d in directives
    ]

    lines = ["@perseus", f"## {profile['label']} — Context Resolution"]
    lines.extend(directives)
    content = "\n".join(lines) + "\n"

    n = sum(1 for line in content.splitlines()
            if line.strip().startswith("@")
            and not line.strip().startswith("@perseus"))
    return content, n


def render_perseus(workspace, context_md):
    """Render context through Perseus. Returns (elapsed_s, success, error, cache_hit)."""
    ctx_path = workspace / ".perseus" / "context.md"
    out_path = workspace / ".hm.md"
    ctx_path.write_text(context_md)

    env = {**os.environ, "PERSEUS_HOME": str(workspace / ".ph")}

    t0 = time.perf_counter()
    r = subprocess.run(
        [PY, str(PERSEUS), "render", str(ctx_path), "--output", str(out_path)],
        capture_output=True, timeout=120, env=env,
    )
    elapsed = time.perf_counter() - t0

    success = r.returncode == 0
    error = r.stderr.decode(errors="replace")[-500:] if not success else ""

    num_directives = sum(1 for line in context_md.splitlines()
                         if line.strip().startswith("@")
                         and not line.strip().startswith("@perseus"))
    cache_hit = success and elapsed < 1.5 and num_directives > 10

    return elapsed, success, error, cache_hit


def bust_random_caches(dev_workspaces, pct=0.05):
    """Randomly clear cache dirs for pct% of developers."""
    keys = list(dev_workspaces.keys())
    n_bust = max(1, int(len(keys) * pct))
    n_bust = min(n_bust, len(keys))  # Don't sample more than available
    bust_keys = random.sample(keys, n_bust)
    busted = 0
    for key in bust_keys:
        cache_dir = dev_workspaces[key] / ".perseus" / "cache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            busted += 1
    return busted


def clear_all_caches(dev_workspaces):
    """Clear all cache dirs -- simulate weekend TTL decay."""
    for ws in dev_workspaces.values():
        cache_dir = ws / ".perseus" / "cache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
            cache_dir.mkdir(parents=True, exist_ok=True)


def compute_summary(results, n_tasks):
    """Compute perseus_summary from individual render results."""
    successes = [r for r in results if r["success"]]
    elapsed_times = [r["elapsed_s"] for r in successes]
    cache_hits = [r for r in results if r.get("cache_hit", False)]

    return {
        "renders": len(results),
        "successful": len(successes),
        "failed": len(results) - len(successes),
        "render_times": {
            "min": round(min(elapsed_times), 3) if elapsed_times else 0,
            "max": round(max(elapsed_times), 3) if elapsed_times else 0,
            "median": round(statistics.median(elapsed_times), 3) if elapsed_times else 0,
            "p95": round(sorted(elapsed_times)[int(len(elapsed_times) * 0.95)], 3)
                   if len(elapsed_times) >= 20 else (round(max(elapsed_times), 3) if elapsed_times else 0),
            "mean": round(statistics.mean(elapsed_times), 3) if elapsed_times else 0,
        },
        "total_render_s": round(sum(elapsed_times), 3),
        "cache_hits": len(cache_hits),
        "cache_hit_rate": round(len(cache_hits) / max(len(results), 1), 3),
        "total_directives_resolved": sum(r["directives"] for r in successes),
    }


def compute_llm_comparison(total_directives, n_devs):
    """Compute LLM comparison for all three tiers."""
    comparisons = {}
    for tier_key, tier in LLM_TIERS.items():
        est = estimate_llm_discovery(total_directives, tier)
        comparisons[tier_key] = {
            "model": tier["label"],
            "pricing": {
                "input_per_1M": tier["input_per_1M"],
                "output_per_1M": tier["output_per_1M"],
            },
            "estimate": {
                "total_seconds": est["seconds"],
                "total_tool_calls": est["tool_calls"],
                "total_turns": est["turns"],
                "total_input_tokens": est["input_tokens"],
                "total_output_tokens": est["output_tokens"],
                "total_cost_usd": est["cost_usd"],
                "per_dev_seconds": round(est["seconds"] / max(n_devs, 1), 1),
            },
        }
    return comparisons


def compute_speedups(perseus_summary, llm_comparison, n_devs):
    """Compute speedup metrics for each LLM tier."""
    perseus_median = perseus_summary["render_times"]["median"] or 0.001
    perseus_wall = perseus_summary["render_times"]["max"] or 0.001

    result = {}
    for tier_key, tier_data in llm_comparison.items():
        llm_total = tier_data["estimate"]["total_seconds"]
        llm_per_dev = tier_data["estimate"]["per_dev_seconds"]
        result[tier_key] = {
            "system_speedup": round(llm_total / perseus_wall, 1),
            "dev_speedup": round(llm_per_dev / perseus_median, 1),
            "cost_saved_usd": tier_data["estimate"]["total_cost_usd"],
        }
    return result


def save_incremental(data, day, event_idx, teams_scope):
    """Save incremental results for crash recovery. Scope by team list hash."""
    INC_DIR.mkdir(parents=True, exist_ok=True)
    import hashlib
    scope_hash = hashlib.md5(",".join(sorted(teams_scope)).encode()).hexdigest()[:8]
    path = INC_DIR / f"{day}_{event_idx:02d}_{scope_hash}.json"
    path.write_text(json.dumps(data, indent=2))


def load_incremental(day, event_idx, teams_scope):
    """Load previously saved incremental result if it exists."""
    import hashlib
    scope_hash = hashlib.md5(",".join(sorted(teams_scope)).encode()).hexdigest()[:8]
    path = INC_DIR / f"{day}_{event_idx:02d}_{scope_hash}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def run_event(event, day, event_idx, dev_workspaces, total_directives_per_dev,
              cache_state, teams_scope, chaos=False):
    """Run one resolution event across all (or chaos subset) developers."""

    cached = load_incremental(day, event_idx, teams_scope)
    if cached:
        return cached

    if chaos:
        available_teams = list(set(k[0] for k in dev_workspaces.keys()))
        n_chaos_teams = min(3, len(available_teams))
        if n_chaos_teams < 2:
            # Single-team mode: no chaos — skip
            return load_incremental(day, event_idx, teams_scope) or {
                "event": f"{event['name']} [CHAOS: skipped — insufficient teams]",
                "time": event["time_slot"],
                "pattern": "skipped",
                "cache_state": cache_state,
                "chaos": True,
                "cache_busted": 0,
                "developers": 0,
                "total_directives": 0,
                "perseus_summary": {"renders": 0, "successful": 0, "failed": 0,
                    "render_times": {"min": 0, "max": 0, "median": 0, "p95": 0, "mean": 0},
                    "total_render_s": 0, "cache_hits": 0, "cache_hit_rate": 0,
                    "wall_clock_s": 0, "total_directives_resolved": 0},
                "llm_comparison": {t: {"model": LLM_TIERS[t]["label"], "pricing": {},
                    "estimate": {"total_seconds": 0, "total_tool_calls": 0,
                        "total_turns": 0, "total_input_tokens": 0,
                        "total_output_tokens": 0, "total_cost_usd": 0,
                        "per_dev_seconds": 0}} for t in LLM_TIERS},
                "speedups": {t: {"system_speedup": 0, "dev_speedup": 0,
                    "cost_saved_usd": 0} for t in LLM_TIERS},
                "failures": [],
                "per_dev_results": [],
            }
        chaos_teams = random.sample(available_teams, n_chaos_teams)
        participants = {k: v for k, v in dev_workspaces.items()
                        if k[0] in chaos_teams}
        event_label = f"{event['name']} [CHAOS: {','.join(chaos_teams)}]"
    else:
        participants = dev_workspaces
        event_label = event["name"]

    tasks = []
    for (team, dev_idx), ws in sorted(participants.items()):
        ctx, n = build_context_md(team)
        tasks.append({
            "key": f"{team}-{dev_idx:02d}",
            "team": team,
            "workspace": ws,
            "context_md": ctx,
            "directives": n,
        })

    total_dirs = sum(t["directives"] for t in tasks)
    n_tasks = len(tasks)

    cache_busted = 0
    if event["pattern"] == "burst" and cache_state == "warm":
        cache_busted = bust_random_caches(participants)

    max_workers = min(100, n_tasks)
    t0_wall = time.perf_counter()

    results = []
    if event["pattern"] == "burst":
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(render_perseus, t["workspace"],
                                 t["context_md"]): t for t in tasks}
            for f in as_completed(futures):
                t = futures[f]
                elapsed, success, error, cache_hit = f.result()
                results.append({
                    "dev": t["key"],
                    "team": t["team"],
                    "directives": t["directives"],
                    "elapsed_s": round(elapsed, 3),
                    "success": success,
                    "error": error if not success else None,
                    "cache_hit": cache_hit,
                })
    else:
        # Staggered: spread over 30s across teams
        by_team = defaultdict(list)
        for t in tasks:
            by_team[t["team"]].append(t)

        team_order = sorted(by_team.keys())
        delay_per_team = 30.0 / max(len(team_order), 1)

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {}
            team_start = t0_wall
            for team_name in team_order:
                for t in by_team[team_name]:
                    f = ex.submit(render_perseus, t["workspace"], t["context_md"])
                    futures[f] = t
                team_start += delay_per_team
                now = time.perf_counter()
                if now < team_start:
                    time.sleep(team_start - now)

            for f in as_completed(futures):
                t = futures[f]
                elapsed, success, error, cache_hit = f.result()
                results.append({
                    "dev": t["key"],
                    "team": t["team"],
                    "directives": t["directives"],
                    "elapsed_s": round(elapsed, 3),
                    "success": success,
                    "error": error if not success else None,
                    "cache_hit": cache_hit,
                })

    wall_clock = time.perf_counter() - t0_wall

    perseus_summary = compute_summary(results, n_tasks)
    perseus_summary["wall_clock_s"] = round(wall_clock, 3)

    failures = [r for r in results if not r["success"]]
    llm_comparison = compute_llm_comparison(total_dirs, n_tasks)
    speedups = compute_speedups(perseus_summary, llm_comparison, n_tasks)

    event_result = {
        "event": event_label,
        "time": event["time_slot"],
        "pattern": event["pattern"],
        "cache_state": cache_state,
        "chaos": chaos,
        "cache_busted": cache_busted,
        "developers": n_tasks,
        "total_directives": total_dirs,
        "perseus_summary": perseus_summary,
        "llm_comparison": llm_comparison,
        "speedups": speedups,
        "failures": [
            {"dev": r["dev"], "team": r["team"],
             "error": r["error"][:200]} for r in failures
        ],
        "per_dev_results": results,
    }

    save_incremental(event_result, day, event_idx, teams_scope)
    return event_result


# ============================================================================
# Main
# ============================================================================

def main():
    import datetime
    import platform as plat

    # Force unbuffered output so progress is visible immediately
    sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

    parser = argparse.ArgumentParser(
        description="Extreme Enterprise Week -- Perseus Stress Benchmark")
    parser.add_argument("--team", help="Run only a single team (e.g. 'web')")
    parser.add_argument("--day", help="Run only a single day (monday-friday)")
    args = parser.parse_args()

    teams_to_run = [args.team] if args.team else list(TEAM_PROFILES.keys())
    days_to_run = [args.day] if args.day else DAY_NAMES

    print("=" * 75)
    print("  PERSEUS EXTREME ENTERPRISE WEEK -- Stress Benchmark")
    print("=" * 75)
    print(f"  Developers: {sum(TEAM_PROFILES[t]['devs'] for t in teams_to_run)}")
    print(f"  Teams: {len(teams_to_run)}")
    print(f"  Days: {len(days_to_run)}")
    print(f"  Scheduled events/day: {len(DAILY_EVENTS)} + 1 chaos = {len(DAILY_EVENTS) + 1}")
    print(f"  Total events: {(len(DAILY_EVENTS) + 1) * len(days_to_run)}")
    print()

    if not args.day or args.day == "monday":
        shutil.rmtree(BASE, ignore_errors=True)
    BASE.mkdir(parents=True, exist_ok=True)

    # Setup workspaces
    print("-- Setting up workspaces --")
    dev_workspaces = {}
    total_directives_per_dev = {}

    for team in teams_to_run:
        profile = TEAM_PROFILES[team]
        nd = len(profile["fn"]())
        team_base = BASE / team
        for i in range(profile["devs"]):
            key = (team, i)
            ws = team_base / f"dev-{i:02d}"
            if not (ws / ".perseus" / "config.yaml").exists():
                setup_team_workspace(ws, team)
            dev_workspaces[key] = ws
            total_directives_per_dev[key] = nd
        dirs_total = profile["devs"] * nd
        print(f"  {profile['label']}: {profile['devs']} devs x {nd} directives = {dirs_total} ({team})")

    total_devs = len(dev_workspaces)
    total_base_directives = sum(total_directives_per_dev.values())
    print(f"\n  Total: {total_devs} developers, {total_base_directives} base directives")
    print()

    # Run the week
    week_results = {}

    for day_i, day_name in enumerate(days_to_run):
        is_monday = (day_name == "monday")

        day_summary = {
            "day": day_name,
            "date": (datetime.datetime.now() +
                     datetime.timedelta(days=day_i)).isoformat(),
            "cache_initial_state": "cold" if is_monday else "warm",
            "events": [],
        }

        for evt_i, event in enumerate(DAILY_EVENTS):
            cache_state = "cold" if (is_monday and evt_i == 0) else "warm"

            print(f"-- {day_name.title()} | Event {evt_i+1}/{len(DAILY_EVENTS)}: "
                  f"{event['name']} ({event['time_slot']}) [{cache_state}] --")

            event_result = run_event(
                event, day_name, evt_i,
                dev_workspaces, total_directives_per_dev,
                cache_state, teams_to_run
            )
            day_summary["events"].append(event_result)

            ps = event_result["perseus_summary"]
            rt = ps["render_times"]
            print(f"  {ps['renders']} renders, {ps['failed']} failed, "
                  f"median={rt['median']}s, p95={rt['p95']}s, "
                  f"wall={ps.get('wall_clock_s', 0)}s, "
                  f"cache_hits={ps['cache_hits']}/{ps['renders']} "
                  f"({ps['cache_hit_rate']:.0%})")

            best_tier = max(event_result["speedups"].items(),
                           key=lambda x: x[1]["dev_speedup"])
            print(f"  Best: {best_tier[0]} -- {best_tier[1]['dev_speedup']:,.0f}x dev speedup, "
                  f"${best_tier[1]['cost_saved_usd']:.2f} saved")

        # Chaos event
        chaos_evt_i = len(DAILY_EVENTS)
        chaos_event_def = {
            "name": "Chaos Surge (3-team burst)",
            "time_slot": f"{(random.randint(9, 17)):02d}:{random.randint(0, 59):02d}",
            "pattern": "burst",
        }

        print(f"-- {day_name.title()} | Chaos Event: "
              f"{chaos_event_def['name']} [{chaos_event_def['time_slot']}] --")

        chaos_result = run_event(
            chaos_event_def, day_name, chaos_evt_i,
            dev_workspaces, total_directives_per_dev,
            "warm", teams_to_run, chaos=True
        )
        day_summary["events"].append(chaos_result)

        cps = chaos_result["perseus_summary"]
        crt = cps["render_times"]
        print(f"  CHAOS: {cps['renders']} renders, {cps['failed']} failed, "
              f"p95={crt['p95']}s, wall={cps.get('wall_clock_s', 0)}s")

        week_results[day_name] = day_summary

        all_medians = [e["perseus_summary"]["render_times"]["median"]
                       for e in day_summary["events"]]
        print(f"  {day_name.title()} complete: "
              f"{len(day_summary['events'])} events, "
              f"median render range {min(all_medians):.3f}s-{max(all_medians):.3f}s")

        if day_name == "friday":
            print(f"\n-- Weekend gap: clearing all caches (simulates 48h TTL decay) --")
            clear_all_caches(dev_workspaces)
            print("  All caches cleared. Monday morning will be cold.")

    # =========================================================================
    # Cross-Week Analysis
    # =========================================================================

    print("\n" + "=" * 75)
    print("  CROSS-WEEK ANALYSIS")
    print("=" * 75)

    all_events = []
    for day_name in DAY_NAMES:
        if day_name in week_results:
            all_events.extend(week_results[day_name]["events"])

    total_renders = sum(e["perseus_summary"]["renders"] for e in all_events)
    total_failures = sum(e["perseus_summary"]["failed"] for e in all_events)
    total_perseus_wall = sum(e["perseus_summary"].get("wall_clock_s", 0)
                             for e in all_events)
    total_perseus_render = sum(e["perseus_summary"]["total_render_s"]
                               for e in all_events)

    cold_medians = [e["perseus_summary"]["render_times"]["median"]
                    for e in all_events if e["cache_state"] == "cold"]
    warm_medians = [e["perseus_summary"]["render_times"]["median"]
                    for e in all_events if e["cache_state"] == "warm"]

    cold_warm_ratio = (statistics.median(cold_medians) /
                       statistics.median(warm_medians)
                       if cold_medians and warm_medians else 0)

    all_cache_hits = sum(e["perseus_summary"].get("cache_hits", 0)
                         for e in all_events)
    cache_hit_rate = all_cache_hits / max(total_renders, 1)

    chaos_events = [e for e in all_events if e.get("chaos")]
    chaos_p95 = max((e["perseus_summary"]["render_times"]["p95"]
                     for e in chaos_events), default=0)

    largest_render = max((e["perseus_summary"]["render_times"]["max"]
                         for e in all_events), default=0)

    # Per-team stats
    team_stats = {}
    for team in TEAM_PROFILES:
        team_events = []
        for e in all_events:
            team_results = [r for r in e.get("per_dev_results", [])
                            if r.get("team") == team]
            if team_results:
                med = statistics.median([r["elapsed_s"] for r in team_results
                                         if r["success"]])
                team_events.append({
                    "event": e["event"],
                    "cache_state": e["cache_state"],
                    "median_s": round(med, 3),
                })
        cold_team = [t["median_s"] for t in team_events
                     if t["cache_state"] == "cold"]
        warm_team = [t["median_s"] for t in team_events
                     if t["cache_state"] == "warm"]
        team_stats[team] = {
            "directives": len(TEAM_PROFILES[team]["fn"]()),
            "cold_median_s": round(statistics.median(cold_team), 3)
                              if cold_team else None,
            "warm_median_s": round(statistics.median(warm_team), 3)
                               if warm_team else None,
        }

    # LLM aggregates
    llm_aggregates = {}
    for tier_key in LLM_TIERS:
        total_llm_s = sum(e["llm_comparison"][tier_key]["estimate"]["total_seconds"]
                         for e in all_events)
        total_llm_cost = sum(e["llm_comparison"][tier_key]["estimate"]["total_cost_usd"]
                           for e in all_events)
        total_llm_tokens_in = sum(e["llm_comparison"][tier_key]["estimate"]["total_input_tokens"]
                                  for e in all_events)
        total_llm_tokens_out = sum(e["llm_comparison"][tier_key]["estimate"]["total_output_tokens"]
                                   for e in all_events)

        all_dev_speedups = [e["speedups"][tier_key]["dev_speedup"]
                           for e in all_events]
        all_sys_speedups = [e["speedups"][tier_key]["system_speedup"]
                           for e in all_events]

        llm_aggregates[tier_key] = {
            "model": LLM_TIERS[tier_key]["label"],
            "total_seconds": round(total_llm_s, 1),
            "total_cost_usd": round(total_llm_cost, 2),
            "total_input_tokens": total_llm_tokens_in,
            "total_output_tokens": total_llm_tokens_out,
            "best_dev_speedup": round(max(all_dev_speedups), 1)
                               if all_dev_speedups else 0,
            "worst_dev_speedup": round(min(all_dev_speedups), 1)
                                if all_dev_speedups else 0,
            "mean_dev_speedup": round(statistics.mean(all_dev_speedups), 1)
                               if all_dev_speedups else 0,
            "annual_savings_usd": round(total_llm_cost * 52, 2),
            "annual_dev_hours_saved": round(total_llm_s * 52 / 3600, 1),
        }

    # Projections
    annual_renders = total_renders * 52
    best_annual_savings = max(a["annual_savings_usd"]
                              for a in llm_aggregates.values())
    worst_annual_savings = min(a["annual_savings_usd"]
                               for a in llm_aggregates.values())
    best_annual_hours = max(a["annual_dev_hours_saved"]
                            for a in llm_aggregates.values())

    cache_payback = (f"Perseus is cost-free per render. "
                     f"With {cache_hit_rate:.0%} cache hit rate, "
                     f"it amortizes instantly -- every render saves API cost.")

    cross_week = {
        "total_renders": total_renders,
        "total_failures": total_failures,
        "total_events": len(all_events),
        "total_perseus_wall_s": round(total_perseus_wall, 2),
        "total_perseus_render_s": round(total_perseus_render, 2),
        "cold_median_s": round(statistics.median(cold_medians), 3)
                         if cold_medians else None,
        "warm_median_s": round(statistics.median(warm_medians), 3)
                         if warm_medians else None,
        "cold_warm_ratio": round(cold_warm_ratio, 2),
        "cache_hit_rate": round(cache_hit_rate, 3),
        "chaos_surge_p95_s": round(chaos_p95, 3),
        "largest_render_s": round(largest_render, 3),
        "team_stats": team_stats,
        "comparison": llm_aggregates,
        "projections": {
            "annual_renders": annual_renders,
            "annual_cost_saved_range":
                f"${worst_annual_savings:,.0f} - ${best_annual_savings:,.0f} "
                f"depending on LLM tier",
            "annual_dev_hours_saved_range":
                f"{best_annual_hours:,.0f} developer-hours",
            "cache_payback": cache_payback,
            "note": "52-week projection. Perseus is OSS/free -- "
                    "every render eliminates LLM tool-calling cost.",
        },
    }

    output = {
        "meta": {
            "date": datetime.datetime.now().isoformat(),
            "host": plat.node(),
            "python": plat.python_version(),
            "perseus_version": (Path("/workspace/perseus/VERSION")
                                .read_text().strip()
                                if Path("/workspace/perseus/VERSION").exists()
                                else "unknown"),
            "developers": total_devs,
            "teams": len(teams_to_run),
            "events": len(all_events),
            "total_directives_per_full_render": total_base_directives,
            "workspace_base": str(BASE),
            "pricing_tiers": {
                k: {
                    "label": v["label"],
                    "input_per_1M": v["input_per_1M"],
                    "output_per_1M": v["output_per_1M"],
                    "tool_call_s": v["tool_call_s"],
                    "parallel": v["parallel"],
                }
                for k, v in LLM_TIERS.items()
            },
        },
        "week": week_results,
        "cross_week": cross_week,
    }

    out_path = OUT_DIR / "extreme_week_results.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\n[check] Full results -> {out_path}")

    # Narrative
    print(f"\n{'=' * 75}")
    print(f"  EXTREME ENTERPRISE WEEK -- VERDICT")
    print(f"{'=' * 75}")
    print(f"""
      {total_devs} developers. {len(teams_to_run)} teams. {total_renders} context resolutions.
      {total_failures} failures.

      Cache Lifecycle
        Cold median:   {cross_week['cold_median_s']:.3f}s
        Warm median:   {cross_week['warm_median_s']:.3f}s
        Cold/Warm gap: {cold_warm_ratio:.1f}x
        Cache hit rate: {cache_hit_rate:.0%}

      Chaos Surge
        P95 during 150-dev burst: {chaos_p95:.3f}s
        Slowest render ever:      {largest_render:.3f}s

      Annual Savings (52 weeks)
        Total renders/year: {annual_renders:,}
        API cost saved:     ${worst_annual_savings:,.0f} - ${best_annual_savings:,.0f}
        Dev hours saved:    {best_annual_hours:,.0f} hours
""")

    print("  LLM Tier Comparison:")
    print(f"  {'Tier':<22} {'Time':>10} {'Cost':>10} {'Dev Speedup':>12} {'Annual $':>12}")
    print(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*12} {'-'*12}")
    for tier_key in ["claude_opus", "gpt5", "gemini3_pro"]:
        a = llm_aggregates[tier_key]
        print(f"  {LLM_TIERS[tier_key]['label']:<22} "
              f"{a['total_seconds']:>8,.0f}s "
              f"${a['total_cost_usd']:>9,.2f} "
              f"{a['best_dev_speedup']:>10,.0f}x "
              f"${a['annual_savings_usd']:>11,.0f}")

    print(f"\n  Team Performance (Directives -> Speedup Impact):")
    print(f"  {'Team':<15} {'Directives':>12} {'Cold Med':>10} {'Warm Med':>10}")
    print(f"  {'-'*15} {'-'*12} {'-'*10} {'-'*10}")
    for team, stats in sorted(team_stats.items(),
                              key=lambda x: x[1]["directives"], reverse=True):
        cm = f"{stats['cold_median_s']:.3f}" if stats['cold_median_s'] else "--"
        wm = f"{stats['warm_median_s']:.3f}" if stats['warm_median_s'] else "--"
        print(f"  {team:<15} {stats['directives']:>12} {cm:>10} {wm:>10}")

    if total_failures > 0:
        print(f"\n  WARNING {total_failures} renders failed -- see results for details.")
    else:
        print(f"\n  OK Zero failures across {total_renders} renders.")


if __name__ == "__main__":
    main()
