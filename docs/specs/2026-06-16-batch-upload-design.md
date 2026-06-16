# Batch upload — design

**Date:** 2026-06-16
**Status:** Approved (pending spec review)

## Problem

Stakeholder discovery (Sarah Chen, Deputy Director) named a concrete pain: large
importers "dump 200, 300 label applications on us at once," and today the team
processes them one at a time. The prototype currently supports only a single
application per submission. This design adds **batch upload** so many applications
can be submitted together and triaged as a group.

## Goals

- Submit N applications in one upload and have an agent triage them as a group.
- Reuse the existing verification pipeline unchanged — including the tool's
  headline capability, *declared-vs-found matching*.
- Keep the upload responsive at the stakeholder's real scale (200–300 items).
- Hold the existing bars: WCAG-AA UI, fail-safe verification, the "clean, obvious"
  UX standard, and the unauthenticated-endpoint safety caps.

## Non-goals (out of scope, recorded in limitations)

- CSV manifests (JSON only — see "Manifest format" below).
- Zip upload (plain multi-file selection instead).
- A per-batch filter on the main review queue.
- COLA integration, auth, retention — unchanged from the rest of the prototype.

## Key decisions

| Decision | Choice | Why |
|---|---|---|
| Input model | **Manifest + images, full matching** | Preserves declared-vs-found matching; reuses the whole pipeline. |
| Manifest format | **JSON** | Reads like a real integration payload; structured per-row validation; avoids CSV comma-escaping hazards in `responsible_party`/warning/class-type strings. |
| Processing | **Background worker + live progress** | At ~2–5s/label, 200 items can't block the request; the queue needs verdicts up front to triage. |
| Single vs. batch | **Single submit = "batch of one"** | One canonical payload and one shared processing path; no duplicated logic. |

## Architecture

### Canonical application payload

There is one canonical "application payload" — the declared fields plus a reference
to its image:

```
ApplicationPayload (validated by pydantic)
  commodity_type, brand_name, class_type, alcohol_content,
  net_contents, source, country_of_origin, responsible_party,
  image: <filename>          # names an image file in the same upload
```

The single Submit form is just one UI that builds one such payload. A batch manifest
is an array of the same payload. Both feed the identical per-application path, which
already exists: `verify_label(img, commodity_type, application_dict)` takes a plain
dict today.

### Shared core

```
process_one(payload, image_bytes) -> Application
  # decode + size-guard the image, create the Application row (verify_status=pending),
  # store it, enqueue it for background verification. Returns immediately.
```

`process_one` is called once by single-submit and N times by batch. Verification
itself runs in the worker, not in `process_one`.

### Endpoints

```
POST /api/applications        # single — unchanged external contract (multipart form);
                              #          internally routes through process_one + enqueue
POST /api/applications/batch  # manifest .json + N image files in one multipart form
GET  /api/batches/{id}        # batch progress + item summaries (polled by the UI)
```

The batch endpoint parses the manifest, matches each object's `image` field to an
uploaded file by filename, and hands each (payload, image) pair to `process_one`.

## Background processing

**One worker pool, one queue, every submission async.** Single submit returns
instantly (the applicant already saw their result via the submit-time **Check**);
the item verifies in the background and then appears in the queue. This also removes
today's lazy-on-open quirk where an unopened submission has a `null` verdict.

- **Worker:** a module-level `ThreadPoolExecutor` (default size 2, configurable via
  env). OCR is CPU-bound, so we deliberately do not over-subscribe.
- **Lifecycle:** workers flip an item `pending → verifying`, run the existing
  `verify_label`, then store the result as `verified`, or record `error`.
- **Self-healing:** on startup, re-enqueue any rows left `pending`/`verifying` so a
  mid-batch restart resumes rather than stranding items.

### Data model changes

`Application` gains:

- `batch_id: str | None` — groups items; single submits leave it null.
- `verify_status: "pending" | "verifying" | "verified" | "error"`.
- `verify_error: str | None` — message if verification raised.

New `Batch` entity (minimal): `id, created_at, total`. All progress counts are
**derived** by querying the batch's applications — no counters to keep in sync.

(SQLite store: add the three columns to `applications` with safe defaults, plus a
`batches` table. The in-memory test store mirrors the same fields.)

## Error handling

Two layers, neither of which fails the whole batch for one bad row:

**Upload-time (synchronous, per-row):**
- Malformed JSON / not an array → `400`, reject the upload.
- Otherwise validate each object. A row is **skipped** (not fatal) when it has a
  missing required field, an unsupported commodity, an `image` filename not among the
  uploaded files, or an unreadable/oversized image. Valid rows proceed.
- Response: `{ batch_id, accepted: N, skipped: [{index, image, reason}] }`.

**Verify-time (in the worker):**
- A row that throws → `verify_status = error` + `verify_error`, surfaced as an error
  chip in the UI. Never crashes the batch. (Consistent with the existing fail-safe
  philosophy: the tool advises; a human always decides.)

**Bounds (unauthenticated endpoint safety):** existing per-image size/resolution caps
still apply per image; add a max items-per-batch (default 500).

## API: progress

`GET /api/batches/{id}` →

```
{ id, total, counts: { pending, verifying, verified, error }, items: [ <summary> … ] }
```

The frontend polls ~1.5s and stops when `pending + verifying == 0`.

## UI

### Batch upload page (`/batch`, new nav item)

A distinct, labeled nav entry beside Submit and Queue (clearer than a hidden toggle).

- One drop zone accepting **a `.json` manifest + many image files** in a single
  multi-select/drag.
- **Client-side reconciliation preview before upload** — parse the manifest and
  cross-check filenames against the chosen images:
  - `"Manifest: 24 applications · 24 images · all matched ✓"`, or
  - warn: `"3 rows reference images you didn't include (…)"` /
    `"2 images aren't referenced by any row."`
  - Catches the most common mistake (filename mismatch) before upload; the server
    re-validates authoritatively.
- Button **"Upload N applications"** → POSTs the multipart form → navigates to the
  progress view.

### Batch progress view (`/batch/:id`)

- Header + progress bar: `"Batch · 18 / 24 verified."`
- Live tallies: **Clear · Needs attention · Verifying · Errors** (Clear/attention
  split the verified items).
- A table that fills in as items complete: brand + a `Verifying…` spinner that
  resolves to a verdict pill; each row links to the existing Review page. Polls
  `GET /api/batches/:id`; stops when done.
- **Skipped rows** (from the upload response) shown up top, expandable:
  `"3 rows skipped — see why."`
- On completion: `"20 clear · 4 need attention · 0 errors"` + CTA
  **"Go to review queue."**

### Tabbed review queue (replaces the stacked, scrolling sections)

Batch items are normal `Application`s, so they flow into the existing queue. At
200–300 items a single scrolling page is unworkable, so the queue becomes tabbed:

- Tabs: **Needs attention** · **Recommended to approve** · **Verifying** ·
  **Decided**, each with a count badge.
- **Default tab: Needs attention** — where the agent's judgment is required.
- **Recommended to approve** keeps the prominent **Approve all N** bulk action.
- **Verifying** is the live view of items still being checked.
- **Grouping fix:** group by `verify_status`, not just `overall`. Today
  `attention = overall !== "pass"`, which wrongly dumps any *unverified* item (null
  verdict) into "Needs attention." New buckets: Verifying (pending/verifying),
  Recommended to approve (verified + pass), Needs attention (verified + not pass),
  Decided. This also cleans up the single-submit lazy-verdict quirk.
- **Accessibility:** real ARIA tabs (`tablist`/`tab`/`tabpanel`, arrow-key nav) to
  hold WCAG-AA.
- **URL-reflected:** active tab in the URL (`/queue?tab=attention`) so it survives
  refresh and is linkable.
- **Table column:** add a **"Submitted"** timestamp column (from existing
  `created_at`), sorted newest-first. No backend change.

## Testing

- **Backend unit:** manifest parsing (valid, malformed, not-array); per-row
  validation and skip reasons; filename→image matching; `process_one` creates a
  `pending` row and enqueues; worker transitions (`pending → verifying → verified`)
  and the `error` path; startup re-enqueue of stranded rows; batch progress counts
  derived correctly; items-per-batch cap.
- **Single-submit parity:** single submit still works through the shared core and
  ends up `verified` in the queue.
- **Frontend type gate:** `tsc` strict.
- **E2E (Playwright):** upload a small manifest + images, watch the progress view
  fill in, land items in the tabbed queue, switch tabs, approve-all the clear ones.
- **Accessibility:** contrast-check script over new pages; keyboard tab navigation.

## Rollout notes

- New SQLite columns/table are additive with defaults — existing rows remain valid.
- Worker pool size is env-configurable; default 2 is safe for the container.
