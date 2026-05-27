---
name: pir-action-tracker
description: >-
  Parses Post-Incident Review (PIR) pages in a Confluence space, fetches live
  status from referenced Jira tickets, updates action item tables with current
  status and due dates, marks completed PIRs with a visual closure panel, and
  surfaces any overdue actions for follow-up. Designed for Customer Success,
  Support, and Account Management teams managing post-incident commitments.
tags: [confluence, jira, incident-management, account-management, automation]
requires: [confluence-mcp, jira-mcp]
---

# PIR Action Tracker Skill

Automates the maintenance of Post-Incident Review (PIR) pages in Confluence by
syncing action item status from Jira, flagging overdue items, and marking
completed PIRs with a visible closure panel.

---

## What This Skill Does

1. **Discovers** all PIR pages in a configured Confluence space
2. **Parses** every action item table — extracts ticket references, current status, and due dates
3. **Fetches live status** for each referenced Jira ticket
4. **Updates** each PIR page in-place with the latest status and due date
5. **Closes** completed PIRs with a prominent green ✅ success panel listing what was accomplished
6. **Reports** any overdue or unverifiable actions for human follow-up

---

## Configuration

Before running, set these variables in your prompt or environment:

| Variable | Example | Description |
|---|---|---|
| `CONFLUENCE_SITE` | `your-org.atlassian.net` | Confluence site hostname |
| `CONFLUENCE_SPACE` | `MYSPACE` | Space key to scan for PIR pages |
| `PIR_SEARCH_TERM` | `PIR` | Title keyword used to find PIR pages (default: "PIR") |
| `JIRA_SITE` | `your-org.atlassian.net` | Primary Jira site for ticket lookups |
| `TICKET_PREFIX_MAP` | See below | Map ticket prefixes to Jira sites |

### Ticket Prefix Map (optional)
If your PIRs reference tickets across multiple Jira sites, provide a prefix-to-site map:
```
CMON, SAM → hello.atlassian.net
PIRA → opsj.atlassian.net
MEP → experimentation-platform.atlassian.net
```
Tickets on inaccessible external sites are flagged in the report but not updated.

---

## Trigger Phrases

- "update the PIR tracker"
- "check PIR action items"
- "sync PIR pages"
- "any overdue PIR actions?"
- "close completed PIRs"
- "PIR status update"

---

## Workflow

### Step 1 — Discover PIR Pages

```
search_confluence_using_cql(
  site_url="{CONFLUENCE_SITE}",
  cql='space = "{CONFLUENCE_SPACE}" AND title ~ "{PIR_SEARCH_TERM}" AND type = page ORDER BY lastModified DESC',
  limit=50
)
```

For each page, note the page ID, title, URL, and last modified date.

---

### Step 2 — Parse Action Item Tables

For each page:
1. Fetch: `get_confluence_page(page_url=..., output_file="tmp_pir_{page_id}.html")`
2. Find all `<table>` elements containing columns named any of:
   - `Ticket`, `Issue`, `Jira`
   - `Status`, `Current Status`
   - `Action`, `Work to Be Done`, `Action item summary`
   - `Due date`, `Target date`, `Est. Completion`
3. For each row extract:
   - **ticket_id** — Jira key from `<a href>` or cell text
   - **action_summary** — plain-text description of the work
   - **status_text** — text inside `<span data-type="status">`
   - **due_date** — from `<time datetime="YYYY-MM-DD">` or plain text

#### Common Table Formats

| Format A | Format B |
|---|---|
| Ticket \| Work to Be Done \| Est. Completion \| Current Status | Ticket \| Action summary \| Status \| Target date \| Notes |
| Dates as plain text ("May 31, 2026") | Dates as `<time datetime="YYYY-MM-DD">` |
| Status as `<span data-type="status">` | Status as `<span data-type="status">` |

---

### Step 3 — Fetch Live Jira Status

For each ticket:
1. Determine Jira site from prefix map (or use default `JIRA_SITE`)
2. Call: `get_jira_issue(issue_url=..., extra_fields=["duedate", "status", "resolutiondate"])`
3. Map Jira status → Confluence status lozenge:

| Jira Status | Lozenge Text | Color |
|---|---|---|
| Done / Resolved / Closed / Won't Do | Done | green |
| In Progress / In Review / Dev Complete | In Progress | blue |
| To Do / Open / Backlog | To Do | neutral |
| Blocked | Blocked | red |
| On Hold / Deferred | On Hold | yellow |

4. Due date: prefer `duedate` field → fall back to `resolutiondate` (if Done) → fall back to existing page value

> If a ticket is inaccessible (external Jira, no auth), skip gracefully — keep the existing page value and note it in the report.

---

### Step 4 — Update PIR Pages

For each page with at least one changed value:

1. Edit the local HTML file — update status lozenges and date cells:

