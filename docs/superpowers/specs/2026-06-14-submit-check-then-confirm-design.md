# Submit-time check-then-confirm (single application) — design

Date: 2026-06-14
Status: approved (design), pending written-spec review
Scope: single-application submit flow only. Batch (bulk ingest + summary) is a deliberate follow-up.

## Problem

Today, submitting an application **persists it into the agent review queue immediately**, then
shows the automated feedback afterward. In `SubmitPage.onSubmit`, the first call is
`submitApplication` (`POST /api/applications`, which stores the application); the inline comment
acknowledges "the application is created & queued for an agent regardless." So the moment the
applicant clicks Submit, the application is in the queue — before they have seen any feedback or
confirmed they want to send it.

This is backwards for the intended story: the automated OCR/VLM + rules check is meant to be the
**submitter's pre-flight**, so they can correct a problem *before* it reaches a TTB agent — or
consciously submit despite a flag, knowing a human on the TTB side makes the final decision.

The building block already exists and is unused: `previewApplication()` → `POST
/api/applications/preview` **verifies without persisting** (documented as "the submit-time
self-check"). The page simply doesn't use it.

## Goal

A single submission runs the automated self-check *before* anything is persisted. The submitter
sees the result inline on the Submit page and either fixes the label and re-checks, or confirms
("Submit" / "Submit anyway"). Only on confirmation does the application enter the queue. The
submitter never navigates to the agent queue. The human gate is unchanged: the automated check
only ever *recommends*; the TTB agent still makes the decision.

Non-goals: batch ingest/summary (separate spec); auto-approval (explicitly rejected — a PASS from
this tool is a partial check, not a compliance determination); backend verification/store changes.

## Decisions (from brainstorming)

- Submission-time automated check is the submitter's pre-flight; feedback is shown inline on the
  Submit page.
- Nothing reaches the agent queue until the submitter confirms.
- A flagged label can still be submitted ("Submit anyway") — the TTB human decides; we never block.
- No auto-approval anywhere; the human gate stands.
- This brings "applicant self-service pre-check" into scope (previously listed out of scope in
  `users.md`).

## Backend

No change required. The two endpoints already exist:
- `POST /api/applications/preview` — verifies an application (OCR + rules) and returns the
  `Verification` **without persisting** anything.
- `POST /api/applications` — persists a new `Application` (verdict recomputed lazily/cached on the
  agent's first open, existing behavior).

The flow change is: call `preview` first; call the persisting endpoint only on confirmation.

## Frontend — `SubmitPage.tsx`

The form stays mounted throughout (so the same fields + image File are available for both the
check and the later confirm). A small state machine drives the action area below the form:

- **State `result: Verification | null`** — the latest preview result; when set, the feedback
  panel + confirm actions render.
- **State `submitted: {id} | null`** — when set, the post-submit confirmation renders.

Behavior:
1. Primary button **"Check label"** → `previewApplication(new FormData(form))` → set `result`.
   Nothing is persisted.
2. With a `result`:
   - **overall PASS** → render the feedback (reuse `VerificationView`) + a **"Submit"** button.
   - **overall NEEDS_REVIEW / FAIL** → render the feedback with the specifics + two paths:
     edit a field and **Check again**, or **"Submit anyway"** with a note: "A TTB reviewer makes
     the final decision."
3. **Submit / Submit anyway** → `submitApplication(new FormData(form))` → set `submitted` →
   render "Submitted — now in the review queue" + a **"Submit another"** reset.
4. **Stale-guard:** any change to a field or the image **clears `result`** (via the form's
   `onChange`), so the submitter must re-Check before a Submit button is available again — data
   that wasn't the data that was checked can never be submitted.
5. **No navigation** to `/queue` at any point.

Error handling: a preview/submit error (unsupported commodity, unreadable image, network) shows an
inline message and persists nothing. The existing multi-file-drop warning on the dropzone stays.

### Data flow

```
fill form ──Check──▶ POST /preview ──▶ Verification (nothing stored)
                                   │
                  edit a field ◀───┤ (clears result; re-Check required)
                                   │
        Submit / Submit anyway ────▶ POST /api/applications ──▶ {id}
                                   └──▶ "Submitted — in the review queue" (stay on Submit)
```

## Testing

- **Backend (pytest):** add/confirm a test that `POST /preview` returns a verification **and
  leaves the queue empty** (`GET /api/applications` length unchanged) — proves preview does not
  persist.
- **Frontend e2e (`frontend/e2e/submit-review.spec.ts`, Playwright) — TDD first:**
  - "Check" surfaces the verification feedback **and the queue stays empty** afterward.
  - "Submit anyway" then makes the application appear in the queue.
  - Editing a field after a Check hides the Submit button until re-checked (stale-guard).

## Docs

Update `docs/users.md`:
- UC1 (Submit an application) — describe the check-then-confirm flow.
- Move "applicant self-service pre-check" from **Out of scope** into scope.

## Risks

- Double verification (once at preview for the submitter, once on the agent's first open) — cheap
  and acceptable for single submit; not worth threading the preview verdict into `create` now.
- A submitter can "Submit anyway" past every flag — intended; the TTB human is the gate, and the
  application carries its NEEDS_REVIEW/FAIL verdict into the queue for the agent to see.

## Deliverables

- `frontend/src/pages/SubmitPage.tsx` reworked to check-then-confirm (uses the existing
  `previewApplication` + `submitApplication`).
- Backend test asserting `/preview` does not persist.
- Updated Playwright e2e covering the new flow.
- `docs/users.md` UC1 + scope update.
