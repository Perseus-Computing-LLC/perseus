#!/usr/bin/env python3
"""Mega-enterprise benchmark environment setup for Perseus cold-start testing.

Synthesizes a 500-microservice platform with:
  - 500 microservices × 3 environments (prod/staging/dev) — health.json,
    deploy log, per-env configs
  - 50 databases with Flyway migration status (10–30 each, realistic
    pending counts)
  - 30 CI/CD pipelines (mixed statuses, branches, trigger types)
  - 100 Docker containers across 3 envs (mixed running/exited/crashed)
  - Trivy CVE scan with 200+ findings
  - SonarQube with module-level results
  - Snyk SBOM with 2,000+ packages
  - Prometheus alerts (500+, 50+ CRITICAL unacknowledged)
  - 20 disk volumes, 200 K8s pods, 15 load balancers
  - License risk tiers + GDPR data residency map
  - Config drift across 50+ services
  - 50 deploys across 25 team members (7-day window)

Total: roughly 25,000 generated files.

Usage:
    python3 setup_mega.py [base_dir]

Default base_dir is platform-temp/mega-enterprise (Windows-safe).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Topology constants
# ---------------------------------------------------------------------------

ENVS = ["prod", "staging", "dev"]

DOMAIN_SUFFIXES = ["acmecorp", "globex", "initech", "umbrella", "stark"]
PRODUCT_LINES = [
    "checkout", "billing", "shipping", "catalog", "search",
    "recommendations", "inventory", "auth", "identity", "session",
    "notifications", "email", "sms", "push", "feed",
    "analytics", "reporting", "metrics", "alerts", "tracing",
    "logging", "audit", "compliance", "risk", "fraud",
    "kyc", "ledger", "wallet", "payouts", "refunds",
    "subscription", "membership", "loyalty", "promo", "discount",
    "tax", "currency", "fx", "settlement", "reconciliation",
    "support", "ticketing", "chat", "voice", "video",
    "media", "asset", "cdn", "image", "thumbnail",
    "transcode", "watermark", "moderation", "scan",
    "rules", "policy", "permission", "rbac", "scim",
    "feature", "experiment", "ab", "config", "secrets",
    "vault", "kms", "encryption", "signing", "tokens",
    "gateway", "ingress", "egress", "proxy", "router",
    "graph", "schema", "registry", "directory", "indexer",
    "matcher", "ranker", "scoring", "model", "embedding",
    "trainer", "evaluator", "tuner", "pipeline", "scheduler",
    "queue", "worker", "dispatcher", "router2", "broker",
    "stream", "consumer", "producer", "ingestor", "exporter",
    "warehouse", "lake", "etl", "elt", "snapshot",
    "backup", "restore", "replica", "sync", "migrator",
]


def _service_names(n: int = 500) -> list[str]:
    rng = random.Random(1337)
    seen: set[str] = set()
    out: list[str] = []
    while len(out) < n:
        prod = rng.choice(PRODUCT_LINES)
        tier = rng.choice(["api", "worker", "consumer", "gateway", "store",
                           "indexer", "scheduler", "agg", "ingest", "egress"])
        idx = rng.randint(1, 99)
        name = f"{prod}-{tier}-{idx:02d}"
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _database_names(n: int = 50) -> list[str]:
    rng = random.Random(424242)
    domains = [
        "users", "orders", "inventory", "billing", "payments",
        "ledger", "audit", "events", "logs", "metrics",
        "analytics", "reports", "search", "catalog", "feed",
        "cms", "media", "assets", "permissions", "rbac",
        "subscriptions", "promotions", "loyalty", "kyc", "risk",
        "fraud", "support", "tickets", "chats", "calls",
        "models", "embeddings", "experiments", "rules", "config",
        "secrets", "tokens", "sessions", "trackers", "telemetry",
        "rl", "feature_flags", "ab_tests", "deployments", "releases",
        "graph", "warehouse", "lake", "snapshots", "backups",
    ]
    out = []
    for d in domains[:n]:
        env_suffix = rng.choice(["primary", "ro", "shard0", "shard1", "global"])
        out.append(f"{d}-{env_suffix}-db")
    return out[:n]


def _pipeline_names(n: int = 30) -> list[str]:
    return [
        "deploy-prod", "deploy-staging", "deploy-dev",
        "canary-release", "rolling-release", "blue-green-release",
        "security-scan", "secret-scan", "dependency-scan",
        "integration-tests", "e2e-smoke-tests", "contract-tests",
        "load-tests", "chaos-tests", "perf-tests",
        "build-images", "build-frontend", "build-mobile",
        "publish-artifacts", "publish-docs", "publish-mobile",
        "data-pipeline", "ml-train", "ml-eval",
        "infra-plan", "infra-apply", "infra-drift-detect",
        "license-scan", "compliance-report", "audit-export",
    ][:n]


def _team_members(n: int = 25) -> list[str]:
    names = [
        "alice", "bob", "carol", "dave", "eve",
        "frank", "grace", "heidi", "ivan", "judy",
        "kai", "leo", "mona", "nora", "omar",
        "peggy", "quinn", "rita", "sam", "trent",
        "uma", "vera", "wally", "xena", "yara",
        "zack",
    ]
    return names[:n]


def _gdpr_regions() -> list[str]:
    return [
        "eu-west-1", "eu-central-1", "us-east-1", "us-west-2",
        "ap-southeast-1", "ap-northeast-1", "ap-south-1", "sa-east-1",
        "ca-central-1", "me-south-1", "af-south-1",
    ]


# ---------------------------------------------------------------------------
# Resolve BASE dir (Windows + bash compatible)
# ---------------------------------------------------------------------------

def resolve_base(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    benchmark_root = Path(os.environ.get("MEGA_BENCH_BASE", "")) if os.environ.get("MEGA_BENCH_BASE") else None
    if benchmark_root:
        return benchmark_root.resolve()
    return Path(tempfile.gettempdir()).resolve() / "mega-enterprise"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_services(base: Path, services: list[str], rng: random.Random) -> None:
    services_root = base / "services"
    for svc in services:
        d = services_root / svc
        d.mkdir(parents=True, exist_ok=True)
        # Health
        status = rng.choices(
            ["healthy", "degraded", "down", "crashloop"],
            weights=[78, 14, 5, 3],
            k=1,
        )[0]
        health = {
            "status": status,
            "version": f"{rng.randint(1, 6)}.{rng.randint(0, 18)}.{rng.randint(0, 199)}",
            "uptime_hours": round(rng.uniform(0.2, 2200), 1),
            "last_deploy": (datetime.now() - timedelta(hours=rng.randint(1, 720))).isoformat(),
            "owner_team": rng.choice([
                "checkout", "billing", "platform", "data", "ml",
                "infra", "growth", "ops", "security", "support",
            ]),
            "tier": rng.choice(["tier-1", "tier-2", "tier-3"]),
            "sli_p99_ms": round(rng.uniform(20, 850), 1),
            "error_budget_burn": round(rng.uniform(0.0, 4.5), 2),
        }
        (d / "health.json").write_text(json.dumps(health, indent=2))

        # Per-environment configs
        for env in ENVS:
            cfg = {
                "service": svc,
                "env": env,
                "replicas": rng.randint(1, 30),
                "cpu_request": f"{rng.choice([250, 500, 750, 1000, 2000])}m",
                "memory_request": f"{rng.choice([256, 512, 768, 1024, 2048, 4096])}Mi",
                "log_level": rng.choice(["INFO", "INFO", "INFO", "DEBUG", "WARN"]),
                "timeout_ms": rng.choice([500, 1000, 1500, 2000, 5000]),
                "feature_flags": {
                    f"flag_{i}": rng.choice([True, False])
                    for i in range(rng.randint(2, 6))
                },
                "deployed_image": f"acmecorp/{svc}:{health['version']}",
                "last_change_at": (datetime.now() - timedelta(hours=rng.randint(1, 720))).isoformat(),
            }
            (d / f"config-{env}.json").write_text(json.dumps(cfg, indent=2))

        # Deploy log (last 5 events)
        deploy_log = []
        for i in range(rng.randint(3, 8)):
            deploy_log.append({
                "deployer": rng.choice(_team_members()),
                "env": rng.choice(ENVS),
                "version": f"{rng.randint(1, 6)}.{rng.randint(0, 18)}.{rng.randint(0, 199)}",
                "timestamp": (datetime.now() - timedelta(hours=rng.randint(1, 168))).isoformat(),
                "status": rng.choices(
                    ["SUCCESS", "FAILED", "ROLLED_BACK"],
                    weights=[80, 12, 8],
                    k=1,
                )[0],
            })
        (d / "deploy-log.json").write_text(json.dumps({"events": deploy_log}, indent=2))


def build_databases(base: Path, databases: list[str], rng: random.Random) -> None:
    db_root = base / "databases"
    for db in databases:
        d = db_root / db
        d.mkdir(parents=True, exist_ok=True)
        n_migs = rng.randint(10, 30)
        migrations = []
        for i in range(n_migs):
            migrations.append({
                "id": hashlib.md5(f"{db}-{i}".encode()).hexdigest()[:8],
                "version": f"V{i + 1}",
                "name": rng.choice([
                    "add_column", "create_index", "alter_table",
                    "add_foreign_key", "backfill_data", "split_table",
                    "drop_legacy_column", "compress_index", "add_partition",
                ]) + f"_{i}",
                "applied_at": (datetime.now() - timedelta(days=rng.randint(0, 180))).isoformat()
                              if rng.random() > 0.18 else None,
                "status": rng.choices(
                    ["APPLIED", "PENDING", "FAILED"],
                    weights=[80, 17, 3],
                    k=1,
                )[0],
                "checksum": hashlib.sha1(f"{db}{i}".encode()).hexdigest()[:16],
                "duration_ms": rng.randint(10, 60000),
            })
        pending = sum(1 for m in migrations if m["status"] == "PENDING")
        failed = sum(1 for m in migrations if m["status"] == "FAILED")
        payload = {
            "database": db,
            "total_migrations": n_migs,
            "pending_count": pending,
            "failed_count": failed,
            "last_applied_at": max(
                (m["applied_at"] for m in migrations if m["applied_at"]),
                default=None,
            ),
            "migrations": migrations,
        }
        (d / "flyway_status.json").write_text(json.dumps(payload, indent=2))


def build_pipelines(base: Path, pipelines: list[str], rng: random.Random) -> None:
    cicd = base / "cicd"
    cicd.mkdir(parents=True, exist_ok=True)
    for pipe in pipelines:
        status = rng.choices(
            ["PASSED", "FAILED", "RUNNING", "QUEUED"],
            weights=[60, 22, 12, 6],
            k=1,
        )[0]
        payload = {
            "pipeline": pipe,
            "status": status,
            "branch": rng.choice([
                "main", "main", "main",
                "release/v3", "release/v2",
                "hotfix/urgent", "hotfix/data-loss",
                "feature/checkout-v3", "feature/ml-rerank",
            ]),
            "trigger": rng.choice(["webhook", "schedule", "manual", "rerun"]),
            "last_run": (datetime.now() - timedelta(minutes=rng.randint(2, 1440))).isoformat(),
            "duration_seconds": rng.randint(30, 1800),
            "failed_stage": rng.choice([
                "build", "unit-tests", "lint", "integration", "deploy",
            ]) if status == "FAILED" else None,
            "triggered_by": rng.choice(_team_members()),
            "commit_sha": hashlib.sha1(pipe.encode() + str(rng.random()).encode()).hexdigest()[:10],
        }
        (cicd / f"{pipe}.json").write_text(json.dumps(payload, indent=2))


def build_containers(base: Path, services: list[str], rng: random.Random) -> None:
    infra = base / "infrastructure"
    infra.mkdir(parents=True, exist_ok=True)

    # 100 Docker containers across services × envs
    containers: list[dict] = []
    picked_pairs: set[tuple[str, str]] = set()
    while len(containers) < 100:
        svc = rng.choice(services)
        env = rng.choice(ENVS)
        if (svc, env) in picked_pairs:
            continue
        picked_pairs.add((svc, env))
        status = rng.choices(
            ["running", "exited", "crashed", "restarting"],
            weights=[72, 12, 8, 8],
            k=1,
        )[0]
        containers.append({
            "name": f"{svc}-{env}",
            "image": f"acmecorp/{svc}:{rng.randint(1, 6)}.{rng.randint(0, 18)}.{rng.randint(0, 199)}",
            "env": env,
            "status": status,
            "restart_count": rng.randint(0, 18) if status in {"crashed", "restarting"} else rng.randint(0, 4),
            "cpu_percent": round(rng.uniform(0.1, 92.0), 1),
            "memory_mb": round(rng.uniform(64, 8192), 1),
            "started_at": (datetime.now() - timedelta(hours=rng.randint(1, 720))).isoformat(),
        })
    payload = {
        "scan_time": datetime.now().isoformat(),
        "total": len(containers),
        "running": sum(1 for c in containers if c["status"] == "running"),
        "exited": sum(1 for c in containers if c["status"] == "exited"),
        "crashed": sum(1 for c in containers if c["status"] == "crashed"),
        "restarting": sum(1 for c in containers if c["status"] == "restarting"),
        "containers": containers,
    }
    (infra / "docker-ps.json").write_text(json.dumps(payload, indent=2))

    # 20 disk volumes
    volumes = []
    for mount in [
        "/data/postgres-primary", "/data/postgres-shard0", "/data/postgres-shard1",
        "/data/postgres-shard2", "/data/clickhouse", "/data/elasticsearch",
        "/data/elasticsearch-cold", "/data/cassandra", "/data/kafka",
        "/data/kafka-logs", "/data/redis", "/data/memcached",
        "/data/objectstore", "/data/objectstore-cold", "/data/logs-hot",
        "/data/logs-warm", "/data/logs-cold", "/var/lib/docker",
        "/var/lib/containerd", "/snapshots",
    ]:
        used = rng.randint(5, 950)
        total = rng.choice([200, 500, 1000, 2000, 4000])
        used = min(used, total - 1)
        volumes.append({
            "mount": mount,
            "used_gb": used,
            "total_gb": total,
            "usage_pct": round(used / total * 100, 1),
            "alert": (used / total) > 0.85,
        })
    (infra / "disk-usage.json").write_text(json.dumps({"volumes": volumes}, indent=2))

    # 200 K8s pods
    pods = []
    for _ in range(200):
        svc = rng.choice(services)
        env = rng.choice(ENVS)
        phase = rng.choices(
            ["Running", "Pending", "CrashLoopBackOff", "Error", "ImagePullBackOff"],
            weights=[78, 6, 8, 4, 4],
            k=1,
        )[0]
        pods.append({
            "name": f"{svc}-{env}-{hashlib.md5(str(rng.random()).encode()).hexdigest()[:6]}",
            "namespace": env,
            "phase": phase,
            "node": f"ip-10-{rng.randint(0, 255)}-{rng.randint(0, 255)}-{rng.randint(0, 255)}",
            "restarts": rng.randint(0, 25) if phase != "Running" else rng.randint(0, 3),
            "age_hours": round(rng.uniform(0.1, 720), 1),
            "container_image": f"acmecorp/{svc}:{rng.randint(1, 6)}.{rng.randint(0, 18)}.{rng.randint(0, 199)}",
        })
    (infra / "k8s-pods.json").write_text(json.dumps({"pods": pods}, indent=2))

    # 15 load balancers
    lbs = []
    for name in [
        "ingress-public-1", "ingress-public-2", "ingress-public-3",
        "ingress-internal-1", "ingress-internal-2",
        "egress-payments-1", "egress-payments-2",
        "lb-api-gateway", "lb-search-frontend", "lb-cdn-edge-1",
        "lb-cdn-edge-2", "lb-cdn-edge-3", "lb-grpc-fleet",
        "lb-websocket", "lb-admin",
    ]:
        active = rng.randint(2, 16)
        total = active + rng.randint(0, 6)
        healthy = active - rng.choices([0, 1, 2, 3], weights=[80, 12, 5, 3], k=1)[0]
        healthy = max(healthy, 0)
        lbs.append({
            "name": name,
            "scheme": "internet-facing" if "public" in name or "cdn" in name else "internal",
            "active_listeners": active,
            "total_targets": total,
            "healthy_targets": healthy,
            "unhealthy_targets": total - healthy,
            "p99_ms": round(rng.uniform(10, 480), 1),
            "tls_version": rng.choice(["TLSv1.2", "TLSv1.3", "TLSv1.3"]),
        })
    (infra / "load-balancers.json").write_text(json.dumps({"load_balancers": lbs}, indent=2))


def build_security(base: Path, services: list[str], rng: random.Random) -> None:
    sec = base / "security"
    sec.mkdir(parents=True, exist_ok=True)

    # Trivy 200+ CVE scan
    cves = []
    cve_packages = [
        "lodash", "requests", "django", "express", "log4j", "flask",
        "fastapi", "react", "vue", "axios", "spring-boot", "kubernetes-client",
        "openssl", "curl", "libxml2", "zlib", "protobuf", "grpc",
        "jackson-databind", "snakeyaml", "tomcat", "netty", "pyyaml",
        "urllib3", "cryptography", "pillow", "numpy", "pandas",
        "kafka-clients", "elastic-client", "redis", "psycopg2", "tornado",
    ]
    for _ in range(rng.randint(205, 260)):
        cves.append({
            "id": f"CVE-{rng.choice([2024, 2025, 2026])}-{rng.randint(1000, 99999)}",
            "package": rng.choice(cve_packages),
            "current_version": f"{rng.randint(0, 10)}.{rng.randint(0, 20)}.{rng.randint(0, 99)}",
            "fixed_version": f"{rng.randint(0, 10)}.{rng.randint(0, 20)}.{rng.randint(0, 99)}",
            "severity": rng.choices(
                ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                weights=[8, 25, 47, 20],
                k=1,
            )[0],
            "in_service": rng.choice(services),
            "first_seen": (datetime.now() - timedelta(days=rng.randint(0, 90))).isoformat(),
            "exploit_available": rng.choices([True, False], weights=[12, 88], k=1)[0],
        })
    cve_payload = {
        "scan_time": datetime.now().isoformat(),
        "total_vulnerabilities": len(cves),
        "critical": sum(1 for c in cves if c["severity"] == "CRITICAL"),
        "high": sum(1 for c in cves if c["severity"] == "HIGH"),
        "medium": sum(1 for c in cves if c["severity"] == "MEDIUM"),
        "low": sum(1 for c in cves if c["severity"] == "LOW"),
        "with_exploit": sum(1 for c in cves if c["exploit_available"]),
        "findings": cves,
    }
    (sec / "trivy-scan.json").write_text(json.dumps(cve_payload, indent=2))

    # SonarQube per-module
    modules = []
    for svc in services[:80]:
        modules.append({
            "module": svc,
            "quality_gate": rng.choice(["PASSED", "PASSED", "PASSED", "WARN", "FAILED"]),
            "bugs": rng.randint(0, 80),
            "vulnerabilities": rng.randint(0, 12),
            "code_smells": rng.randint(20, 600),
            "coverage_pct": round(rng.uniform(20, 95), 1),
            "duplicated_lines_pct": round(rng.uniform(0, 18), 1),
            "ncloc": rng.randint(800, 90000),
            "tech_debt_hours": round(rng.uniform(0.5, 240), 1),
        })
    sonar = {
        "project": "acmecorp-platform",
        "scan_time": datetime.now().isoformat(),
        "overall_quality_gate": "FAILED",
        "modules": modules,
        "totals": {
            "bugs": sum(m["bugs"] for m in modules),
            "vulnerabilities": sum(m["vulnerabilities"] for m in modules),
            "code_smells": sum(m["code_smells"] for m in modules),
            "ncloc": sum(m["ncloc"] for m in modules),
        },
    }
    (sec / "sonarqube.json").write_text(json.dumps(sonar, indent=2))

    # Snyk SBOM (linked from compliance, also referenced here)
    # Built fully in build_compliance — keep a thin pointer here.


def build_monitoring(base: Path, services: list[str], rng: random.Random) -> None:
    mon = base / "monitoring"
    mon.mkdir(parents=True, exist_ok=True)
    alerts = []
    severities = ["critical", "warning", "warning", "warning", "info", "info"]
    messages = [
        "High p99 latency (>500ms)",
        "Error rate spike (>5%)",
        "Memory usage >85%",
        "Connection pool exhausted",
        "Disk usage >90%",
        "SSL certificate expiring in 7 days",
        "Rate limit hit",
        "Dead letter queue backlog >1000",
        "Replica lag >30s",
        "OOM killed",
        "Pod restarts > threshold",
        "Cron job missed schedule",
        "Disk I/O saturation",
        "TCP retransmits elevated",
        "GC pause >2s",
    ]
    for _ in range(rng.randint(520, 620)):
        sev = rng.choice(severities)
        ack = rng.random() > 0.55 if sev == "critical" else rng.random() > 0.35
        # Force ~50+ critical unacknowledged
        alerts.append({
            "id": f"ALERT-{rng.randint(100000, 999999)}",
            "timestamp": (datetime.now() - timedelta(minutes=rng.randint(1, 1440))).isoformat(),
            "severity": sev,
            "service": rng.choice(services),
            "message": rng.choice(messages),
            "acknowledged": ack,
            "runbook": rng.choice([
                "https://wiki.acmecorp.com/rb/high-latency",
                "https://wiki.acmecorp.com/rb/error-rate",
                "https://wiki.acmecorp.com/rb/oom",
                None,
            ]),
        })
    # Top up criticals if too few
    crit_unack = [a for a in alerts if a["severity"] == "critical" and not a["acknowledged"]]
    if len(crit_unack) < 55:
        need = 55 - len(crit_unack)
        for _ in range(need):
            alerts.append({
                "id": f"ALERT-{rng.randint(100000, 999999)}",
                "timestamp": (datetime.now() - timedelta(minutes=rng.randint(1, 60))).isoformat(),
                "severity": "critical",
                "service": rng.choice(services),
                "message": rng.choice(messages),
                "acknowledged": False,
                "runbook": None,
            })
    payload = {
        "generated_at": datetime.now().isoformat(),
        "total_alerts": len(alerts),
        "by_severity": {
            "critical": sum(1 for a in alerts if a["severity"] == "critical"),
            "warning": sum(1 for a in alerts if a["severity"] == "warning"),
            "info": sum(1 for a in alerts if a["severity"] == "info"),
        },
        "unacknowledged": sum(1 for a in alerts if not a["acknowledged"]),
        "critical_unacknowledged": sum(
            1 for a in alerts if a["severity"] == "critical" and not a["acknowledged"]
        ),
        "alerts": alerts,
    }
    (mon / "prometheus-alerts.json").write_text(json.dumps(payload, indent=2))


def build_compliance(base: Path, services: list[str], rng: random.Random) -> None:
    comp = base / "compliance"
    comp.mkdir(parents=True, exist_ok=True)

    # SBOM 2000+ packages
    packages = []
    license_choices = [
        "MIT", "MIT", "MIT", "MIT", "Apache-2.0", "Apache-2.0",
        "BSD-3-Clause", "BSD-2-Clause", "ISC",
        "MPL-2.0", "LGPL-2.1", "LGPL-3.0",
        "GPL-2.0", "GPL-3.0", "AGPL-3.0",
        "UNLICENSED", "PROPRIETARY",
    ]
    namespaces = [
        "org.apache.", "com.google.", "io.github.", "@acme/",
        "io.netty.", "org.springframework.", "io.grpc.",
        "com.fasterxml.", "org.eclipse.", "@aws-sdk/",
        "@google-cloud/", "@azure/", "io.opentelemetry.",
    ]
    pkg_bases = [
        "core", "utils", "client", "common", "lib", "api",
        "auth", "config", "schema", "model", "internal", "runtime",
        "http", "grpc", "graphql", "json", "yaml", "xml",
        "logging", "metrics", "tracing", "cache", "queue",
        "kafka", "redis", "postgres", "elastic", "spanner",
    ]
    n_pkg = rng.randint(2050, 2400)
    for i in range(n_pkg):
        license_id = rng.choices(
            license_choices,
            weights=[7, 7, 7, 7, 9, 9, 5, 5, 4, 3, 2, 1, 1, 1, 1, 4, 4],
            k=1,
        )[0]
        risk = "HIGH" if license_id in {"AGPL-3.0", "GPL-3.0", "GPL-2.0", "PROPRIETARY"} else \
               "MEDIUM" if license_id in {"LGPL-2.1", "LGPL-3.0", "MPL-2.0", "UNLICENSED"} else \
               "LOW"
        packages.append({
            "id": f"pkg-{i:05d}",
            "name": f"{rng.choice(namespaces)}{rng.choice(pkg_bases)}-{rng.randint(0, 99)}",
            "version": f"{rng.randint(0, 12)}.{rng.randint(0, 30)}.{rng.randint(0, 99)}",
            "license": license_id,
            "risk": risk,
            "in_services": rng.sample(services, k=rng.randint(1, 5)),
            "data_residency_tier": rng.choice(["pii", "pii", "billing", "logs", "telemetry"]),
        })
    payload = {
        "generated_at": datetime.now().isoformat(),
        "total_packages": len(packages),
        "by_license": {},
        "high_risk": sum(1 for p in packages if p["risk"] == "HIGH"),
        "medium_risk": sum(1 for p in packages if p["risk"] == "MEDIUM"),
        "low_risk": sum(1 for p in packages if p["risk"] == "LOW"),
        "copyleft": sum(1 for p in packages if p["license"] in {"AGPL-3.0", "GPL-2.0", "GPL-3.0", "LGPL-2.1", "LGPL-3.0"}),
        "packages": packages,
    }
    by_lic: dict[str, int] = {}
    for p in packages:
        by_lic[p["license"]] = by_lic.get(p["license"], 0) + 1
    payload["by_license"] = by_lic
    (comp / "sbom.json").write_text(json.dumps(payload, indent=2))

    # GDPR data residency map
    residency = []
    regions = _gdpr_regions()
    for svc in services:
        residency.append({
            "service": svc,
            "primary_region": rng.choice(regions),
            "replicas": rng.sample(regions, k=rng.randint(1, 3)),
            "data_classes": rng.sample(
                ["pii", "pci", "phi", "billing", "logs", "telemetry", "analytics"],
                k=rng.randint(1, 3),
            ),
            "lawful_basis": rng.choice([
                "contract", "consent", "legitimate_interest", "legal_obligation",
            ]),
        })
    (comp / "gdpr-residency.json").write_text(json.dumps({"map": residency}, indent=2))


def build_drift(base: Path, services: list[str], rng: random.Random) -> None:
    drift_dir = base / "config-audit"
    drift_dir.mkdir(parents=True, exist_ok=True)
    drifts = []
    drifting = rng.sample(services, k=rng.randint(55, 75))
    parameters = [
        "log_level", "max_connections", "timeout_ms", "cache_ttl",
        "replicas", "cpu_request", "memory_request",
        "feature_flag_new_checkout", "feature_flag_ml_rerank",
        "feature_flag_strict_validation", "rate_limit_rps",
        "circuit_breaker_threshold", "retries_max",
    ]
    for svc in drifting:
        param = rng.choice(parameters)
        prod_val = str(rng.randint(1, 200))
        staging_val = str(rng.randint(1, 200))
        dev_val = str(rng.randint(1, 200))
        drifts.append({
            "service": svc,
            "parameter": param,
            "prod_value": prod_val,
            "staging_value": staging_val,
            "dev_value": dev_val,
            "first_detected": (datetime.now() - timedelta(hours=rng.randint(1, 168))).isoformat(),
            "severity": rng.choices(
                ["LOW", "MEDIUM", "HIGH"],
                weights=[55, 30, 15],
                k=1,
            )[0],
        })
    (drift_dir / "drift-report.json").write_text(json.dumps({
        "scan_time": datetime.now().isoformat(),
        "total_services": len(services),
        "services_with_drift": len(drifts),
        "drifts": drifts,
    }, indent=2))


def build_team(base: Path, services: list[str], rng: random.Random) -> None:
    team_dir = base / "team"
    team_dir.mkdir(parents=True, exist_ok=True)
    members = _team_members()
    deploys = []
    for _ in range(50):
        deploys.append({
            "deployer": rng.choice(members),
            "service": rng.choice(services),
            "environment": rng.choice(ENVS),
            "version": f"{rng.randint(1, 6)}.{rng.randint(0, 18)}.{rng.randint(0, 199)}",
            "timestamp": (datetime.now() - timedelta(hours=rng.randint(1, 168))).isoformat(),
            "status": rng.choices(
                ["SUCCESS", "FAILED", "ROLLED_BACK"],
                weights=[78, 14, 8],
                k=1,
            )[0],
            "duration_minutes": rng.randint(1, 35),
        })
    (team_dir / "recent-deploys.json").write_text(json.dumps({
        "window_days": 7,
        "team_size": len(members),
        "members": members,
        "deploys": deploys,
    }, indent=2))


# ---------------------------------------------------------------------------
# Scanner script generation
# ---------------------------------------------------------------------------

SCANNERS: dict[str, str] = {
    "scan-services-overview.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
svc_root = os.path.join(base, "services")
healthy = degraded = down = crashloop = 0
total = 0
tier_counts = {}
for svc in sorted(os.listdir(svc_root)):
    hp = os.path.join(svc_root, svc, "health.json")
    if not os.path.isfile(hp):
        continue
    h = json.load(open(hp))
    total += 1
    status = h["status"]
    if status == "healthy":
        healthy += 1
    elif status == "degraded":
        degraded += 1
    elif status == "down":
        down += 1
    elif status == "crashloop":
        crashloop += 1
    tier = h.get("tier", "tier-?")
    tier_counts[tier] = tier_counts.get(tier, 0) + 1
print(f"Total services: {total}")
print(f"  healthy:   {healthy}")
print(f"  degraded:  {degraded}")
print(f"  down:      {down}")
print(f"  crashloop: {crashloop}")
print()
print("By tier:")
for tier in sorted(tier_counts):
    print(f"  {tier}: {tier_counts[tier]}")
""",

    "scan-services-incidents.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
