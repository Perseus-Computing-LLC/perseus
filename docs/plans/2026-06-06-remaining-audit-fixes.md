# Remaining Audit Findings — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Resolve the 14 remaining findings from the 2026-06-06 Documentation Integrity Audit after PR #205 addressed the first 11.

**Architecture:** Three passes: (1) count standardization across all docs, (2) spec file deep audit for version staleness, (3) documentation coverage gaps for undocumented features. Each pass is self-contained and can be executed independently.

**Tech Stack:** Markdown files, git, grep, no code changes required (pure documentation).

**Prerequisite:** PR #205 merged. Branch from latest `main`.

---

## Phase 1: Count Standardization

### Task 1.1: Add test-count sentinel to README.md

**Objective:** Add a `<!-- test-count: NNN -->` HTML comment sentinel so the website's live JS and CI can validate counts.

**Files:**
- Modify: `README.md` (after line 7, the badge row)

**Step 1: Find current test count**

Run the test suite to get the authoritative count:
```bash
cd /opt/data/webui/minions/.minions-data/workspace/perseus
python -m pytest tests/ -q --co 2>/dev/null | tail -1
# OR count test functions:
grep -c "def test_" tests/test_*.py | awk -F: '{s+=$2} END {print s}'
```

Assume 894 (based on the website's live-fetched count from `<!-- test-count: 894 -->` in the infographic alt text).

**Step 2: Insert sentinel**

Insert after the badge row (current line ~14):
```markdown
<!-- test-count: 894 -->
```

**Existing line 14 is:** `<!-- mcp-name: io.github.tcconnally/perseus -->`

Patch: add the test-count comment on the next line.

**Verification:**
```bash
grep "test-count:" README.md
# Expected: <!-- test-count: 894 -->
```

---

### Task 1.2: Sync test counts in CONTRIBUTING.md and docs/CONTRIBUTING.md

**Objective:** Replace stale test counts with the sentinel value.

**Files:**
- Modify: `CONTRIBUTING.md` (currently says "750+ tests")
- Modify: `docs/CONTRIBUTING.md` (currently says "753 tests expected")

**Step 1: Fix CONTRIBUTING.md**

Old: `python -m pytest tests/ -q    # 750+ tests`
New: `python -m pytest tests/ -q    # 894 tests (<!-- test-count: 894 -->)`

**Step 2: Fix docs/CONTRIBUTING.md**

Old: `python -m pytest tests/ -q        # 753 tests expected`
New: `python -m pytest tests/ -q        # 894 tests expected`

**Verification:**
```bash
grep -n "tests expected\|tests\b.*test" CONTRIBUTING.md docs/CONTRIBUTING.md
```

---

### Task 1.3: Fix MCP tool count in SKILL.md (13 → 24)

**Objective:** SKILL.md claims "13-tool MCP server façade" but Perseus now exposes 24 tools.

**Files:**
- Modify: `SKILL.md`

**Step 1: Update the description line**

Find: `13-tool MCP server façade`
Replace with: `24-tool MCP server`

**Step 2: Update the "what this PR teaches" section if it mentions tool count**

Search SKILL.md for any other "13" references and update.

**Verification:**
```bash
grep -i "13.tool\|24.tool\|tool.*13\|tool.*24" SKILL.md
```

---

### Task 1.4: Fix directive count in SKILL.md (22 → 24)

**Objective:** SKILL.md claims "22 directives" but the table has 20 entries, and the actual directive count is 24. Update header and add missing entries.

**Files:**
- Modify: `SKILL.md`

**Step 1: Update the directive count header**

Find: `use any of these 22 directives`
Replace with: `use any of these 24 directives`

**Step 2: Check the table for missing directives**

The current table is missing: `@env`, `@session`, `@date`, `@validate`, `@drift`, `@perseus`, `@tool`, `@constraint`.

Add rows for the missing directives to the table. Reference `docs/DIRECTIVES.md` for accurate one-line descriptions.

**Verification:**
```bash
# Count directive rows in the SKILL.md table
grep -c "| \`@" SKILL.md
# Should be >= 24
```

---

### Task 1.5: Add count sentinels to all relevant docs

**Objective:** Add HTML comment sentinels so automated tooling can validate counts.

**Files:**
- Modify: `README.md` (already done in 1.1)
- Modify: `SKILL.md`
- Modify: `docs/index.md`
- Modify: `docs/DIRECTIVES.md`

Add these comments near the top of each file:
```markdown
<!-- test-count: 894 -->
<!-- mcp-tool-count: 24 -->
<!-- directive-count: 24 -->
<!-- phase-count: 26 -->
```

Only add the sentinels relevant to each file (e.g., `SKILL.md` gets `mcp-tool-count` and `directive-count`; `docs/index.md` gets `phase-count`).

**Verification:**
```bash
for f in README.md SKILL.md docs/index.md docs/DIRECTIVES.md; do
  echo "=== $f ==="
  grep "<!--.*count:" "$f"
done
```

---

## Phase 2: Spec File Deep Audit

### Task 2.1: Audit and update spec/pythia.md version references

**Objective:** Check if `spec/pythia.md` contains stale version references like `spec/overview.md` did.

**Files:**
- Inspect: `spec/pythia.md`
- Possibly modify: `spec/pythia.md`

**Step 1: Read the file and search for version/phase references**

```bash
grep -n "v0\.[0-9]\|v1\.[0-9]\|Phase [0-9]\|Alpha\|Beta\|MVP" spec/pythia.md
```

**Step 2: Evaluate each reference**

- "Phase 5A" references are historical design docs — these are fine as-is
- Version references like "v0.9.0" need updating to "v1.0.6"
- Status labels like "Alpha" / "MVP" need updating if the feature is shipped

**Step 3: Apply targeted patches for any stale references found**

**Verification:**
```bash
grep "v0\.[0-9]\|Alpha" spec/pythia.md
# Should return nothing (or only historical context that's clearly labeled)
```

---

### Task 2.2: Audit and update spec/components.md

**Objective:** Same as 2.1 but for `spec/components.md`.

**Step 1:** Search for stale references
```bash
grep -n "v0\.[0-9]\|v1\.[0-5]\|Phase [0-9]\|Alpha\|future milestone" spec/components.md
```

**Step 2:** Update any found. "Future milestone" items that are now shipped should be marked as ✅ or removed.

---

### Task 2.3: Audit and update spec/data-model.md

**Objective:** Check for stale config keys, paths, or version references.

**Step 1:** Search
```bash
grep -n "Mnemosyne\|mnemosyne\|gRPC\|Phase\|v0\." spec/data-model.md
```

**Step 2:** The Mnemosyne→Engram-rs migration (v1.0.6) means any `mnemosyne:` config block references are stale. Replace with `engram:` or add migration notes.

---

### Task 2.4: Clarify v0.4 protocol version vs v1.0.6 package version (W7)

**Objective:** Add a clear explanation that `@perseus v0.4` in context files is a directive protocol version, not the package version — and that both v0.4 and v0.8 remain supported.

**Files:**
- Modify: `docs/DIRECTIVES.md` (already has a note, expand it)
- Modify: `SETUP-GUIDE.md` (add a callout in the context template section)
- Modify: `QUICKSTART.md` (add a brief note)

**Step 1: Expand docs/DIRECTIVES.md explanation**

The existing note says:
> "The version number refers to the directive protocol version, not the package version."

Expand to:
> "The version number (`v0.4` or `v0.8`) refers to the **directive protocol version** — the syntax revision Perseus parses. It is **not** the package version (currently v1.0.6). v0.4 and v0.8 context files remain fully supported across all package versions. Most examples in documentation use `@perseus v1.0.6` as a convention matching the package release, but both v0.4 and v0.8 are equivalent in practice."

**Step 2: Add a brief note in SETUP-GUIDE.md and QUICKSTART.md**

In the context template section, add:
```markdown
> **Note:** `@perseus v1.0.6` on line 1 matches the package version by convention.
> v0.4 and v0.8 protocol versions are also supported and functionally equivalent.
```

**Verification:**
```bash
grep -A2 "protocol version" docs/DIRECTIVES.md
grep "v0.4.*v0.8\|protocol version" SETUP-GUIDE.md QUICKSTART.md
```

---

## Phase 3: Documentation Coverage Gaps

### Task 3.1: Document @tool directive

**Objective:** Add user-facing documentation for the `@tool` directive, which allows running allowlisted external tools with argument restrictions. Currently only appears as a one-line entry in `docs/DIRECTIVES.md`.

**Files:**
- Modify: `docs/DIRECTIVES.md` (expand the one-liner)
- Possibly modify: `SETUP-GUIDE.md` (add example)

**Step 1: Expand the @tool entry in docs/DIRECTIVES.md**

Replace the current one-liner:
```
| `@tool "<path>" [args...]` | Run an allowlisted external tool ... |
```

With a multi-line expanded description including:
- Configuration prerequisite: `tools.allowlist` in config.yaml
- Argument restriction syntax
- Timeout and output size cap behavior
- `@cache ttl=N` support
- Example usage

**Step 2: Add a brief example to SETUP-GUIDE.md context template section**

```markdown
## Allowlisted Tools
@tool "./scripts/lint.sh" --check @cache ttl=300
```

**Verification:**
```bash
grep -A5 "@tool" docs/DIRECTIVES.md
```

---

### Task 3.2: Document @perseus (foreign resolver) directive

**Objective:** Same as 3.1 but for `@perseus <remote-url>` — the foreign context resolver with HMAC verification.

**Files:**
- Modify: `docs/DIRECTIVES.md` (expand entry)
- Modify: `docs/CONTEXT_PACKS.md` or `docs/DEPLOYMENT.md` (add cross-reference)

**Step 1: Expand the @perseus entry**

Add:
- Configuration prerequisite: `foreign_resolver.allowlist`
- HMAC signature verification behavior
- TTL caching with graceful degradation
- Security notes (SSRF protection, private-IP blocking)
- Example usage

**Verification:**
```bash
grep -A5 "@perseus" docs/DIRECTIVES.md
```

---

### Task 3.3: Add OPENAI_API_KEY and DEEPSEEK_API_KEY to LLM setup docs

**Objective:** QUICKSTART.md only covers Gemini and Groq free tiers. Add notes about paid providers.

**Files:**
- Modify: `QUICKSTART.md` (in the "Free LLM Backend Options" section)
- Modify: `SETUP-GUIDE.md` (in the LLM configuration section)

**Step 1: Add a "Paid Provider Options" subsection to QUICKSTART.md**

After the Groq section:
```markdown
### Paid Provider Options

**OpenAI:**
```bash
export OPENAI_API_KEY="your-key-here"
```
Config:
```yaml
llm:
  provider: openai-compat
  model: gpt-4o
  url: https://api.openai.com/v1
```

**DeepSeek:**
```bash
export DEEPSEEK_API_KEY="your-key-here"
```
Config:
```yaml
llm:
  provider: openai-compat
  model: deepseek-chat
  url: https://api.deepseek.com/v1
```
```

**Step 2: Add the env vars to SETUP-GUIDE.md LLM config section**

**Verification:**
```bash
grep -c "OPENAI_API_KEY\|DEEPSEEK_API_KEY" QUICKSTART.md
# Should be >= 2
```

---

### Task 3.4: Clarify ANTHROPIC_API_KEY ownership in DEPLOYMENT.md (W8)

**Objective:** `ANTHROPIC_API_KEY` is a Hermes Agent prerequisite, not a Perseus one. Make this clear.

**Files:**
- Modify: `docs/DEPLOYMENT.md`

**Step 1: Update the prerequisites table**

Change:
```
| `ANTHROPIC_API_KEY` | `grep ANTHROPIC_API_KEY ~/.hermes/.env` | valid key |
```

To:
```
| `ANTHROPIC_API_KEY` | `grep ANTHROPIC_API_KEY ~/.hermes/.env` | valid key (Hermes Agent prerequisite, not Perseus) |
```

**Step 2: Add a note**

After the prerequisites table, add:
```markdown
> **Note:** `ANTHROPIC_API_KEY` is consumed by Hermes Agent's LLM proxy, not by Perseus directly.
> Perseus itself requires no API keys for core functionality. LLM-augmented features use the
> provider configured in `~/.perseus/config.yaml` with their respective env vars
> (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`).
```

**Verification:**
```bash
grep -A3 "Hermes Agent prerequisite" docs/DEPLOYMENT.md
```

---

## Phase 4: Website Polish

### Task 4.1: Add "and 12 more" note to website directive display (W6)

**Objective:** The website shows 12 directives visually but Perseus has 24. Add a note.

**Files:**
- Modify: `index.html`

**Step 1: Find the directive grid section**

Around line 2207, the `.greek` divs list 12 directives.

**Step 2: Add a trailing note after the last directive**

After `@prompt` (line ~2262):
```html
<div class="greek" style="opacity:0.5; font-size:0.85em;">+ 12 more</div>
```

(This is a one-line CSS-styled addition, keeping the visual design intact.)

**Verification:**
```bash
grep "12 more" index.html
```

---

### Task 4.2: Add documentation site link to topbar nav (W3)

**Objective:** The sticky topbar has nav links but no "Docs" link. Add one.

**Files:**
- Modify: `index.html`

**Step 1: Find the topbar nav**

Around line 181-205, the topbar nav links.

**Step 2: Add a Docs link before the GitHub button**

```html
<a class="nav-link" href="https://github.com/tcconnally/perseus/blob/main/docs/index.md">Docs</a>
```

**Verification:**
```bash
grep "nav-link.*Docs\|Docs.*nav-link" index.html
```

---

## Phase 5: External

### Task 5.1: Update Anthropic Skills PR #1193

**Objective:** The PR at https://github.com/anthropics/skills/pull/1193 references 13 tools and 596 tests — both stale.

**Note:** This is an external repo. Cannot be done from this session. Action items:

1. Add a comment to PR #1193 with updated numbers:
   - "Perseus now exposes 24 MCP tools (up from 13)"
   - "Test suite: 894 tests (up from 596)"
2. Consider closing and re-opening with updated SKILL.md content
3. Mark as a follow-up task for the project owner

---

## Execution Order

```
Phase 1 (Counts):  1.1 → 1.2 → 1.3 → 1.4 → 1.5
Phase 2 (Specs):   2.1 → 2.2 → 2.3 → 2.4
Phase 3 (Gaps):    3.1 → 3.2 → 3.3 → 3.4
Phase 4 (Website): 4.1 → 4.2
Phase 5 (External): 5.1 (manual follow-up)

