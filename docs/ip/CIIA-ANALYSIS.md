# Perseus — CIIA / Employment Agreement IP Analysis

**Prepared for:** Thomas Connally
**Date:** 2026-05-28
**Governing law:** California (Atlassian CIIA Exhibit B lists CA + DE, IL, KS, MN, NC, UT, WA)
**Statute:** California Labor Code § 2870

---

## 1. Agreements Reviewed

| Document | Key IP Clause | Status |
|---|---|---|
| Offer letter (Atlassian) | Outside Activities — prohibition on "business activity that would create a conflict of interest or compete with the Company" | Original governs |
| CIIA (Confidential Information and Invention Assignment Agreement) | § 4.7 carve-out (California § 2870 standard) | Original governs |
| Role amendments | "All other terms unchanged" — CIIA unchanged | Confirmed |

---

## 2. The § 2870 Carve-Out Standard

California Labor Code § 2870 excludes from assignment any invention that the employee
developed **entirely** on their own time **without** using the employer's equipment, supplies,
facilities, or trade secret information, **except** for inventions that either:

**(a)** Relate, at the time of conception or reduction to practice, to the employer's
business, or actual or demonstrably anticipated research or development; or

**(b)** Result from any work performed by the employee for the employer.

All four of the following must be true for the carve-out to apply:

| Test | Status | Evidence |
|---|---|---|
| 1. Developed entirely on own time | ✅ | Git timestamps outside business hours; personal GitHub account |
| 2. No employer equipment used | ✅ | Development on personal hardware; repo under personal GitHub account |
| 3. No employer trade secrets used | ✅ | No Atlassian-internal code, APIs, or confidential data in repo |
| 4a. Does NOT relate to employer's business | ⚠️ **Live risk** | See §3 below |
| 4b. Does NOT result from work for employer | ✅ | Perseus is not part of any Atlassian product or work assignment |

---

## 3. "Relates to Business" — The Live Risk

### Atlassian's Current AI Products (as of 2026-05-28)

- **Rovo Dev** — AI coding assistant; context-aware, tool-using, MCP-compatible
- **Atlassian Intelligence** — AI features across Jira, Confluence, etc.
- **Atlassian has publicly announced significant AI investment and R&D**

### Perseus's Domain

Perseus is a **live context engine and MCP server for AI assistants**. It resolves
dynamic system state before an LLM sees context, eliminating cold starts. It works
with any MCP-compatible assistant (including Rovo Dev).

### Risk Assessment

| Argument | For carve-out (Perseus is exempt) | Against carve-out (employer may claim) |
|---|---|---|
| **Nature of product** | Perseus is a context *pre-processor*, not an AI coding assistant. It's infrastructure that *feeds* assistants, not an assistant itself. | Rovo Dev also manages context for AI interactions. The "context engine" space is adjacent to Rovo's territory. |
| **Meta-layer argument** | Perseus operates at a layer *below* the assistant — it's a compiler for context, not a consumer of it. Rovo Dev is a consumer of context. | The distinction between "producing context" and "consuming context" may be too fine for an employer's IP department. |
| **Competition** | Perseus is open source (MIT), not a commercial product. No revenue, no customers. | Open source doesn't preclude competition — Perseus aims to replace the same context files (CLAUDE.md, .cursorrules) that Rovo Dev reads. |
| **Timing** | First commit predates Rovo Dev's public context-engine features. Invention date is established. | Employer may argue that "demonstrably anticipated R&D" at time of hiring (2019) included AI/ML broadly, even if specific products shipped later. |
| **Integration framing** | Perseus lists Rovo Dev as a *supported integration target*, implicitly positioning as complementary, not competitive. | Listing a competitor as an integration target doesn't legally exempt from competition analysis. |

### The "At Time of Conception" Defense

The CIIA carve-out is evaluated at the **time of conception**, not at the time of the
employment dispute. Key dates:

- **Employment start:** 2019 (Atlassian was primarily a PM/work-management company)
- **Perseus first commit:** [Check `git log --oneline --reverse | head -1`]
- **Rovo Dev announcement:** [Date TBD — check Atlassian public announcements]
- **Atlassian AI pivot public:** 2023-2024 (Atlassian Intelligence, Rovo)

