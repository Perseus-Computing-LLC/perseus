#!/usr/bin/env python3
"""Enterprise benchmark environment setup for Perseus cold-start testing.

Creates a synthetic 12-microservice platform with CI/CD, databases, security
scans, monitoring, config drift, and team activity — 366 files across 17
discovery surfaces — to demonstrate Perseus's scaling power.

Usage:
    python3 setup.py                  # creates /tmp/enterprise-benchmark
    cd /tmp/enterprise-benchmark
    python3 perseus.py render .perseus/context.md --output .hermes.md
    wc -l .hermes.md                  # ~300 lines of pre-resolved context
"""

import json
import os
import random
import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path("/tmp/enterprise-benchmark")
SERVICES = [
    "user-service", "payment-service", "inventory-service", "notification-service",
    "api-gateway", "auth-service", "analytics-service", "search-service",
    "reporting-service", "webhooks-service", "file-service", "rate-limiter",
]
ENVS = ["prod", "staging", "dev"]
DATABASES = ["users-db", "orders-db", "inventory-db", "analytics-db"]
PIPELINES = [
    "deploy-prod", "deploy-staging", "canary-release",
    "security-scan", "integration-tests", "e2e-smoke-tests",
]
TEAM = ["alice", "bob", "carol", "dave", "eve", "frank", "grace"]
DOMAINS = [
    "api.acmecorp.com", "admin.acmecorp.com", "cdn.acmecorp.com",
    "status.acmecorp.com", "monitoring.acmecorp.com",
    "auth.acmecorp.com", "payments.acmecorp.com",
]


