#!/usr/bin/env python3
"""Mixed real-world benchmark environment: Perseus core + 8 satellite repos.

Layout (under <base>/repos/):
    perseus              ← the real Perseus repo (cloned from GitHub)
    acme-infra           ← Terraform, K8s manifests, Helm charts
    acme-api             ← Go/Python service with tests
    acme-web             ← React frontend with Jest/Cypress
    acme-mobile          ← React Native app
    acme-data-pipeline   ← Airflow DAGs, dbt models
    acme-ml-serving      ← Model registry, inference configs
    acme-shared-libs     ← Internal packages
    acme-docs            ← Internal wiki, runbooks

Each acme-* repo is a real git repo with:
  - 3–6 commits with realistic messages
  - Working files for its stack (package.json, requirements.txt, .tf, .yaml,
    Dockerfile, etc.)
  - Snapshot files for CI / dependency / security / test state:
      .ci-status.json, .test-results.json, .security-scan.json,
      .deps-freshness.json
  - CODEOWNERS

Usage:
    python3 setup_mixed.py [base_dir]
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

PERSEUS_GIT = "https://github.com/Perseus-Computing-LLC/perseus.git"

# ---------------------------------------------------------------------------

REPOS: list[tuple[str, dict]] = [
    ("acme-infra", {
        "stack": ["terraform", "k8s", "helm"],
        "files": {
            "main.tf": (
                'terraform {\n  required_version = ">= 1.5"\n  '
                'required_providers {\n    aws = { source = "hashicorp/aws", version = "~> 5.10" }\n'
                '    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.20" }\n'
                "  }\n}\n\n"
                'provider "aws" {\n  region = var.region\n}\n'
            ),
            "variables.tf": (
                'variable "region" {\n  type = string\n  default = "us-east-1"\n}\n'
                'variable "cluster_name" {\n  type = string\n  default = "acme-prod"\n}\n'
            ),
            "modules/cluster/main.tf": (
                'module "eks" {\n  source = "terraform-aws-modules/eks/aws"\n'
                '  version = "20.4.0"\n  cluster_name = var.cluster_name\n}\n'
            ),
            "k8s/namespaces.yaml": (
                "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: prod\n---\n"
                "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: staging\n"
            ),
            "helm/charts/api/Chart.yaml": (
                "apiVersion: v2\nname: api\nversion: 1.4.2\nappVersion: 2.7.1\n"
            ),
            "helm/charts/api/values.yaml": (
                "image:\n  repository: acmecorp/api\n  tag: 2.7.1\nreplicaCount: 3\n"
            ),
            ".github/workflows/terraform.yml": (
                "name: terraform\non: [push, pull_request]\njobs:\n"
                "  plan:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: hashicorp/setup-terraform@v3\n"
                "      - run: terraform init && terraform plan\n"
            ),
        },
        "commits": [
            "feat: bootstrap EKS cluster module",
            "feat(helm): add api/values.yaml and Chart.yaml",
            "fix(tf): pin aws provider to ~> 5.10",
            "chore: bump module/eks to 20.4.0",
            "ci: add terraform plan workflow",
        ],
    }),

    ("acme-api", {
        "stack": ["python", "go", "tests"],
        "files": {
            "go.mod": (
                "module github.com/acmecorp/api\n\ngo 1.22\n\nrequire (\n"
                "\tgithub.com/gin-gonic/gin v1.9.1\n"
                "\tgithub.com/jackc/pgx/v5 v5.5.0\n"
                "\tgithub.com/redis/go-redis/v9 v9.4.0\n"
                "\tgo.opentelemetry.io/otel v1.21.0\n"
                ")\n"
            ),
            "main.go": (
                'package main\n\nimport (\n\t"github.com/gin-gonic/gin"\n)\n\n'
                'func main() {\n\tr := gin.Default()\n\tr.GET("/health", func(c *gin.Context) {\n'
                '\t\tc.JSON(200, gin.H{"status": "ok"})\n\t})\n'
                '\tr.Run(":8080")\n}\n'
            ),
            "Dockerfile": (
                "FROM golang:1.22-alpine AS build\nWORKDIR /src\nCOPY . .\n"
                "RUN go build -o /api ./...\n\nFROM alpine:3.19\nCOPY --from=build /api /api\n"
                'ENTRYPOINT ["/api"]\n'
            ),
            "requirements-dev.txt": (
                "pytest==8.0.2\nhttpx==0.27.0\nlocust==2.20.0\nblack==24.2.0\n"
            ),
            "tests/test_health.py": (
                'import httpx\n\n\ndef test_health(base_url):\n'
                '    r = httpx.get(f"{base_url}/health")\n'
                '    assert r.status_code == 200\n'
            ),
            ".github/workflows/ci.yml": (
                "name: ci\non: [push, pull_request]\njobs:\n"
                "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-go@v5\n        with:\n          go-version: '1.22'\n"
                "      - run: go test ./... -race -coverprofile=coverage.out\n"
            ),
        },
        "commits": [
            "feat: scaffold gin server with /health",
            "feat(db): add pgx + redis clients",
            "test: add httpx-based contract tests",
            "feat(obs): wire opentelemetry tracing",
            "fix: tighten Dockerfile build stage",
            "chore: bump otel to 1.21.0",
        ],
    }),

    ("acme-web", {
        "stack": ["react", "jest", "cypress"],
        "files": {
            "package.json": json.dumps({
                "name": "acme-web",
                "version": "3.4.1",
                "private": True,
                "dependencies": {
                    "react": "18.2.0",
                    "react-dom": "18.2.0",
                    "react-router-dom": "6.22.0",
                    "@tanstack/react-query": "5.20.0",
                    "axios": "1.6.7",
                    "zustand": "4.5.0",
                },
                "devDependencies": {
                    "vite": "5.1.4",
                    "@vitejs/plugin-react": "4.2.1",
                    "jest": "29.7.0",
                    "cypress": "13.6.4",
                    "@testing-library/react": "14.2.1",
                    "typescript": "5.3.3",
                    "eslint": "8.57.0",
                },
                "scripts": {
                    "dev": "vite",
                    "build": "vite build",
                    "test": "jest",
                    "e2e": "cypress run",
                },
            }, indent=2),
            "src/App.tsx": (
                "import { Routes, Route } from 'react-router-dom';\n"
                "export default function App() {\n"
                "  return (\n    <Routes>\n      <Route path='/' element={<div>acme</div>} />\n"
                "    </Routes>\n  );\n}\n"
            ),
            "src/components/Cart.tsx": (
                "import { useState } from 'react';\nexport function Cart() {\n"
                "  const [items, setItems] = useState<string[]>([]);\n"
                "  return <div>{items.length} items</div>;\n}\n"
            ),
            "tests/Cart.test.tsx": (
                "import { render } from '@testing-library/react';\n"
                "import { Cart } from '../src/components/Cart';\n\n"
                "test('renders zero items', () => {\n"
                "  const { getByText } = render(<Cart />);\n"
                "  expect(getByText('0 items')).toBeTruthy();\n});\n"
            ),
            "cypress/e2e/checkout.cy.ts": (
                "describe('checkout', () => {\n"
                "  it('loads cart', () => {\n"
                "    cy.visit('/');\n    cy.contains('items');\n  });\n});\n"
            ),
            ".github/workflows/ci.yml": (
                "name: ci\non: [push, pull_request]\njobs:\n"
                "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-node@v4\n        with:\n          node-version: '20'\n"
                "      - run: npm ci\n      - run: npm test\n      - run: npm run build\n"
            ),
        },
        "commits": [
            "feat: scaffold vite + react app",
            "feat(cart): add Cart component + zustand store",
            "feat(routes): wire react-router-dom",
            "test: Jest + RTL coverage for Cart",
            "test(e2e): cypress smoke for checkout",
            "fix: tighten axios baseURL handling",
        ],
    }),

    ("acme-mobile", {
        "stack": ["react-native", "expo"],
        "files": {
            "package.json": json.dumps({
                "name": "acme-mobile",
                "version": "2.1.0",
                "private": True,
                "dependencies": {
                    "expo": "50.0.6",
                    "react": "18.2.0",
                    "react-native": "0.73.4",
                    "@react-navigation/native": "6.1.10",
                    "@react-navigation/stack": "6.3.21",
                    "axios": "1.6.7",
                    "react-native-mmkv": "2.12.1",
                },
                "devDependencies": {
                    "typescript": "5.3.3",
                    "jest": "29.7.0",
                    "@testing-library/react-native": "12.4.3",
                    "detox": "20.16.0",
                },
                "scripts": {
                    "start": "expo start",
                    "test": "jest",
                    "e2e": "detox test",
                },
            }, indent=2),
            "App.tsx": (
                "import { NavigationContainer } from '@react-navigation/native';\n"
                "import { createStackNavigator } from '@react-navigation/stack';\n"
                "const Stack = createStackNavigator();\n"
                "export default function App() {\n  return <NavigationContainer />;\n}\n"
            ),
            "src/screens/Home.tsx": (
                "import { View, Text } from 'react-native';\nexport function Home() {\n"
                "  return <View><Text>Home</Text></View>;\n}\n"
            ),
            "ios/Podfile": (
                "platform :ios, '14.0'\nuse_frameworks!\n"
            ),
            "android/build.gradle": (
                "buildscript {\n  ext {\n    minSdkVersion = 24\n    compileSdkVersion = 34\n  }\n}\n"
            ),
            ".github/workflows/ci.yml": (
                "name: mobile-ci\non: [push, pull_request]\njobs:\n"
                "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-node@v4\n        with:\n          node-version: '20'\n"
                "      - run: npm ci\n      - run: npm test\n"
            ),
        },
        "commits": [
            "feat: bootstrap expo + RN 0.73",
            "feat(nav): add stack navigator skeleton",
            "feat(home): Home screen scaffold",
            "test: Detox e2e harness",
            "chore: bump expo to 50.0.6",
        ],
    }),

    ("acme-data-pipeline", {
        "stack": ["airflow", "dbt", "python"],
        "files": {
            "requirements.txt": (
                "apache-airflow==2.8.1\n"
                "dbt-core==1.7.4\n"
                "dbt-postgres==1.7.4\n"
                "pandas==2.2.0\n"
                "polars==0.20.9\n"
                "pyarrow==15.0.0\n"
            ),
            "dags/ingest_orders.py": (
                "from datetime import datetime\n"
                "from airflow import DAG\n"
                "from airflow.operators.bash import BashOperator\n\n"
                "with DAG('ingest_orders', start_date=datetime(2026, 1, 1),\n"
                "         schedule='@hourly', catchup=False) as dag:\n"
                "    extract = BashOperator(task_id='extract', bash_command='echo extract')\n"
                "    transform = BashOperator(task_id='transform', bash_command='echo transform')\n"
                "    load = BashOperator(task_id='load', bash_command='echo load')\n"
                "    extract >> transform >> load\n"
            ),
            "dags/refresh_metrics.py": (
                "from datetime import datetime\n"
                "from airflow import DAG\n"
                "from airflow.operators.python import PythonOperator\n\n"
                "def refresh():\n    print('refresh')\n\n"
                "with DAG('refresh_metrics', start_date=datetime(2026, 1, 1),\n"
                "         schedule='@daily', catchup=False) as dag:\n"
                "    PythonOperator(task_id='refresh', python_callable=refresh)\n"
            ),
            "dbt/dbt_project.yml": (
                "name: 'acme_dbt'\nversion: '1.0.0'\nconfig-version: 2\n"
                "profile: 'acme'\nmodels:\n  acme_dbt:\n    materialized: view\n"
            ),
            "dbt/models/orders_enriched.sql": (
                "select o.id, o.created_at, c.name as customer_name\n"
                "from {{ ref('orders') }} o\n"
                "join {{ ref('customers') }} c on c.id = o.customer_id\n"
            ),
            ".github/workflows/ci.yml": (
                "name: data-ci\non: [push, pull_request]\njobs:\n"
                "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n"
                "      - run: pip install -r requirements.txt\n"
                "      - run: dbt deps && dbt parse && dbt test --select state:modified\n"
            ),
        },
        "commits": [
            "feat: airflow ingest_orders DAG",
            "feat(dbt): dbt project skeleton",
            "feat(dbt): orders_enriched model",
            "test: dbt CI workflow",
            "chore: bump airflow to 2.8.1",
        ],
    }),

    ("acme-ml-serving", {
        "stack": ["python", "fastapi", "torch"],
        "files": {
            "requirements.txt": (
                "fastapi==0.110.0\n"
                "uvicorn==0.27.1\n"
                "torch==2.2.0\n"
                "transformers==4.38.1\n"
                "pydantic==2.6.1\n"
                "prometheus-client==0.20.0\n"
            ),
            "app.py": (
                "from fastapi import FastAPI\nfrom pydantic import BaseModel\n\n"
                "app = FastAPI()\n\nclass Predict(BaseModel):\n    text: str\n\n"
                "@app.post('/predict')\n"
                "def predict(p: Predict):\n    return {'label': 'positive', 'score': 0.93}\n"
            ),
            "models/registry.json": json.dumps({
                "models": [
                    {"id": "sentiment-v2", "version": "2.4.0", "size_mb": 247, "loaded": True},
                    {"id": "embeddings-v1", "version": "1.9.3", "size_mb": 412, "loaded": True},
                    {"id": "ranker-v3", "version": "3.0.1-rc", "size_mb": 1820, "loaded": False},
                ],
            }, indent=2),
            "Dockerfile": (
                "FROM python:3.11-slim\nWORKDIR /app\nCOPY . .\n"
                "RUN pip install -r requirements.txt\n"
                'CMD ["uvicorn", "app:app", "--host", "0.0.0.0"]\n'
            ),
            ".github/workflows/ci.yml": (
                "name: ml-ci\non: [push, pull_request]\njobs:\n"
                "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n"
                "      - run: pip install -r requirements.txt\n"
                "      - run: pytest -q\n"
            ),
        },
        "commits": [
            "feat: scaffold fastapi inference server",
            "feat(models): sentiment-v2 model card",
            "feat(models): embeddings-v1 add",
            "wip: ranker-v3 release candidate",
            "chore: bump torch to 2.2.0",
        ],
    }),

    ("acme-shared-libs", {
        "stack": ["python", "typescript"],
        "files": {
            "pyproject.toml": (
                "[project]\nname = 'acme-shared'\nversion = '0.14.2'\n"
                "dependencies = [\n  'pydantic>=2.6',\n  'httpx>=0.27',\n  'structlog>=24.1',\n]\n"
            ),
            "acme_shared/__init__.py": "__version__ = '0.14.2'\n",
            "acme_shared/tracing.py": (
                "import structlog\nlog = structlog.get_logger()\n\n"
                "def trace(name: str):\n    def deco(fn):\n        def wrapper(*a, **kw):\n"
                "            log.info('trace_start', name=name)\n            return fn(*a, **kw)\n"
                "        return wrapper\n    return deco\n"
            ),
            "package.json": json.dumps({
                "name": "@acme/shared",
                "version": "0.14.2",
                "main": "dist/index.js",
                "types": "dist/index.d.ts",
                "dependencies": {"zod": "3.22.4", "ky": "1.2.0"},
                "devDependencies": {"typescript": "5.3.3", "vitest": "1.3.1"},
            }, indent=2),
            "src/index.ts": (
                "export * from './tracing';\nexport * from './schemas';\n"
            ),
            "src/tracing.ts": (
                "export function trace<T>(name: string, fn: () => T): T {\n"
                "  console.log('trace_start', name);\n  return fn();\n}\n"
            ),
            ".github/workflows/ci.yml": (
                "name: libs-ci\non: [push, pull_request]\njobs:\n"
                "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-node@v4\n      - run: npm ci && npm test\n"
                "      - uses: actions/setup-python@v5\n      - run: pip install -e . && pytest\n"
            ),
        },
        "commits": [
            "feat: split tracing into shared lib",
            "feat(ts): mirror python tracing in TS",
            "fix: bump pydantic to 2.6",
            "chore: cut 0.14.2",
        ],
    }),

    ("acme-docs", {
        "stack": ["markdown"],
        "files": {
            "README.md": "# acme-docs\n\nInternal wiki + runbooks.\n",
            "runbooks/incident-payments.md": (
                "# Runbook — payments incident\n\n"
                "1. Page on-call.\n2. Verify Stripe webhook ingest.\n"
                "3. Drain DLQ if backlog > 1000.\n"
            ),
            "runbooks/incident-checkout.md": (
                "# Runbook — checkout outage\n\n"
                "1. Confirm api-gateway is up.\n"
                "2. Check feature_flag_new_checkout in prod vs staging.\n"
                "3. Roll back via blue-green if drift detected.\n"
            ),
            "wiki/architecture.md": (
                "# Architecture overview\n\n"
                "- Edge: CloudFront → API Gateway → Service mesh\n"
                "- Data: Postgres (primary + shards) → ClickHouse → Lake\n"
                "- ML: Inference fleet → model registry\n"
            ),
            ".github/workflows/lint.yml": (
                "name: docs-lint\non: [push, pull_request]\njobs:\n"
                "  lint:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: DavidAnson/markdownlint-cli2-action@v15\n"
            ),
        },
        "commits": [
            "docs: bootstrap wiki + runbooks",
            "docs(runbook): payments incident",
            "docs(runbook): checkout outage",
            "docs(arch): architecture overview",
        ],
    }),
]


# ---------------------------------------------------------------------------

def resolve_base(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    return Path(tempfile.gettempdir()).resolve() / "mixed-real-world"


def run(cmd: list[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, check=True,
        capture_output=capture, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "acme-bot", "GIT_AUTHOR_EMAIL": "bot@acme.test",
             "GIT_COMMITTER_NAME": "acme-bot", "GIT_COMMITTER_EMAIL": "bot@acme.test"},
    )


def write_file(root: Path, rel: str, content: str) -> None:
    dst = root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8")


def build_repo(base: Path, name: str, spec: dict, rng: random.Random) -> None:
    root = base / "repos" / name
    if root.exists():
        # Re-initialise cleanly.
        import shutil
        shutil.rmtree(root, onerror=lambda f, p, e: None)
    root.mkdir(parents=True, exist_ok=True)

    # CODEOWNERS
    write_file(root, ".github/CODEOWNERS",
               "* @acme/platform\n*.tf @acme/infra\n*.tsx @acme/web\n*.py @acme/backend\n")

    # README
    write_file(root, "README.md", f"# {name}\n\nStack: {', '.join(spec['stack'])}.\n")

    # Stack files
    for rel, content in spec["files"].items():
        write_file(root, rel, content)

    # Initialize git, commit in N chunks (so git log has history)
    run(["git", "init", "-q", "-b", "main"], root)
    run(["git", "add", "."], root)
    commits = spec["commits"]
    first = commits[0]
    # First commit: everything
    run(["git", "commit", "-q", "-m", first], root)

    # Stagger additional commits by mutating README to create churn.
    for msg in commits[1:]:
        write_file(root, "CHANGELOG.md",
                   f"# Changelog\n\n## Unreleased\n\n- {msg}\n")
        run(["git", "add", "CHANGELOG.md"], root)
        run(["git", "commit", "-q", "-m", msg], root)

    # Make working tree dirty for *some* repos so `git status` shows changes.
    if rng.random() < 0.55:
        # Touch one file with a working-tree change (not committed).
        target = root / "README.md"
        target.write_text(target.read_text(encoding="utf-8") + "\n<!-- WIP edit -->\n", encoding="utf-8")

    # CI status snapshot (synthetic, deterministic per-repo)
    status = rng.choices(
        ["PASSED", "FAILED", "RUNNING"],
        weights=[70, 22, 8],
        k=1,
    )[0]
    write_file(root, ".ci-status.json", json.dumps({
        "repo": name,
        "status": status,
        "branch": "main",
        "last_run": (datetime.now() - timedelta(minutes=rng.randint(2, 600))).isoformat(),
        "commit_sha": hashlib.sha1(f"{name}-ci".encode()).hexdigest()[:10],
        "failed_jobs": [] if status != "FAILED" else [
            rng.choice(["unit-tests", "lint", "build", "integration"]),
        ],
        "duration_seconds": rng.randint(30, 1500),
    }, indent=2))

    # Dependency freshness
    deps = rng.randint(8, 40)
    outdated = rng.randint(0, max(deps // 4, 1))
    vulnerable = rng.randint(0, max(outdated // 2, 0))
    write_file(root, ".deps-freshness.json", json.dumps({
        "repo": name,
        "total_dependencies": deps,
        "outdated": outdated,
        "vulnerable": vulnerable,
        "last_audit": (datetime.now() - timedelta(days=rng.randint(0, 14))).isoformat(),
    }, indent=2))

    # Security scan snapshot
    findings = rng.randint(0, 18)
    write_file(root, ".security-scan.json", json.dumps({
        "repo": name,
        "scanner": rng.choice(["snyk", "trivy", "semgrep"]),
        "scan_time": datetime.now().isoformat(),
        "findings": findings,
        "by_severity": {
            "CRITICAL": rng.randint(0, max(findings // 6, 0)),
            "HIGH": rng.randint(0, max(findings // 4, 0)),
            "MEDIUM": rng.randint(0, max(findings // 2, 0)),
            "LOW": rng.randint(0, findings),
        },
    }, indent=2))

    # Test results
    total_tests = rng.randint(40, 850)
    failures = rng.randint(0, max(total_tests // 40, 0))
    skipped = rng.randint(0, max(total_tests // 30, 0))
    write_file(root, ".test-results.json", json.dumps({
        "repo": name,
        "runner": rng.choice(["pytest", "jest", "go test", "vitest", "detox"]),
        "total_tests": total_tests,
        "passed": total_tests - failures - skipped,
        "failed": failures,
        "skipped": skipped,
        "duration_seconds": rng.randint(20, 1200),
        "run_at": (datetime.now() - timedelta(minutes=rng.randint(5, 600))).isoformat(),
    }, indent=2))


def clone_perseus(base: Path) -> None:
    target = base / "repos" / "perseus"
    if target.exists():
        return
    print("  Cloning Perseus core repo...")
    run(["git", "clone", "--quiet", PERSEUS_GIT, str(target)], base)


# ---------------------------------------------------------------------------
# Scanner scripts
# ---------------------------------------------------------------------------

SCANNERS: dict[str, str] = {
    "scan-repo-log.py": r"""