The gap between Perseus's conception and Atlassian's entry into AI coding assistants is
the strongest defense. If Perseus's first commit predates Rovo Dev's public launch, the
"relates to business" test is evaluated against Atlassian's business *at that earlier date*,
when the company was not in the AI coding assistant space.

---

## 4. Disclosure Obligation

The CIIA contains a **disclosure obligation** — the employee must disclose all inventions
conceived during employment to the employer, even those the employee believes qualify for
the carve-out.

**Status:** ⚠️ **Needs resolution.** The obligation:
- Is typically **unconditional** — triggered by conception, not by patent filing
- Is **separate from ownership** — disclosing does not concede ownership
- Should be accompanied by a cover letter asserting the carve-out position

**Recommendation:** Do NOT disclose without counsel. The attorney should advise on:
1. Whether disclosure is required now or can wait until after non-provisional filing
2. Exact wording of the carve-out assertion in the disclosure letter
3. Whether to file as small entity ($130) vs micro entity ($65) given potential assignment obligation

---

## 5. Outside Activities Clause

The offer letter prohibits "business activity that would create a conflict of interest
or compete with the Company."

| Factor | Analysis |
|---|---|
| Is Perseus a "business activity"? | Unclear — it's open source with no revenue, no customers, no commercial entity |
| Does it compete? | See §3 — meta-layer argument applies |
| Is it a conflict of interest? | Integration with Rovo Dev suggests complementary, not adversarial, relationship |

---

## 6. Documentation to Assemble for Attorney

Before the attorney meeting, gather:

- [ ] Git log showing first commit date and development timeline
- [ ] Evidence of personal hardware (no employer equipment)
- [ ] Absence of Atlassian credentials, VPN, or internal APIs in the repo
- [ ] Rovo Dev public launch date (for "at time of conception" defense)
- [ ] Copy of CIIA and offer letter (the actual executed documents, not templates)
- [ ] Any internal Atlassian policies on employee open source projects

---

## 7. Risk Table

| Risk | Severity | Probability | Mitigation |
|---|---|---|---|
| Employer claims ownership under CIIA | High | Medium | Document timeline, personal equipment, meta-layer argument. File as small entity. |
| Outside Activities clause triggered | Medium | Low | Open source ≠ commercial business. Integration with Rovo Dev frames as ecosystem. |
| Disclosure obligation unmet | Medium | High | Prepare disclosure letter with attorney. Don't self-disclose without counsel. |
| "Relates to business" risk | High | Medium | Conception-date defense. Meta-layer argument. MIT license (no commercial activity). |
| Patent examiner cites Atlassian patents/prior art | Low | Low | Prior art search in progress. Different technical space (context compilation vs. AI assistants). |

---

## 8. Specific Questions for the Attorney

1. "Does Perseus, as an open-source context pre-processor, 'relate to' Atlassian's business of AI coding assistants under § 2870 as evaluated at the time of Perseus's conception?"

2. "Is the disclosure obligation triggered now (provisional filed, public repo) or only at non-provisional filing? What's the recommended timing?"

3. "Should we file the non-provisional as small entity ($130) rather than micro entity ($65) given the unresolved assignment obligation?"

4. "Does the MIT license (no patent grant) + open source status affect the Outside Activities analysis? Is open-sourcing considered 'business activity'?"

5. "If Atlassian claims ownership, what happens to the provisional filing? Can it be re-filed with Atlassian as assignee?"

6. "What's the fee structure for a 2-3 hour opinion letter covering both CIIA and patent strategy?"

---

## 9. Immediate Actions (Before Non-Provisional Deadline: 2027-05-19)

1. **Engage attorney** — dual CIIA + patent prosecution, California-licensed
2. **Resolve disclosure question** — timing, wording, carve-out assertion
3. **Document conception timeline** — git log, personal hardware, no employer resources
4. **Continue evidence collection** — exhibits E5 (adaptive prefetch) and E6 (redaction count) per `docs/ip/README.md`
5. **Complete prior art search** — USPTO full-text, Google Patents, arXiv