svc_root = os.path.join(base, "services")
broken = []
for svc in sorted(os.listdir(svc_root)):
    hp = os.path.join(svc_root, svc, "health.json")
    if not os.path.isfile(hp):
        continue
    h = json.load(open(hp))
    if h["status"] != "healthy":
        broken.append((h["status"], svc, h.get("owner_team", "?"), h.get("tier", "?"), h["version"]))
broken.sort(key=lambda r: ("crashloop", "down", "degraded").index(r[0]) if r[0] in ("crashloop", "down", "degraded") else 99)
print(f"Non-healthy services: {len(broken)}")
# Print first 60 incidents so tier-1 / crashloops are visible.
for status, svc, owner, tier, ver in broken[:60]:
    print(f"  {status.upper():9s} {tier:7s} {svc:38s} owner={owner:10s} v{ver}")
if len(broken) > 60:
    print(f"  ... +{len(broken) - 60} more")
""",

    "scan-services-error-budget.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
svc_root = os.path.join(base, "services")
burning = []
for svc in sorted(os.listdir(svc_root)):
    hp = os.path.join(svc_root, svc, "health.json")
    if not os.path.isfile(hp):
        continue
    h = json.load(open(hp))
    burn = h.get("error_budget_burn", 0.0)
    if burn >= 2.0:
        burning.append((burn, svc, h.get("tier", "?"), h.get("sli_p99_ms", 0)))
burning.sort(reverse=True)
print(f"Services burning error budget (>=2x): {len(burning)}")
for burn, svc, tier, p99 in burning[:20]:
    print(f"  burn={burn:4.2f}x  tier={tier:7s}  p99={p99:5.0f}ms  {svc}")
""",

    "scan-databases-overview.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