import os, subprocess, sys
base = os.environ["MIXED_BASE"]
name = sys.argv[1]
root = os.path.join(base, "repos", name)
print(f"## {name}")
print()
r = subprocess.run(["git", "log", "--oneline", "-10"], cwd=root,
                   capture_output=True, text=True)
if r.returncode != 0:
    print(f"(git log failed: {r.stderr.strip()})")
else:
    print(r.stdout.strip())
print()
print("`git status --short`:")
s = subprocess.run(["git", "status", "--short"], cwd=root,
                   capture_output=True, text=True)
out = s.stdout.strip()
print(out if out else "(clean)")
""",

    "scan-ci-rollup.py": r"""
import json, os
base = os.environ["MIXED_BASE"]
repos = sorted(os.listdir(os.path.join(base, "repos")))
print(f"CI rollup across {len(repos)} repos:")
counts = {"PASSED": 0, "FAILED": 0, "RUNNING": 0, "UNKNOWN": 0}
rows = []
for r in repos:
    p = os.path.join(base, "repos", r, ".ci-status.json")
    if os.path.isfile(p):
        d = json.load(open(p))
        counts[d["status"]] = counts.get(d["status"], 0) + 1
        rows.append((d["status"], r, d["branch"], d.get("failed_jobs", []), d["commit_sha"]))
    else:
        counts["UNKNOWN"] += 1
        rows.append(("UNKNOWN", r, "?", [], "?"))
