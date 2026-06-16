# Design: Submit → Review → Decide flow (single application)

**Date:** 2026-06-11 · **Status:** Approved (design) · **Scope:** single application end-to-end

## Context & goal

The verification *engine* (pluggable OCR/VLM readers + deterministic rules + government-warning
checks) is already built. This design wraps it in a usable flow that demonstrates the real COLA
process end to end:

> a bottler/importer **submits** an application (declared fields + label image) → a TTB agent
> **reviews** it with AI-assisted verification → **decides** Approve / Reject / Needs Correction.

Constraints (from the assignment):
- **Local-first — no cloud APIs, no outbound ML calls.** The agency firewall blocks ML
  endpoints (it broke the prior vendor's pilot). The engine already runs entirely in-process;
  this flow adds **zero** external calls and would run **air-gapped**. The deployed demo on the
  open internet is only so reviewers can access it — the architecture itself needs no egress.
- **<5 s** to a result (the prior vendor died at 30–40 s).
- Standalone POC, **no COLA integration**, **no auth**, **store nothing sensitive**.
- UI usable by a non-technical 73-year-old.

## Roles as modes (no auth)

The applicant (submitter, "in the field") and the agent (reviewer) are different people in
reality, but in the prototype they are simply **two views toggled by a top-level tab** — no
logins, no permissions. This lets the demo show both sides of the same process.

## The two modes

### ① Applicant — "Submit an application"
A clean form: **commodity type** (wine / distilled spirits / malt), **brand name**, **class/type**,
**alcohol content**, **net contents**, and **upload one label image**. Submit creates an
application with status `submitted`. (This stands in for filing a COLA — it's how data enters a
standalone tool.) Validation: required fields present; image is JPEG/PNG within a size limit.

### ② Agent — "Review queue" (the core)
- A **list** of submitted applications (id, brand, commodity, status, submitted time).
- **Open one** → verification runs (the existing engine) and shows **per-field results**:
  brand **MATCH**, alcohol content **MATCH**, net contents **MATCH**, government warning
  **PRESENT** (exact wording / ALL-CAPS / bold), class/type **PRESENT/VALID** — each
  `PASS / WARN / NEEDS_REVIEW / FAIL` with **evidence** (declared value vs. what was read, and a
  bounding-box overlay on the label image).
- The agent **decides: Approve / Reject / Needs Correction** (optional free-text note). The tool
  *advises*; the human decides (human-in-the-loop).

## Canonical data model

`Application`:
- `id`, `created_at`, `status` (`submitted | approved | rejected | needs_correction`)
- `commodity_type`
- declared fields: `brand_name`, `class_type`, `alcohol_content`, `net_contents`
- `label_image` (bytes/path, in-memory)
- `decision_note` (optional)

`VerificationResult` (from the engine): overall verdict + `[FieldResult]`, where each
`FieldResult` has `field`, `kind` (`match | present`), `verdict`, `expected`, `found`, `detail`,
and evidence (bbox) for the overlay.

## Check semantics (already in the engine; restated)

- **MATCH** (label must agree with the declared value): brand, alcohol content, net contents.
- **PRESENT** (mandatory on the label; no declared value to compare): government warning
  (exact + caps + bold), class/type validity. (Class/type matches *if* a value is declared.)
- Each field → `PASS / WARN / NEEDS_REVIEW / FAIL`; the label-level verdict is the most severe.

## Verdict → suggested decision (advisory only)

- all `PASS` → suggest **Approve**
- any `FAIL` → suggest **Needs Correction** (or Reject)
- any `NEEDS_REVIEW` → suggest **Needs Correction / human review**

The agent always makes the final call.

## Architecture

Applicant form → `Application` store → on agent open,
`pipeline.verify_label(image, commodity, application)` → `VerificationResult` → agent decision →
status update.

- **Backend (FastAPI):**
  - `POST /api/applications` — create from form fields + image (multipart)
  - `GET /api/applications` — list (queue)
  - `GET /api/applications/{id}` — detail + verification result (runs/caches verification)
  - `POST /api/applications/{id}/decision` — `{decision, note}` → updates status
- **Store:** in-memory dict, reset on restart (prototype; nothing sensitive).
- **Frontend (React):** top toggle (Applicant | Agent); Applicant form; Agent queue + review view
  (label image with bbox overlays, per-field results, decision buttons).

## Error handling (an explicit eval criterion)

- Unreadable image / low OCR confidence → `NEEDS_REVIEW` with a "request a better image" message;
  never a crash or a stack trace.
- Missing declared field → that field's check is `NEEDS_REVIEW`.
- Unsupported file type / oversized image → clear validation error at submit time.
- A failure on one application never affects others.

## Testing

- **Backend:** engine already covered by golden tests; add API tests — create application, list,
  get-with-verification on `old_tom_clean` → expected per-field verdicts, decision updates status.
- **Frontend:** type-check + production build; basic component smoke for the two modes.
- **End-to-end:** submit the OLD TOM sample → review → see passing results → Approve.

## Phasing & batch-readiness

Batch is the **most-emphasized stakeholder ask** (Sarah's whole paragraph; "Janet has been
asking for years") — it is a committed phase, not a "maybe". We sequence it second only so the
single path is solid first; the design is deliberately **batch-shaped from day one**:

- **Phase 1 (this build):** single application — submit one → review one → decide.
- **Phase 2 (next):** batch upload. It only changes **ingestion**, not the review experience,
  because: the agent mode is already a **queue**, each `Application` is an **independent unit**,
  and the engine is **stateless**. So batch = "create many `Application`s at once → they land in
  the same queue", plus a batch summary (counts of pass / needs-review / fail) on top.
  - **Input shape (finalized in Phase 2):** a package of application units — each unit is a
    *label image + its declared fields* (e.g. a ZIP with a per-image JSON sidecar). **Not** a
    flat CSV — the unit includes the image, which a spreadsheet row can't carry.
  - Processing is an async job with bounded concurrency and **per-item isolation** (one bad
    file never sinks the batch), staying under the 5 s/label budget per item.

Nothing in Phase 1 should block this — the API and data model below are designed so batch is
additive (a bulk-create endpoint + a batch summary view), not a rewrite.

## Out of scope (deferred / future)

- Multi-surface label sets (front/back/neck) — single image for now.
- LLM advisory **judgment layer** (misleading/prohibited claims) — discussed, deferred.
- Persistent storage, auth, real PII handling.
- Curved-text uncertainty flag from OCR polygon angles (captured as a research note).