db_root = os.path.join(base, "databases")
total = 0
total_migs = 0
total_pending = 0
total_failed = 0
for db in sorted(os.listdir(db_root)):
    fp = os.path.join(db_root, db, "flyway_status.json")
    if not os.path.isfile(fp):
        continue
    d = json.load(open(fp))
    total += 1
    total_migs += d["total_migrations"]
    total_pending += d["pending_count"]
    total_failed += d["failed_count"]
print(f"Total databases: {total}")
print(f"Total migrations:  {total_migs}")
print(f"Pending:           {total_pending}")
print(f"Failed:            {total_failed}")
""",

    "scan-databases-pending.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
db_root = os.path.join(base, "databases")
rows = []
for db in sorted(os.listdir(db_root)):
    fp = os.path.join(db_root, db, "flyway_status.json")
    if not os.path.isfile(fp):
        continue
    d = json.load(open(fp))
    if d["pending_count"] > 0 or d["failed_count"] > 0:
        rows.append((d["failed_count"], d["pending_count"], db, d["total_migrations"]))
rows.sort(reverse=True)
print(f"Databases needing attention: {len(rows)}")
for failed, pending, db, total in rows:
    print(f"  {db:38s}  total={total:3d}  pending={pending:2d}  failed={failed}")
""",

    "scan-cicd-overview.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