for st in ("PASSED", "FAILED", "RUNNING", "UNKNOWN"):
    print(f"  {st:8s} {counts[st]}")
print()
print("Per repo:")
for st, repo, branch, fj, sha in sorted(rows):
    failed = (" failed=" + ",".join(fj)) if fj else ""
    print(f"  {st:8s} {repo:22s} branch={branch:6s} sha={sha}{failed}")
""",

    "scan-security-rollup.py": r"""
import json, os
base = os.environ["MIXED_BASE"]
repos = sorted(os.listdir(os.path.join(base, "repos")))
total = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
rows = []
for r in repos:
    p = os.path.join(base, "repos", r, ".security-scan.json")
    if not os.path.isfile(p):
        continue
    d = json.load(open(p))
    rows.append((d.get("findings", 0), r, d["scanner"], d["by_severity"]))
    for sev, n in d["by_severity"].items():
        total[sev] = total.get(sev, 0) + n
print("Security rollup:")
print(f"  CRITICAL: {total['CRITICAL']}")
print(f"  HIGH:     {total['HIGH']}")
print(f"  MEDIUM:   {total['MEDIUM']}")
print(f"  LOW:      {total['LOW']}")
print()
print("Per repo:")
for findings, r, scanner, sev in sorted(rows, reverse=True):
    print(f"  {r:22s} scanner={scanner:8s} findings={findings:3d} "
          f"crit={sev['CRITICAL']} high={sev['HIGH']} med={sev['MEDIUM']} low={sev['LOW']}")
