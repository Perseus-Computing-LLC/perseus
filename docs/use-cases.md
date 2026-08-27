# Perseus use cases

**See also:** [Perseus examples](./EXAMPLES.md) for concrete walkthroughs.

Perseus renders operator-selected workspace sources into a context file before
an assistant session. The result reflects the configured sources at render time;
source-system checks, permissions, retention, and freshness remain part of each
team's operating process.

## Sales

- **Onboarding:** Render playbooks, approved account notes, and current project
  files into one reviewable starting point. The team decides which sources are
  appropriate and checks records in the systems of record.
- **Account preparation:** Assemble selected CRM exports, support notes, and
  meeting material into a bounded context file before a call. The output is a
  snapshot, not a replacement for the CRM or an assertion that every record is
  current.
- **Handoffs:** Use checkpoints and local memory to give the next teammate a
  dated trail of decisions, open work, and requested follow-ups. Review the
  source entries before relying on them.
- **Drafting:** Give an assistant approved background material for outreach,
  proposals, or briefing notes. A human still reviews the resulting copy and
  any customer-specific claims.

## Marketing

- **Launch preparation:** Render release notes, issue lists, and approved
  product material into a bounded planning context. Keep publication decisions
  separate from the render step.
- **Campaign review:** Combine selected reports and experiment notes so a team
  can inspect the inputs used for a planning discussion. Perseus does not
  determine attribution or campaign success.
- **Research intake:** Organize approved market notes and links before an
  assistant summarizes them. External sources keep their own update and
  retention policies.

## Support

- **Case preparation:** Provide an assistant with the approved history and
  troubleshooting material for a case. The support system remains authoritative
  for account state, entitlements, and current incidents.
- **Escalation handoff:** Use checkpoints and task files to preserve decisions,
  requested actions, and unresolved questions between shifts.
- **Runbook lookup:** Render the relevant runbook and local service signals for
  an operator review. A health check is an observation, not proof that a service
  will remain healthy.

## Engineering and operations

- **New-team-member context:** Render repository conventions, open tasks, recent
  checkpoints, and selected test output before work begins. The engineer should
  inspect the source and rerun important checks.
- **Release review:** Assemble the release notes, build result, dependency
  report, and known issues that a reviewer has selected. Perseus does not sign
  or authorize a release by rendering those files.
- **Incident preparation:** Collect approved local logs, service observations,
  and handoff notes into a bounded context file. Keep secrets and uncontrolled
  log bodies out of the configured paths.

## Management and executive review

- **Weekly review:** Render selected project status, decisions, risks, and
  operational notes into a dated briefing. The briefing is an input to review,
  not a substitute for financial, safety, or mission-system records.
- **Planning:** Keep assumptions, source paths, and open questions visible when
  an assistant drafts scenarios or options. Label generated material before it
  is circulated.
- **Crisis response:** Assemble the approved incident sources available at the
  time of the render, with their timestamps and limitations. Confirm critical
  facts with the responsible teams before acting.

## Common boundary

These examples describe ways to prepare context; they do not promise customer
outcomes, universal freshness, automatic savings, or authority over a source
system. Start with the smallest local render, inspect the output, and expand the
configured sources only when the operating owner accepts their permissions and
retention boundary.