cicd = os.path.join(base, "cicd")
counts = {}
for f in sorted(os.listdir(cicd)):
    if not f.endswith(".json"):
        continue
    p = json.load(open(os.path.join(cicd, f)))
    counts[p["status"]] = counts.get(p["status"], 0) + 1
print("Pipeline summary:")
for status in ("PASSED", "FAILED", "RUNNING", "QUEUED"):
    print(f"  {status}: {counts.get(status, 0)}")
""",

    "scan-cicd-failures.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
cicd = os.path.join(base, "cicd")
fails = []
for f in sorted(os.listdir(cicd)):
    if not f.endswith(".json"):
        continue
    p = json.load(open(os.path.join(cicd, f)))
    if p["status"] == "FAILED":
        fails.append(p)
fails.sort(key=lambda p: p.get("last_run", ""), reverse=True)
print(f"Failed pipelines: {len(fails)}")
for p in fails:
    print(f"  {p['pipeline']:30s} branch={p['branch']:25s} stage={p.get('failed_stage', '?'):16s} sha={p['commit_sha']}")
""",

    "scan-docker-overview.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "infrastructure", "docker-ps.json")))
print(f"Containers: {d['running']}/{d['total']} running  "
      f"(exited={d['exited']}, crashed={d['crashed']}, restarting={d['restarting']})")