""",

    "scan-deps-rollup.py": r"""
import json, os
base = os.environ["MIXED_BASE"]
repos = sorted(os.listdir(os.path.join(base, "repos")))
total_deps = total_outdated = total_vuln = 0
rows = []
for r in repos:
    p = os.path.join(base, "repos", r, ".deps-freshness.json")
    if not os.path.isfile(p):
        continue
    d = json.load(open(p))
    total_deps += d["total_dependencies"]
    total_outdated += d["outdated"]
    total_vuln += d["vulnerable"]
    rows.append((d["vulnerable"], d["outdated"], r, d["total_dependencies"], d["last_audit"][:10]))
print(f"Dependency freshness across {len(rows)} repos:")
print(f"  Total deps:    {total_deps}")
print(f"  Outdated:      {total_outdated}")
print(f"  Vulnerable:    {total_vuln}")
print()
for vuln, out, r, total, audit in sorted(rows, reverse=True):
    print(f"  {r:22s} {total:4d} deps  outdated={out:2d}  vuln={vuln:2d}  audit={audit}")
""",

    "scan-test-rollup.py": r"""
import json, os
base = os.environ["MIXED_BASE"]
repos = sorted(os.listdir(os.path.join(base, "repos")))
total = total_pass = total_fail = total_skip = 0
rows = []
for r in repos:
    p = os.path.join(base, "repos", r, ".test-results.json")
    if not os.path.isfile(p):
        continue
    d = json.load(open(p))
    total += d["total_tests"]
    total_pass += d["passed"]
    total_fail += d["failed"]
    total_skip += d["skipped"]
    rows.append((d["failed"], d["total_tests"], r, d["runner"], d["passed"]))