```html
<!-- Status update -->
<span data-type="status" data-color="blue">In Progress</span>
→ <span data-type="status" data-color="green">Done</span>

<!-- Date update (Format B) -->
<time datetime="2026-05-11">May 11, 2026</time>
→ <time datetime="2026-06-15">June 15, 2026</time>
```

2. Publish:
```
update_confluence_page(
  page_url=...,
  content="tmp_pir_{page_id}.html",
  version_message="PIR Action Tracker: synced status from Jira — {YYYY-MM-DD}"
)
```

3. Delete the temp file after publishing.

**Safety rules:**
- Only modify status and date cells in action item tables
- Never touch incident summary, root cause, timeline, or resolution sections
- Only re-publish pages where at least one value changed
- If a ticket is inaccessible, keep the existing page value

---

### Step 5 — Mark Completed PIRs as Closed

A PIR is eligible to be marked **Closed** when:
- All action items in all tables have status: Done / Resolved / Closed
- OR the page has no tracked action items (narrative-only PIR)

For each eligible page, prepend a green success panel to the top of the page:

```html
<div data-type="panel-success">
  <h2>✅ All Post-Incident Actions Complete — This PIR is Closed</h2>
  <p>All engineering follow-up actions from this incident have been completed
  and verified. No further action is required from Atlassian on this
  incident.</p>
  <p><strong>{N} completed actions:</strong></p>
  <ul>
    <li><p>{Plain-English description of action 1}</p></li>
    <li><p>{Plain-English description of action 2}</p></li>
    ...
  </ul>
  <p><em>Closed: {date} · {team name}</em></p>
</div>
```

**Guidelines for the action list:**
- Use human-readable plain English — not ticket keys or internal identifiers
- Group by theme if there are more than 6 actions (e.g. "Cluster Optimization (4 actions): ...")
- For narrative-only PIRs (no tracked tickets), use the shorter variant:
  ```html
  <h2>✅ This PIR is Closed — No Tracked Action Items</h2>
  <p>This post-incident review was completed without formal tracked action items.
  The findings and recommendations are documented below for reference.</p>
  ```

Do not add the closure panel if any action items are still open.

---

### Step 6 — Generate Overdue Report

Flag any action item where:
- Due date is in the past AND status is not Done/Resolved
- Due date is "TBD" AND the incident is > 90 days old
- Ticket fetch failed AND due date is in the past

```
⚠️  PIR ACTION ITEM STATUS REPORT
════════════════════════════════════
Generated: {date} | Pages scanned: {N} | Pages updated: {N}

🔴 OVERDUE — Past Due Date, Not Done
──────────────────────────────────────
PIR: {page title} → {page URL}
  • {ticket} — {action summary}
    Due: {date} ({N} days overdue) | Status: {current status}
    → Recommended: {suggested follow-up}

🟡 TBD — No Due Date, Incident > 90 Days Old
──────────────────────────────────────────────
PIR: {page title} → {page URL}
  • {ticket} — {action summary}
    → Recommended: Request a target date from the engineering team

⚪ STATUS UNVERIFIABLE — External Ticket
──────────────────────────────────────────
PIR: {page title} → {page URL}
  • {ticket} — {action summary}
    → Manually verify at: {ticket URL}

✅ ALL CLEAR
─────────────
{N} pages updated · {N} action items synced · {N} already current · {N} PIRs closed
```

---

### Step 7 — Offer Follow-Up Actions

After the report, offer:
1. Draft a follow-up email to the responsible engineering team for overdue items
2. Create a tracking Jira ticket for overdue follow-up
3. Add overdue items to the next morning brief or standup agenda

---

## Suggested Cadence

| Trigger | When |
|---|---|
| Weekly sweep | Monday morning, alongside account health checks |
| New PIR published | Run immediately to initialize action items |
| On demand | Any time you need a current status snapshot |

---

## Example Usage

```
# Weekly sweep
"Update the PIR tracker for all open SpaceX PIRs"

# Check for overdue items only
"Any overdue PIR actions this week?"

# Close completed PIRs
"Mark any completed PIRs as closed"

# After a new PIR is published
"New PIR just published — sync it with the tracker"
```

---

## Tips

- **Pre-filter by date**: Use `lastModified > now("-180d")` in the CQL query to skip very old PIRs that are unlikely to have open items.
- **Batch updates**: Run all Jira fetches in parallel before making any page updates to minimize round trips.
- **Customer-safe language**: When writing the closure panel action list, avoid internal team names, ticket keys, and jargon. Write as if the customer will read it — because they might.
- **Preserve history**: Always use a meaningful `version_message` so the page history shows what changed and why.

---

*Part of the Perseus skill library. Compatible with Rovo Dev CLI, Claude Code, and any MCP-enabled assistant.*
*See: https://github.com/tcconnally/perseus*