""",

    "scan-docker-failures.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "infrastructure", "docker-ps.json")))
bad = [c for c in d["containers"] if c["status"] != "running"]
bad.sort(key=lambda c: ("crashed", "exited", "restarting").index(c["status"]) if c["status"] in ("crashed", "exited", "restarting") else 9)
print(f"Non-running containers: {len(bad)}")
for c in bad:
    print(f"  {c['status']:11s} {c['name']:48s} restarts={c['restart_count']:2d}  image={c['image']}")
""",

    "scan-k8s-pods.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "infrastructure", "k8s-pods.json")))
counts = {}
for p in d["pods"]:
    counts[p["phase"]] = counts.get(p["phase"], 0) + 1
print(f"K8s pods: {len(d['pods'])} total")
for phase in sorted(counts):
    print(f"  {phase}: {counts[phase]}")
bad = [p for p in d["pods"] if p["phase"] != "Running"]
bad.sort(key=lambda p: p["restarts"], reverse=True)
print(f"\nNon-Running pods (top 40 by restarts):")
for p in bad[:40]:
    print(f"  {p['phase']:18s} {p['name']:55s} ns={p['namespace']:7s} restarts={p['restarts']:2d}")
""",

    "scan-load-balancers.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "infrastructure", "load-balancers.json")))
print(f"Load balancers: {len(d['load_balancers'])}")
deg = []
for lb in d["load_balancers"]:
    if lb["unhealthy_targets"] > 0 or lb["p99_ms"] > 250:
        deg.append(lb)
print(f"  with unhealthy targets or p99>250ms: {len(deg)}")
for lb in deg:
    print(f"  {lb['name']:24s} scheme={lb['scheme']:16s} healthy={lb['healthy_targets']}/{lb['total_targets']} p99={lb['p99_ms']}ms tls={lb['tls_version']}")
""",

    "scan-disk.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "infrastructure", "disk-usage.json")))