print(f"Test rollup:")
print(f"  Total:   {total}")
print(f"  Passed:  {total_pass}")
print(f"  Failed:  {total_fail}")
print(f"  Skipped: {total_skip}")
print()
print("Per repo (sorted by failure count):")
for failed, total, r, runner, passed in sorted(rows, reverse=True):
    pct = (passed / total * 100) if total else 0
    print(f"  {r:22s} runner={runner:9s} pass={passed:4d}/{total:4d} ({pct:5.1f}%) failed={failed}")
""",

    "scan-files-touched.py": r"""
import os, subprocess
base = os.environ["MIXED_BASE"]
repos = sorted(os.listdir(os.path.join(base, "repos")))
print("Files touched per repo in last 5 commits:")
for r in repos:
    root = os.path.join(base, "repos", r)
    git_dir = os.path.join(root, ".git")
    if not os.path.isdir(git_dir):
        continue
    p = subprocess.run(["git", "log", "--name-only", "--pretty=", "-5"],
                       cwd=root, capture_output=True, text=True)
    files = [f for f in p.stdout.splitlines() if f.strip()]
    print(f"  {r:22s} {len(files)} files (unique: {len(set(files))})")
""",

    "scan-codeowners-overview.py": r"""
import os
base = os.environ["MIXED_BASE"]
repos = sorted(os.listdir(os.path.join(base, "repos")))
print(f"CODEOWNERS presence across {len(repos)} repos:")
for r in repos:
    co1 = os.path.join(base, "repos", r, ".github", "CODEOWNERS")
    co2 = os.path.join(base, "repos", r, "CODEOWNERS")
    present = "yes" if os.path.isfile(co1) or os.path.isfile(co2) else "no"
    print(f"  {r:22s} CODEOWNERS={present}")
