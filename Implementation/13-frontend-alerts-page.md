# Part 13 — Frontend: Early Warning / Alert Management Page

**Depends on:** 10 (frontend architecture/design system), 07 (`GET`/`POST /api/alerts`), 09 (delivery status), 15 (auth — this page has write actions)
**Feeds into:** 16 (integration)
**Owner persona:** Frontend engineer

## 1. Objective

Implement the "Heatwave Early Warning" screen — the page authority users use to create, review, and issue alerts, and to track their multi-channel distribution status, matching the UI mockup's four-panel layout.

## 2. Page contents, section by section

### 2.1 Page header
- Title: "Heatwave Early Warning," subtitle: "Alert creation and authority response management," current region.

### 2.2 Alert Details panel
- Fields: Alert ID (auto-generated, format matching the mockup's human-readable pattern like a prefixed code + year + sequence), Created date, Status (Draft/Ready/Issued — using the shared Status Pill component), Severity (Normal/Heatwave/Severe, using the shared Risk Badge styling), Target region.
- When creating a new alert, most of these fields (ID, created date) are system-generated; severity and target region should default from the current highest-risk prediction context but remain editable by the authority user before issuing.

### 2.3 Alert Distribution panel
- A list of the five distribution channels (Public Mobile Alert, Government Portal, Public Display Boards, Emergency Services, Hospitals & Health Centres) each with a Status Pill showing its current delivery state, sourced from Part 08's `alert_channel_deliveries` table via Part 07's alerts endpoint.
- Before an alert is issued, channels show as "READY" (selectable/toggleable — the authority user chooses which channels to notify); after issuing, this list becomes a live status view reflecting Part 09's dispatch outcomes ("NOTIFIED," "PENDING," "FAILED").

### 2.4 Public Advisory panel
- A text area for the actual advisory message shown to the public (matching the mockup's example: "SEVERE HEATWAVE ALERT — MUMBAI... Residents are advised to avoid prolonged outdoor exposure, stay hydrated, and take extra precautions..."), editable by the authority user before issuing, pre-filled with a sensible default derived from the current prediction's risk class and region (a template, per Part 09 Section 4, not free-form from scratch every time).

### 2.5 Response Coordination panel
- A checklist-style list of internal coordination parties (Disaster Management, Municipal Corporation, Emergency Services, Health Departments, Field Response Teams) each with a status indicator (READY/NOTIFIED/PENDING) — clarify whether this is: (a) functionally identical to the external distribution channels and should reuse that same status-pill mechanism and data source, or (b) a genuinely separate, internal-only coordination tracker not tied to Part 09's delivery pipeline. Document this decision explicitly, since the mockup shows it as visually distinct from the Alert Distribution panel.

### 2.6 Action bar
- "Save as Draft" and "Issue Warning" buttons — mapping to the alert status transitions defined in Part 07 Section 3.4 (both write to the same alert record, changing only its status field). "Issue Warning" is the action that triggers Part 09's dispatch flow and should be a protected action requiring authentication (Part 15) and, ideally, a confirmation step given its real-world consequence.

## 3. Interaction behavior

- Support both **creating a new alert** (form starts empty/defaulted) and **viewing/editing an existing draft alert** (form pre-populated) and **viewing an issued alert read-only** (fields locked, distribution panel becomes a live status monitor) — these are three distinct states of essentially the same page/form and should be modeled as such rather than as separate pages.
- After issuing, the Alert Distribution panel should refresh/poll to reflect delivery status updates from Part 09 as they arrive, per Part 10's polling convention.
- Provide a list/history view of past alerts (referencing `GET /api/alerts`) as the entry point into this page, so authority users can find and review past issued alerts, not just create new ones — confirm this list view's own layout (likely a simple table with ID, region, severity, status, date) even though it's not explicitly detailed in the mockup screenshot.

## 4. Non-functional requirements

- The "Issue Warning" action is a real, consequential, protected action — client-side, this means a clear confirmation UX (not a bare button click with no feedback) and an unambiguous success/failure result shown to the user, distinct from the per-channel delivery statuses which may still be pending at that moment.
- Draft alerts must be safely re-editable without accidentally triggering any notification dispatch — only the explicit "Issue Warning" action does that, never an autosave or a "Save as Draft" click.

## 5. Acceptance criteria / "done"

- [ ] All five panel sections implemented matching the mockup layout.
- [ ] Draft/edit/issued-readonly states implemented as one cohesive page/form.
- [ ] Response Coordination vs. Alert Distribution data-source decision (Section 2.5) made and documented.
- [ ] "Save as Draft" and "Issue Warning" wired to the correct status-transition API calls.
- [ ] Post-issue live status polling implemented.
- [ ] Alert history/list view implemented as the entry point.
- [ ] "Issue Warning" gated behind authentication with a confirmation step.

## 6. Handoff note template

> Alerts page implemented at route: <path>. Response Coordination data-source decision: <summary>. Confirmed alert lifecycle states supported: draft, issued, read-only history.