warn = [v for v in d["volumes"] if v["alert"]]
print(f"Disk volumes: {len(d['volumes'])} total, {len(warn)} over 85% usage")
for v in sorted(d["volumes"], key=lambda v: -v["usage_pct"])[:15]:
    flag = " 🚨" if v["alert"] else ""
    print(f"  {v['mount']:34s} {v['used_gb']:4d}/{v['total_gb']:4d}GB ({v['usage_pct']:5.1f}%){flag}")
""",

    "scan-security-cves.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "security", "trivy-scan.json")))
print(f"Trivy CVE scan: {d['total_vulnerabilities']} total")
print(f"  CRITICAL: {d['critical']}")
print(f"  HIGH:     {d['high']}")
print(f"  MEDIUM:   {d['medium']}")
print(f"  LOW:      {d['low']}")
print(f"  with public exploit: {d['with_exploit']}")
""",

    "scan-security-criticals.py": r"""
import json, os
from collections import Counter
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "security", "trivy-scan.json")))
crit = [c for c in d["findings"] if c["severity"] == "CRITICAL"]
exploitable = [c for c in crit if c["exploit_available"]]
by_pkg = Counter(c["package"] for c in crit)
by_svc = Counter(c["in_service"] for c in crit)
print(f"CRITICAL CVEs: {len(crit)} ({len(exploitable)} with exploit available)")
print("Top packages:")
for pkg, n in by_pkg.most_common(15):
    print(f"  {pkg:24s} {n}")
print("Top affected services:")
for svc, n in by_svc.most_common(15):
    print(f"  {svc:38s} {n}")
print("Exploitable CRITICAL findings (first 15):")
for c in exploitable[:15]:
    print(f"  {c['id']:18s} {c['package']:18s} svc={c['in_service']:38s} fix={c['fixed_version']}")
""",

    "scan-sonarqube.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "security", "sonarqube.json")))
modules = d["modules"]
print(f"SonarQube: overall {d['overall_quality_gate']}")
print(f"  modules scanned: {len(modules)}")
print(f"  totals: bugs={d['totals']['bugs']} vulns={d['totals']['vulnerabilities']} "
      f"smells={d['totals']['code_smells']} ncloc={d['totals']['ncloc']}")
failed = [m for m in modules if m["quality_gate"] == "FAILED"]
print(f"  modules failing quality gate: {len(failed)}")
for m in sorted(failed, key=lambda m: -m["vulnerabilities"])[:8]:
    print(f"    {m['module']:38s} bugs={m['bugs']:3d} vulns={m['vulnerabilities']:2d} cov={m['coverage_pct']:.0f}%")