""",
}


def write_scanners(base: Path) -> list[str]:
    scripts_dir = base / ".perseus" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    names = []
    base_literal = base.as_posix()
    for name, body in SCANNERS.items():
        prelude = (
            "import os, sys\n"
            "try:\n"
            "    sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
            "except Exception:\n"
            "    pass\n"
            f"os.environ.setdefault('MIXED_BASE', {base_literal!r})\n"
        )
        (scripts_dir / name).write_text(prelude + body.lstrip() + "\n", encoding="utf-8")
        names.append(name)
    return names


def write_context(base: Path) -> None:
    perseus_dir = base / ".perseus"
    perseus_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        (perseus_dir / "config.yaml").write_text(
            "render:\n  allow_query_shell: true\n  allow_services_command: false\n",
            encoding="utf-8",
        )
    else:
        (perseus_dir / "config.yaml").write_text(
            "render:\n  allow_query_shell: true\n  allow_services_command: false\n  shell: /bin/bash\n",
            encoding="utf-8",
        )
    scanners_dir = (base / ".perseus" / "scripts").as_posix()
    repos = ["perseus"] + [r[0] for r in REPOS]

    lines = [
        "@perseus v0.8",
        "",
        "@prompt",
        "This document was rendered live by Perseus from 9 git repos: the real",
        "Perseus repo cloned from GitHub, plus 8 synthetic ACME satellites.",
        "All git logs, statuses, CI/security/dep/test rollups, and codeowner",
        "states are pre-resolved. Do NOT cd into individual repos to verify.",
        "@end",
        "",
        "# ACME Org — Cross-Repo Snapshot",
        "",
        "**Generated:** @date format=\"YYYY-MM-DD HH:mm UTC\"",
        f"**Workspace:** `{base}`",
        f"**Repos in scope:** {len(repos)} ({', '.join(repos)})",
        "",
        "---",
        "",
        "## 1. CI Status Rollup (all repos)",
        f'@query "python -X utf8 {scanners_dir}/scan-ci-rollup.py"',
        "",
        "## 2. Security Scan Rollup (all repos)",
        f'@query "python -X utf8 {scanners_dir}/scan-security-rollup.py"',
        "",
        "## 3. Dependency Freshness Rollup",
        f'@query "python -X utf8 {scanners_dir}/scan-deps-rollup.py"',
        "",
        "## 4. Test Results Rollup",
        f'@query "python -X utf8 {scanners_dir}/scan-test-rollup.py"',
        "",
        "## 5. Files Touched (last 5 commits per repo)",
        f'@query "python -X utf8 {scanners_dir}/scan-files-touched.py"',
        "",
        "## 6. CODEOWNERS Presence",
        f'@query "python -X utf8 {scanners_dir}/scan-codeowners-overview.py"',
        "",
        "---",
        "",
        "# Per-Repo `git log` + `git status`",
        "",
    ]
    for r in repos:
        lines.append(f"### `{r}`")
        lines.append(f'@query "python -X utf8 {scanners_dir}/scan-repo-log.py {r}"')
        lines.append("")

    lines.extend([
        "---",
        "",
        "## Available Skills",
        "@skills flag_stale=true",
        "",
        "## Recent Sessions",
        "@session count=3",
        "",
        "## Maintenance Snapshot",
        "@health",
        "",
    ])

    (perseus_dir / "context.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    base = resolve_base(sys.argv[1] if len(sys.argv) > 1 else None)
    base.mkdir(parents=True, exist_ok=True)
    print(f"Building mixed real-world benchmark at {base} ...")
    rng = random.Random(20260524)

    # 1) Perseus (real)
    clone_perseus(base)

    # 2) 8 satellite repos
    for name, spec in REPOS:
        print(f"  Building {name} ...")
        build_repo(base, name, spec, rng)

    # 3) Scanners + context
    names = write_scanners(base)
    write_context(base)

    n_files = sum(1 for _ in base.rglob("*") if _.is_file())
    n_repos = len(REPOS) + 1
    print()
    print(f"  Done. {n_repos} repos · {n_files} files generated.")
    print()
    print(f"  Render:")
    print(f"    cd {base}")
    print(f"    PYTHONUTF8=1 python /path/to/perseus.py render .perseus/context.md --output .hermes.md")


if __name__ == "__main__":
    main()
