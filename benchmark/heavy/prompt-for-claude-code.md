# Claude Code Opus 4.7 Max — Perseus Heavy Benchmarking Prompt

You are executing a $50 compute budget against three progressively heavier
Perseus cold-start benchmarks. Burn through them aggressively. Your job is to
produce three benchmark reports that make the scaling curve irrefutable.

## Setup (do once)

```bash
git clone https://github.com/Perseus-Computing-LLC/perseus.git /tmp/perseus-bench-heavy
cd /tmp/perseus-bench-heavy
pip install pyyaml
```

---

## Test 1: Mega-Enterprise (500 Microservices)

Build a synthetic environment that dwarfs the existing 12-service benchmark:

- **500 microservices** — each with health.json, deploy log, per-environment configs (prod/staging/dev)
- **50 databases** — each with Flyway migration status (10-30 migrations, realistic pending counts)
- **30 CI/CD pipelines** — mixed statuses, branches, trigger types
- **100 Docker containers** — across 3 environments, mixed running/exited/crashed
- **Security**: Trivy scan with 200+ CVEs, SonarQube with granular module-level results, Snyk SBOM
- **Monitoring**: 500+ alerts from Prometheus, 50 CRITICAL unacknowledged
- **Infrastructure**: disk usage across 20 volumes, K8s pod status for 200 pods, load balancer health for 15 LBs
- **Compliance**: SBOM with 2,000+ packages, license risk tiers, GDPR data residency map
- **Config drift**: 50+ services with drift across environments (include the actual diff values)
- **Team**: 50 deploys, 25 members, 7-day window

### Context file design
Write a `.perseus/context.md` with 25+ `@query` blocks that call Python scanner
scripts (like the existing pattern). Each `@query` should resolve a full category.
Use `@skills flag_stale=true`, `@session count=5`, `@health`.

### Measurements
1. **Render time** — `time python3 perseus.py render ...` (expect 2-5 seconds)
2. **Discovery calls eliminated** — count how many individual `cat`/`curl`/`docker`/`git`/API calls this replaces (should be **500-800**)
3. **Context file size** — lines of `.hermes.md` output (expect 800-1500 lines)
4. **Subprocess count** — how many parallel Python processes did Perseus spawn?

### Deliverable
`BENCHMARK-MEGA-ENTERPRISE.md` — comparison table, scaling analysis, render time, call elimination count, context size.

---

## Test 2: Mixed Real-World Audit (Perseus Repo + Simulated Org)

This one combines the *real* Perseus repo with a synthetic corporate environment
to demonstrate that Perseus works on genuine codebases, not just toys.

### Environment
- Clone the real Perseus repo as the "platform core" repo
- Add 8 satellite repos simulating a corporate GitHub org:
  - `acme-infra` (Terraform, K8s manifests, Helm charts)
  - `acme-api` (real-looking Go/Python service with tests)
  - `acme-web` (React frontend with Jest/Cypress tests)
  - `acme-mobile` (React Native)
  - `acme-data-pipeline` (Airflow DAGs, dbt models)
  - `acme-ml-serving` (model registry, inference configs)
  - `acme-shared-libs` (internal packages)
  - `acme-docs` (internal wiki, runbooks)
- Each repo has: git log, git status, CI config, dependency manifest, test results file, security scan, codeowners

### Context file design
Write directives that scan across all 9 repos:
- `@query` for each repo's `git log --oneline -10` and `git status`
- `@query` aggregating CI status across all repos
- `@query` aggregating security scan results
- `@query` for dependency freshness across all repos
- Use `@services` with `command:` for any synthetic health endpoints
- Include `@skills`, `@agora` if task files exist, `@health`

### Measurements
Same as Test 1. Additionally: count how many repos a human would need to `cd` into
and run `git log`/`git status`/`cat` commands in.

### Deliverable
`BENCHMARK-MIXED-REAL-WORLD.md`

---

## Test 3: Adversarial — Maximum Directives, Worst-Case Render

Push Perseus to its breaking point. Find where it fails.

### Test matrix
Run render with escalating directive counts and measure failure thresholds:
- 10 @query blocks
- 50 @query blocks
- 100 @query blocks
- 200 @query blocks
- 500 @query blocks

For each:
- Measure render time
- Check if any blocks error out or timeout
- Check if context file is truncated
- Note subprocess limits hit

### Edge cases to test
- `@query` with 10MB+ stdout (does it truncate? crash?)
- `@query` that takes 60+ seconds (timeout behavior)
- `@query` with binary output (null bytes)
- `@query` with shell metacharacters in output (backticks, dollar signs)
- `@query` that references a missing script (error handling)
- `@services` with 100 entries
- `@services` with a `command:` that hangs
- Malformed YAML in context.md (syntax errors)
- Very long context.md files (500+ lines of directives)
- Unicode/emoji in @query output

### Deliverable
`BENCHMARK-ADVERSARIAL.md` — pass/fail matrix, failure modes, performance curve, recommendations.

---

## Output Format

Each benchmark report should follow the same structure as the existing ones:
- Headline metric at the top
- Comparison table (Without Perseus vs With Perseus vs Delta)
- Call-by-call breakdown
- What Perseus pre-resolved (category table)
- Scaling curve row for the master table
- Reproduction instructions

---

## Burn Rate

You have $50 in Claude Code Opus 4.7 Max credit. That's roughly 500M-750M tokens
of thinking budget depending on pricing. Use it. Think hard. Make the benchmarks
bulletproof. If you find real Perseus bugs or limitations, document them — that's
more valuable than clean numbers.

## Deliverables

Commit all three reports + any scripts/environments to:
`/tmp/perseus-bench-heavy/benchmark/heavy/`

Then produce a one-paragraph summary of the combined results suitable for a
GitHub README badge or Hacker News comment.