""",

    "scan-alerts-overview.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "monitoring", "prometheus-alerts.json")))
print(f"Prometheus: {d['total_alerts']} alerts")
print(f"  by severity: critical={d['by_severity']['critical']} "
      f"warning={d['by_severity']['warning']} info={d['by_severity']['info']}")
print(f"  unacknowledged: {d['unacknowledged']}")
print(f"  CRITICAL unacknowledged: {d['critical_unacknowledged']}")
""",

    "scan-alerts-critical.py": r"""
import json, os
from collections import Counter
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "monitoring", "prometheus-alerts.json")))
crit = [a for a in d["alerts"] if a["severity"] == "critical" and not a["acknowledged"]]
by_msg = Counter(a["message"] for a in crit)
by_svc = Counter(a["service"] for a in crit)
print(f"Unacknowledged CRITICAL alerts: {len(crit)}")
print("Top alert messages:")
for msg, n in by_msg.most_common(12):
    print(f"  {n:3d}x  {msg}")
print("Top affected services:")
for svc, n in by_svc.most_common(15):
    print(f"  {n:3d}x  {svc}")
""",

    "scan-sbom-overview.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "compliance", "sbom.json")))
print(f"SBOM: {d['total_packages']} packages")
print(f"  HIGH risk:   {d['high_risk']}")
print(f"  MEDIUM risk: {d['medium_risk']}")
print(f"  LOW risk:    {d['low_risk']}")
print(f"  copyleft:    {d['copyleft']}")
""",

    "scan-sbom-licenses.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "compliance", "sbom.json")))
print("License distribution:")
for lic, n in sorted(d["by_license"].items(), key=lambda kv: -kv[1]):
    print(f"  {lic:18s} {n:5d}")
""",

    "scan-gdpr-residency.py": r"""
import json, os
from collections import Counter
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "compliance", "gdpr-residency.json")))
m = d["map"]
by_region = Counter(r["primary_region"] for r in m)
data_class = Counter(c for r in m for c in r["data_classes"])
print(f"GDPR residency entries: {len(m)}")
print("Primary regions (top 8):")
for region, n in by_region.most_common(8):
    print(f"  {region:16s} {n}")
print("Data classes in scope:")
for cls, n in data_class.most_common():
    print(f"  {cls:12s} {n}")
""",

    "scan-drift-overview.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "config-audit", "drift-report.json")))
print(f"Config drift: {d['services_with_drift']}/{d['total_services']} services have divergence")
by_sev = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
for dr in d["drifts"]:
    by_sev[dr["severity"]] = by_sev.get(dr["severity"], 0) + 1
for s in ("HIGH", "MEDIUM", "LOW"):
    print(f"  {s}: {by_sev.get(s, 0)}")
""",

    "scan-drift-detail.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "config-audit", "drift-report.json")))
high = [dr for dr in d["drifts"] if dr["severity"] == "HIGH"]
medium = [dr for dr in d["drifts"] if dr["severity"] == "MEDIUM"]
low = [dr for dr in d["drifts"] if dr["severity"] == "LOW"]
print(f"HIGH-severity drift ({len(high)}):")
for dr in high:
    print(f"  {dr['service']:38s} {dr['parameter']:30s} prod={dr['prod_value']:>5s} | staging={dr['staging_value']:>5s} | dev={dr['dev_value']:>5s}")
print(f"\nMEDIUM-severity drift ({len(medium)}):")
for dr in medium:
    print(f"  {dr['service']:38s} {dr['parameter']:30s} prod={dr['prod_value']:>5s} | staging={dr['staging_value']:>5s} | dev={dr['dev_value']:>5s}")
print(f"\nLOW-severity drift sample ({min(len(low), 12)} of {len(low)}):")
for dr in low[:12]:
    print(f"  {dr['service']:38s} {dr['parameter']:30s} prod={dr['prod_value']:>5s} | staging={dr['staging_value']:>5s} | dev={dr['dev_value']:>5s}")
""",

    "scan-team-overview.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "team", "recent-deploys.json")))
print(f"Team deploy activity ({d['window_days']}-day window):")
print(f"  total deploys: {len(d['deploys'])}")
print(f"  team size: {d['team_size']}")
status_counts = {}
env_counts = {}
for dep in d["deploys"]:
    status_counts[dep["status"]] = status_counts.get(dep["status"], 0) + 1
    env_counts[dep["environment"]] = env_counts.get(dep["environment"], 0) + 1
print(f"  status: SUCCESS={status_counts.get('SUCCESS',0)} FAILED={status_counts.get('FAILED',0)} ROLLED_BACK={status_counts.get('ROLLED_BACK',0)}")
print(f"  by env: prod={env_counts.get('prod',0)} staging={env_counts.get('staging',0)} dev={env_counts.get('dev',0)}")
""",

    "scan-team-failures.py": r"""
import json, os
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "team", "recent-deploys.json")))
bad = [dep for dep in d["deploys"] if dep["status"] in ("FAILED", "ROLLED_BACK")]
print(f"Failed/rolled-back deploys: {len(bad)}")
for dep in sorted(bad, key=lambda x: x["timestamp"], reverse=True)[:18]:
    print(f"  {dep['status']:12s} {dep['deployer']:8s} -> {dep['service']:38s} {dep['environment']:7s} v{dep['version']}")
""",

    "scan-deploys-by-env.py": r"""
import json, os
from collections import Counter
base = os.environ["MEGA_BASE"]
d = json.load(open(os.path.join(base, "team", "recent-deploys.json")))
by_env_status = Counter()
for dep in d["deploys"]:
    by_env_status[(dep["environment"], dep["status"])] += 1
print("Deploys by env × status:")
for env in ("prod", "staging", "dev"):
    s = by_env_status[(env, "SUCCESS")]
    f = by_env_status[(env, "FAILED")]
    r = by_env_status[(env, "ROLLED_BACK")]
    print(f"  {env:8s}  SUCCESS={s:3d}  FAILED={f:3d}  ROLLED_BACK={r:3d}")