def main():
    print("Building AcmeCorp enterprise benchmark environment...")
    os.makedirs(BASE, exist_ok=True)

    # 1. Clone Perseus repo as one of the platform repos
    print("  [1/13] Cloning Perseus repo...")
    perseus_dir = BASE / "repos" / "perseus"
    if not perseus_dir.exists():
        os.system(
            f"git clone --quiet https://github.com/tcconnally/perseus.git {perseus_dir} 2>&1 | tail -1"
        )

    # 2. Microservices
    print(f"  [2/13] Creating {len(SERVICES)} microservices...")
    for svc in SERVICES:
        d = BASE / "services" / svc
        os.makedirs(d, exist_ok=True)
        health = {
            "status": random.choice(["healthy", "healthy", "healthy", "degraded"]),
            "version": f"2.{random.randint(1,9)}.{random.randint(0,99)}",
            "uptime_hours": round(random.uniform(1, 720), 1),
            "last_deploy": (datetime.now() - timedelta(hours=random.randint(1, 168))).isoformat(),
        }
        with open(d / "health.json", "w") as f:
            json.dump(health, f, indent=2)

    # 3. CI/CD pipelines
    print(f"  [3/13] Creating {len(PIPELINES)} CI/CD pipelines...")
    os.makedirs(BASE / "cicd", exist_ok=True)
    for pipe in PIPELINES:
        status = random.choice(["PASSED", "PASSED", "PASSED", "PASSED", "FAILED"])
        with open(BASE / "cicd" / f"{pipe}.json", "w") as f:
            json.dump(
                {
                    "pipeline": pipe,
                    "last_run": (datetime.now() - timedelta(minutes=random.randint(5, 1440))).isoformat(),
                    "status": status,
                    "duration_seconds": random.randint(30, 900),
                    "branch": random.choice(["main", "release/v2", "hotfix/urgent"]),
                    "triggered_by": random.choice(["webhook", "schedule", "manual"]),
                },
                f,
                indent=2,
            )

    # 4. Database migrations
    print(f"  [4/13] Creating {len(DATABASES)} database migration states...")
    for db in DATABASES:
        d = BASE / "databases" / db
        os.makedirs(d, exist_ok=True)
        migrations = []
        for i in range(random.randint(15, 25)):
            migrations.append(
                {
                    "id": hashlib.md5(f"{db}{i}".encode()).hexdigest()[:8],
                    "name": f"V{i+1}__{random.choice(['add_column','create_index','alter_table','add_foreign_key','backfill_data'])}",
                    "applied_at": (datetime.now() - timedelta(days=random.randint(0, 90))).isoformat(),
                    "status": random.choice(["APPLIED", "APPLIED", "APPLIED", "APPLIED", "PENDING"]),
                }
            )
        with open(d / "flyway_status.json", "w") as f:
            json.dump(
                {
                    "database": db,
                    "migrations": migrations,
                    "pending_count": sum(1 for m in migrations if m["status"] == "PENDING"),
                },
                f,
                indent=2,
            )

    # 5. Security scans
    print("  [5/13] Generating security scan results...")
    os.makedirs(BASE / "security", exist_ok=True)
    vulns = []
    for i in range(random.randint(15, 30)):
        vulns.append(
            {
                "id": f"CVE-2026-{random.randint(1000,99999)}",
                "package": random.choice(
                    ["lodash", "requests", "django", "express", "log4j", "flask",
                     "fastapi", "react", "vue", "axios", "spring-boot", "kubernetes-client"]
                ),
                "severity": random.choice(
                    ["CRITICAL", "CRITICAL", "HIGH", "HIGH", "HIGH", "MEDIUM", "MEDIUM", "MEDIUM", "MEDIUM", "LOW", "LOW"]
                ),
                "fixed_version": f"{random.randint(1,10)}.{random.randint(0,9)}.{random.randint(0,99)}",
                "in_service": random.choice(SERVICES),
            }
        )
    with open(BASE / "security" / "trivy-scan.json", "w") as f:
        json.dump(
            {
                "scan_time": datetime.now().isoformat(),
                "total_vulnerabilities": len(vulns),
                "critical": sum(1 for v in vulns if v["severity"] == "CRITICAL"),
                "high": sum(1 for v in vulns if v["severity"] == "HIGH"),
                "findings": vulns,
            },
            f,
            indent=2,
        )
    with open(BASE / "security" / "sonarqube.json", "w") as f:
        json.dump(
            {
                "project": "acme-platform",
                "quality_gate": "FAILED",
                "bugs": random.randint(20, 100),
                "vulnerabilities": random.randint(2, 15),
                "code_smells": random.randint(100, 500),
                "coverage": f"{random.randint(45,85)}%",
                "duplicated_lines": f"{random.randint(3,15)}%",
            },
            f,
            indent=2,
        )

    # 6. Monitoring alerts
    print("  [6/13] Generating monitoring alerts...")
    os.makedirs(BASE / "monitoring", exist_ok=True)
    alerts = []
    for i in range(random.randint(25, 40)):
        svc = random.choice(SERVICES)
        alerts.append(
            {
                "id": f"ALERT-{random.randint(10000,99999)}",
                "timestamp": (datetime.now() - timedelta(minutes=random.randint(1, 1440))).isoformat(),
                "severity": random.choice(["critical", "critical", "warning", "warning", "warning", "info", "info", "info"]),
                "service": svc,
                "message": random.choice(
                    [
                        f"High latency in {svc} (>500ms p99)",
                        f"Error rate spike in {svc} (5.2%)",
                        f"Memory usage >85% on {svc}",
                        f"Connection pool exhausted for {svc}",
                        f"Disk usage >90% on {svc} host",
                        "SSL certificate expiring in 7 days",
                        f"Rate limit hit for {svc} endpoint",
                        "Dead letter queue backlog >1000",
                    ]
                ),
                "acknowledged": random.choice([True, False, False]),
            }
        )
    with open(BASE / "monitoring" / "prometheus-alerts.json", "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(),
                "total_alerts": len(alerts),
                "unacknowledged": sum(1 for a in alerts if not a["acknowledged"]),
                "alerts": alerts,
            },
            f,
            indent=2,
        )

    # 7. Docker infrastructure
    print("  [7/13] Generating Docker container state...")
    os.makedirs(BASE / "infrastructure", exist_ok=True)
    containers = []
    for svc in SERVICES:
        for env in ENVS[:2]:
            containers.append(
                {
                    "name": f"{svc}-{env}",
                    "image": f"acmecorp/{svc}:2.{random.randint(1,5)}.{random.randint(0,99)}",
                    "status": random.choice(["running", "running", "running", "running", "running", "exited"]),
                    "cpu_percent": round(random.uniform(0.5, 85.0), 1),
                    "memory_mb": round(random.uniform(50, 2048), 1),
                    "restart_count": random.randint(0, 5),
                }
            )
    with open(BASE / "infrastructure" / "docker-ps.json", "w") as f:
        json.dump(
            {
                "containers": containers,
                "total": len(containers),
                "running": sum(1 for c in containers if c["status"] == "running"),
                "exited": sum(1 for c in containers if c["status"] == "exited"),
            },
            f,
            indent=2,
        )
    with open(BASE / "infrastructure" / "disk-usage.json", "w") as f:
        json.dump(
            {
                "volumes": [
                    {"mount": "/data/postgres", "used_gb": random.randint(20, 200), "total_gb": 500,
                     "usage_pct": random.randint(10, 85)},
                    {"mount": "/data/elasticsearch", "used_gb": random.randint(50, 300), "total_gb": 500,
                     "usage_pct": random.randint(30, 90)},
                    {"mount": "/data/logs", "used_gb": random.randint(100, 400), "total_gb": 1000,
                     "usage_pct": random.randint(40, 95)},
                    {"mount": "/var/lib/docker", "used_gb": random.randint(30, 150), "total_gb": 200,
                     "usage_pct": random.randint(30, 80)},
                ]
            },
            f,
            indent=2,
        )

    # 8. Config drift
    print("  [8/13] Generating config drift report...")
    os.makedirs(BASE / "config-audit", exist_ok=True)
    drifts = []
    for svc in random.sample(SERVICES, 6):
        drifts.append(
            {
                "service": svc,
                "parameter": random.choice(
                    ["log_level", "max_connections", "timeout_ms", "cache_ttl",
                     "replicas", "resource_limits", "feature_flag_enable_new_checkout"]
                ),
                "prod_value": str(random.randint(1, 100)),
                "staging_value": str(random.randint(1, 100)),
                "drift_detected": True,
            }
        )
    with open(BASE / "config-audit" / "drift-report.json", "w") as f:
        json.dump(
            {
                "scan_time": datetime.now().isoformat(),
                "total_services": len(SERVICES),
                "services_with_drift": len(drifts),
                "drifts": drifts,
            },
            f,
            indent=2,
        )

    # 9. Backups
    print("  [9/13] Generating backup status...")
    os.makedirs(BASE / "backups", exist_ok=True)
    backups = []
    for db in DATABASES:
        backups.append(
            {
                "database": db,
                "last_backup": (datetime.now() - timedelta(hours=random.randint(1, 72))).isoformat(),
                "size_gb": round(random.uniform(0.5, 50), 1),
                "status": random.choice(["COMPLETED", "COMPLETED", "COMPLETED", "COMPLETED", "FAILED"]),
                "retention_days": 30,
            }
        )
    with open(BASE / "backups" / "status.json", "w") as f:
        json.dump({"backups": backups}, f, indent=2)

    # 10. SSL certificates
    print("  [10/13] Generating SSL certificate state...")
    os.makedirs(BASE / "ssl", exist_ok=True)
    certs = []
    for dom in DOMAINS:
        days_left = random.randint(5, 365)
        certs.append(
            {
                "domain": dom,
                "expires_at": (datetime.now() + timedelta(days=days_left)).isoformat(),
                "days_remaining": days_left,
                "issuer": "LetsEncrypt",
                "warning": days_left < 30,
            }
        )
    with open(BASE / "ssl" / "certificates.json", "w") as f:
        json.dump(
            {"certificates": certs, "expiring_soon": sum(1 for c in certs if c["warning"])},
            f,
            indent=2,
        )

    # 11. License compliance
    print("  [11/13] Generating license compliance SBOM...")
    os.makedirs(BASE / "compliance", exist_ok=True)
    licenses = []
    for i in range(random.randint(50, 80)):
        licenses.append(
            {
                "package": f"{random.choice(['@acme/','org.apache.','com.google.','io.github.'])}{random.choice(['utils','core','client','common','lib','api'])}-{random.choice(['java','py','js','go'])}",
                "version": f"{random.randint(0,10)}.{random.randint(0,20)}.{random.randint(0,99)}",
                "license": random.choice(["MIT", "Apache-2.0", "GPL-3.0", "BSD-3-Clause", "LGPL-2.1", "MPL-2.0", "UNLICENSED", "PROPRIETARY"]),
                "risk": random.choice(["LOW", "LOW", "LOW", "MEDIUM", "MEDIUM", "HIGH"]),
            }
        )
    with open(BASE / "compliance" / "sbom-licenses.json", "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(),
                "total_packages": len(licenses),
                "high_risk": sum(1 for l in licenses if l["risk"] == "HIGH"),
                "copyleft": sum(1 for l in licenses if l["license"] in ("GPL-3.0", "AGPL-3.0", "LGPL-2.1")),
                "packages": licenses,
            },
            f,
            indent=2,
        )

    # 12. Team activity
    print("  [12/13] Generating team deploy activity...")
    os.makedirs(BASE / "team", exist_ok=True)
    deploys = []
    for i in range(random.randint(15, 30)):
        deploys.append(
            {
                "deployer": random.choice(TEAM),
                "service": random.choice(SERVICES),
                "environment": random.choice(ENVS),
                "version": f"{random.randint(1,5)}.{random.randint(0,9)}.{random.randint(0,99)}",
                "timestamp": (datetime.now() - timedelta(hours=random.randint(1, 168))).isoformat(),
                "status": random.choice(["SUCCESS", "SUCCESS", "SUCCESS", "SUCCESS", "FAILED", "ROLLED_BACK"]),
            }
        )
    with open(BASE / "team" / "recent-deploys.json", "w") as f:
        json.dump({"deploys": deploys}, f, indent=2)

    # 13. Perseus config for rendering
    print("  [13/13] Writing Perseus config...")
    os.makedirs(BASE / ".perseus", exist_ok=True)
    with open(BASE / ".perseus" / "config.yaml", "w") as f:
        f.write("allow_services_command: true\nquery:\n  timeout: 30\n")

    # Write scanner scripts
    scripts_dir = BASE / ".perseus" / "scripts"
    os.makedirs(scripts_dir, exist_ok=True)

    scanners = {
        "scan-services.py": f"""import json, os
base='{BASE}/services'
for svc in sorted(os.listdir(base)):
    hp = os.path.join(base, svc, 'health.json')
    if os.path.exists(hp):
        h = json.load(open(hp))
        print(f'{{svc}}: {{h["status"]}} v{{h["version"]}} (uptime: {{h["uptime_hours"]}}h)')
""",
        "scan-cicd.py": f"""import json, os
for f in sorted(os.listdir('{BASE}/cicd')):
    if f.endswith('.json'):
        p = json.load(open(f'{{BASE}}/cicd/{{f}}'))
        print(f'{{p["pipeline"]}}: {{p["status"]}} | branch={{p["branch"]}} | {{p["last_run"]}}')
""",
        "scan-databases.py": f"""import json, os
base='{BASE}/databases'
for db in sorted(os.listdir(base)):
    fp = os.path.join(base, db, 'flyway_status.json')
    if os.path.exists(fp):
        d = json.load(open(fp))
        print(f'{{db}}: {{len(d["migrations"])}} migrations, {{d["pending_count"]}} pending')
""",
        "scan-security.py": f"""import json
t = json.load(open('{BASE}/security/trivy-scan.json'))
s = json.load(open('{BASE}/security/sonarqube.json'))
print(f'Trivy: {{t["total_vulnerabilities"]}} vulns ({{t["critical"]}} critical, {{t["high"]}} high)')
print(f'SonarQube: {{s["quality_gate"]}} gate | coverage={{s["coverage"]}} | bugs={{s["bugs"]}} | vulns={{s["vulnerabilities"]}}')
""",
        "scan-alerts.py": f"""import json
a = json.load(open('{BASE}/monitoring/prometheus-alerts.json'))
print(f'Alerts: {{a["total_alerts"]}} total, {{a["unacknowledged"]}} unacknowledged')
for alert in a['alerts']:
    if alert['severity'] == 'critical' and not alert['acknowledged']:
        print(f'  CRITICAL [{{alert["service"]}}]: {{alert["message"]}}')
""",
        "scan-docker.py": f"""import json
d = json.load(open('{BASE}/infrastructure/docker-ps.json'))
print(f'Containers: {{d["running"]}}/{{d["total"]}} running ({{d["exited"]}} exited)')
for c in d['containers']:
    if c['status'] != 'running':
        print(f'  {{c["name"]}}: {{c["status"]}} (restarts={{c["restart_count"]}})')
""",
        "scan-disk.py": f"""import json
d = json.load(open('{BASE}/infrastructure/disk-usage.json'))
for v in d['volumes']:
    print(f'  {{v["mount"]}}: {{v["used_gb"]}}/{{v["total_gb"]}}GB ({{v["usage_pct"]}}%)')
""",
        "scan-drift.py": f"""import json
d = json.load(open('{BASE}/config-audit/drift-report.json'))
print(f'Services with drift: {{d["services_with_drift"]}}/{{d["total_services"]}}')
for drift in d['drifts']:
    print(f'  {{drift["service"]}}: {{drift["parameter"]}} - prod={{drift["prod_value"]}} vs staging={{drift["staging_value"]}}')
""",
        "scan-backups.py": f"""import json
d = json.load(open('{BASE}/backups/status.json'))
for b in d['backups']:
    print(f'  {{b["database"]}}: {{b["status"]}} (last: {{b["last_backup"]}}, size={{b["size_gb"]}}GB)')
""",
        "scan-ssl.py": f"""import json
d = json.load(open('{BASE}/ssl/certificates.json'))
print(f'Expiring soon: {{d["expiring_soon"]}} certs')
for c in d['certificates']:
    if c['warning']:
        print(f'  {{c["domain"]}}: {{c["days_remaining"]}} days remaining')
""",
        "scan-licenses.py": f"""import json
d = json.load(open('{BASE}/compliance/sbom-licenses.json'))
print(f'Packages: {{d["total_packages"]}} | High-risk: {{d["high_risk"]}} | Copyleft: {{d["copyleft"]}}')
""",
        "scan-deploys.py": f"""import json
d = json.load(open('{BASE}/team/recent-deploys.json'))
print(f'Recent deploys: {{len(d["deploys"])}}')
for dep in d['deploys']:
    if dep['status'] in ('FAILED', 'ROLLED_BACK'):
        print(f'  {{dep["deployer"]}} deployed {{dep["service"]}} {{dep["version"]}} to {{dep["environment"]}}: {{dep["status"]}}')
""",
    }

    for name, content in scanners.items():
        with open(scripts_dir / name, "w") as f:
            f.write(content)

    # Count
    count = sum(1 for _ in BASE.rglob("*") if _.is_file())
    print(f"\n✅ Enterprise environment ready at {BASE}")
    print(f"   Files created: {count}")
    print(f"   Services: {len(SERVICES)}")
    print(f"   Databases: {len(DATABASES)}")
    print(f"   CI/CD pipelines: {len(PIPELINES)}")
    print(f"   Scanner scripts: {len(scanners)}")
    print(f"\nNext: cd {BASE} && python3 perseus.py render .perseus/context.md --output .hermes.md")


if __name__ == "__main__":
    main()