Any phase can run independently after Phase 1.
```

**Estimated total tasks:** 16
**Estimated time:** ~45-60 minutes (mostly grep/replace, some writing)

---

## Verification Checklist

After all phases complete, run the full audit verification:

```bash
cd /opt/data/webui/minions/.minions-data/workspace/perseus

# 1. No PERSEUS_WORKSPACE phantoms remain
grep -rn "PERSEUS_WORKSPACE" --include="*.md" --include="*.html" --include="*.json" . | grep -v ".git/" | grep -v benchmark/
# Expected: empty

# 2. No dead benchmark/ links
grep -rn 'href="benchmark/"' --include="*.html" .
# Expected: empty

# 3. PERSEUS_ALLOW_DANGEROUS in README and website
grep -c "PERSEUS_ALLOW_DANGEROUS" README.md index.html
# Expected: >= 1 each

# 4. Test count consistency
grep -oh "<!-- test-count: [0-9]* -->" README.md docs/CONTRIBUTING.md CONTRIBUTING.md | sort -u
# Expected: exactly one value

# 5. Phase count: 26 everywhere
grep "phases shipped" docs/index.md ROADMAP.md spec/overview.md
# Expected: all say 26

# 6. MCP tool count: 24 in SKILL.md
grep "24.tool\|tool.*24" SKILL.md
# Expected: found

# 7. Directive count: 24 in SKILL.md
grep "24 directive" SKILL.md
# Expected: found

# 8. No stale Alpha/v0.9.0 in spec files
grep -rn "Alpha\|v0\.9\.0" spec/ | grep -v "historical"
# Expected: empty or only clearly labeled historical context
```