""",
}


def write_scanners(base: Path) -> list[str]:
    scripts_dir = base / ".perseus" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    base_literal = base.as_posix()
    names = []
    for name, body in SCANNERS.items():
        # Hard-code MEGA_BASE inside each script (instead of relying on env
        # vars) so they work under both bash and cmd.exe. Add UTF-8 stdout
        # reconfig so emoji / non-ASCII characters survive on Windows.
        prelude = (
            "import os, sys\n"
            "try:\n"
            "    sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
            "except Exception:\n"
            "    pass\n"
            f"os.environ.setdefault('MEGA_BASE', {base_literal!r})\n"
        )
        full = prelude + body.lstrip() + "\n"
        (scripts_dir / name).write_text(full, encoding="utf-8")
        names.append(name)
    return names


def write_context(base: Path, scanner_names: list[str]) -> None:
    """Write a .perseus/context.md that calls every scanner via @query."""
    perseus_dir = base / ".perseus"
    perseus_dir.mkdir(parents=True, exist_ok=True)
    # Config — allow shell execution; longer timeout
    # On Windows we let the default cmd.exe shell handle invocation.
    # Embedding render.shell with a Windows path-with-spaces gets mangled
    # by subprocess.run on Windows (executable= kwarg + shell=True).
    if os.name == "nt":
        (perseus_dir / "config.yaml").write_text(
            "render:\n"
            "  allow_query_shell: true\n"
            "  allow_services_command: false\n",
            encoding="utf-8",
        )
    else:
        (perseus_dir / "config.yaml").write_text(
            "render:\n"
            "  allow_query_shell: true\n"
            "  allow_services_command: false\n"
            "  shell: /bin/bash\n",
            encoding="utf-8",
        )
    # Map scanner script name -> human-friendly section title
    titles = {
        "scan-services-overview.py":     "1. Service Health Overview (500 services)",
        "scan-services-incidents.py":    "2. Service Incidents — Non-Healthy",
        "scan-services-error-budget.py": "3. Services Burning Error Budget",
        "scan-databases-overview.py":    "4. Database Migration Overview (50 DBs)",
        "scan-databases-pending.py":     "5. Databases Needing Attention",
        "scan-cicd-overview.py":         "6. CI/CD Pipeline Overview (30 pipelines)",
        "scan-cicd-failures.py":         "7. Pipeline Failures",
        "scan-docker-overview.py":       "8. Docker Container Overview",
        "scan-docker-failures.py":       "9. Non-Running Containers",
        "scan-k8s-pods.py":              "10. K8s Pod Status (200 pods)",
        "scan-load-balancers.py":        "11. Load Balancer Health (15 LBs)",
        "scan-disk.py":                  "12. Disk Usage (20 volumes)",
        "scan-security-cves.py":         "13. Trivy CVE Scan",
        "scan-security-criticals.py":    "14. Critical CVEs by Service",
        "scan-sonarqube.py":             "15. SonarQube Quality (module-level)",
        "scan-alerts-overview.py":       "16. Prometheus Alerts Overview",
        "scan-alerts-critical.py":       "17. Unacknowledged CRITICAL Alerts",
        "scan-sbom-overview.py":         "18. SBOM Overview (2k+ packages)",
        "scan-sbom-licenses.py":         "19. License Distribution",
        "scan-gdpr-residency.py":        "20. GDPR Data Residency Map",
        "scan-drift-overview.py":        "21. Config Drift Overview",
        "scan-drift-detail.py":          "22. Config Drift Detail (with values)",
        "scan-team-overview.py":         "23. Team Deploy Activity (7d)",
        "scan-team-failures.py":         "24. Failed / Rolled-Back Deploys",
        "scan-deploys-by-env.py":        "25. Deploys by Environment",
    }
    # Build directives
    lines = [
        "@perseus v0.8",
        "",
        "@prompt",
        "This document was rendered live by Perseus from a 500-service synthetic enterprise.",
        "All facts below are pre-resolved at render time. Do NOT spawn discovery calls",
        "to verify services, databases, pipelines, containers, alerts, scans, drift,",
        "or compliance state — those facts are already in this context.",
        "@end",
        "",
        "# AcmeCorp Mega-Platform — Live SRE Snapshot",
        "",
        "**Generated:** @date format=\"YYYY-MM-DD HH:mm UTC\"",
        f"**Workspace:** `{base}`",
        "**Scale:** 500 services · 50 databases · 30 pipelines · 100 Docker containers · 200 K8s pods · 15 load balancers · 20 volumes · 200+ CVEs · 2k+ packages · 500+ alerts",
        "",
        "---",
        "",
    ]
    for name in scanner_names:
        title = titles.get(name, name)
        lines.append(f"## {title}")
        # Use bash-friendly invocation; rely on MEGA_BASE env var set by perseus shell
        # The scanner reads MEGA_BASE from the environment.
        # No quoting on the script path — it's space-free by construction.
        # python -X utf8 makes emoji survive on Windows cmd.exe.
        script_path = (base / ".perseus" / "scripts" / name).as_posix()
        cmd = f"python -X utf8 {script_path}"
        lines.append(f'@query "{cmd}"')
        lines.append("")
    # Add a few non-@query directives at the end
    lines.extend([
        "---",
        "",
        "## 26. Available Skills",
        "@skills flag_stale=true",
        "",
        "## 27. Recent Sessions",
        "@session count=5",
        "",
        "## 28. Maintenance Snapshot",
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
    print(f"Building mega-enterprise benchmark at {base} ...")
    rng = random.Random(20260523)

    services = _service_names(500)
    databases = _database_names(50)
    pipelines = _pipeline_names(30)

    print(f"  [1/9] Services: {len(services)}")
    build_services(base, services, rng)
    print(f"  [2/9] Databases: {len(databases)}")
    build_databases(base, databases, rng)
    print(f"  [3/9] Pipelines: {len(pipelines)}")
    build_pipelines(base, pipelines, rng)
    print(f"  [4/9] Containers + K8s + LBs + disk")
    build_containers(base, services, rng)
    print(f"  [5/9] Security scans (Trivy, SonarQube)")
    build_security(base, services, rng)
    print(f"  [6/9] Monitoring alerts")
    build_monitoring(base, services, rng)
    print(f"  [7/9] Compliance (SBOM + GDPR residency)")
    build_compliance(base, services, rng)
    print(f"  [8/9] Config drift")
    build_drift(base, services, rng)
    print(f"  [9/9] Team activity + Perseus context + scanners")
    build_team(base, services, rng)
    names = write_scanners(base)
    write_context(base, names)

    # Tally
    n_files = sum(1 for _ in base.rglob("*") if _.is_file())
    print()
    print(f"  Done. ~{n_files} files generated.")
    print()
    print(f"  Render:")
    print(f"    cd {base}")
    print(f"    python -m perseus render .perseus/context.md --output .hermes.md")
    print(f"  (or use absolute path to perseus.py if not installed)")


if __name__ == "__main__":
    main()
