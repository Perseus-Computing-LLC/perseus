# Design-Partner Onboarding & Feedback Cadence

**Audience:** 5–10 high-fit design partners — CTO/founder-led teams running
real LLM or agent workloads.
**Tracking issue:** perseus#829
**Rule:** Outreach must never advertise a self-serve paid checkout while it is
disabled. Free covers teams of 10 or fewer — no card, no automatic charge;
an optional donation is presented only after independently verified savings.

---

## 1. One-page onboarding guide (send this to every design partner)

### Step 1 — Create your Perseus Cloud account
Go to **https://perseus.observer/cloud/signup/** and register with your work
email and a password. The Free starter tier includes 1,000 entities and
1 workspace — no credit card required.

### Step 2 — Verify your email
Click the verification link we send you. The Cloud API confirms the address
(`GET /api/accounts/verify`) before the workspace activates.

### Step 3 — Open your Cloud dashboard
Log in at **https://perseus.observer/cloud/dashboard/**. This is your control
surface: plan and seats, verified-savings recommendation, and the link to
your ledger-backed audit receipt.

### Step 4 — Sign in to Plutus with Google
Open **https://plutus.perseus.observer/auth/login** and use Google sign-in.
Plutus is the metering and audit layer: it records usage into an append-only,
hash-chained ledger and produces your tamper-evident savings receipt.

### Step 5 — Create an API key
From your Cloud account, create an API key
(`POST /api/accounts/api-keys` against **https://cloud-api.perseus.observer**).
Store it as an environment variable — it is shown once.

### Step 6 — Record your first usage event
Point one real workload at the API with your key — e.g. store and recall a
memory (`POST /api/v1/remember`, `POST /api/v1/recall`) or meter an LLM call
through Plutus. Your first metered event appears on the dashboard and in
`GET /api/v1/usage`.

**You are done when:** you can see at least one metered usage event on your
dashboard without anyone's help. If any step took help, that is a friction
point — tell us (see feedback template below).

---

## 2. Outreach cadence

| When | Channel | Purpose | Message spine |
|------|---------|---------|---------------|
| **Day 0** (signup) | Email | Welcome + the one-page guide above | "Here's the 10-minute path to your first metered event. Free covers your whole team (≤10 seats) — no card, no automatic charge, ever." |
| **Day 3** | Email | Activation check | "Did you reach your first usage event? If anything snagged, reply with the step number — we fix onboarding friction within a week." If they activated: ask for the first feedback template. |
| **Day 7** | Email or 20-min call | Feedback + value review | Walk their usage/audit receipt together; collect the feedback template; ask the willingness-to-pay signal. Mention the optional donation **only if** their dashboard shows independently verified savings. |

Cadence rules:
- Stop the sequence the moment a partner replies — every reply gets a human
  response within one business day.
- Never mention subscriptions, seat pricing, or checkout in Days 0–7.
- Log every touch (date, channel, outcome) so gate evidence for the Team beta
  (plutus#164) accumulates by construction.

---

## 3. Feedback template (copy into every Day 3/Day 7 touch)

```
Partner: ____________________   Date: __________

1. One friction point
   (the single step that confused, slowed, or annoyed you most — with the
   step number from the onboarding guide)

2. One useful metric
   (the number on your dashboard or audit receipt that mattered to you —
   e.g. verified savings, tokens audited, efficiency number)

3. Willingness-to-pay signal
   [ ] Would pay today, unprompted
   [ ] Would pay if <specific gap> closed: __________
   [ ] Would not pay — value not clear yet
   [ ] Declined to answer

Free-form (optional): anything you'd tell a peer about the product?
```

Route completed templates into the design-partner log; the friction points
feed onboarding fixes, and the WTP signals feed the Team-beta gate
("three explicit requests for >10 seats or advanced reporting").

---

## 4. Acceptance checklist for this issue

- [x] Guide covers: signup → verify email → Cloud dashboard → Plutus Google
      sign-in → API-key creation → first usage event, with exact public URLs.
- [x] Day 0 / Day 3 / Day 7 cadence defined.
- [x] Feedback template: one friction point, one useful metric, WTP signal.
- [x] Clear statement: Free covers teams of 10 or fewer; no card and no
      automatic charge; optional donation only after verified savings.
- [x] No self-serve paid checkout advertised anywhere in the outreach.
- [x] No credentials in this document.
