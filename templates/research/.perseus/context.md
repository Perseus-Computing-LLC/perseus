@perseus v0.5

@prompt
You are the research assistant for this workspace. This document was rendered
live by Perseus and assembles current notes, memory, and recent activity. All
values below are current — do not re-verify, just start work.
@end

# Research Session Context — @date format="YYYY-MM-DD HH:mm"

**Workspace:** {workspace}

---

## Project Narrative
@memory focus="recent"

---

## Research Notes
@include "notes/research.md"

---

## Project Overview
@read "README.md"

---

## Open Threads
@agora status=open

---

## Recent Sessions
@session count=5

---

## Last Session
@waypoint

---

## Literature Search
<!-- Placeholder: @research directive lands in #513. Once available, add a
     @research directive here to pull live literature/web search results into
     this section. Until then this section is intentionally inert. -->
