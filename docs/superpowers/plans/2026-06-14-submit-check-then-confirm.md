# Submit-time check-then-confirm — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a single submission run the automated self-check *before* anything is persisted — the submitter sees the result inline and either fixes the label and re-checks, or confirms ("Submit" / "Submit anyway"); only on confirm does the application enter the agent queue.

**Architecture:** No backend change — wire the existing `POST /api/applications/preview` (verify, no persist) into the Submit page, and call the persisting `POST /api/applications` only on confirm. The Submit form stays mounted; a small state machine shows a feedback panel after a check and a confirmation after submit. Verification the agent later sees is still recomputed lazily on their first open.

**Tech Stack:** React + TypeScript (Vite), FastAPI, pytest (TestClient), Playwright e2e. Backend tests: `.venv/bin/python -m pytest` from `backend/`. Frontend typecheck: `npx tsc --noEmit` from `frontend/`. E2e: `npx playwright test` from `frontend/` (its `webServer` boots the backend on :8000 with escalation off + a /tmp SQLite db, and the dev server on :5173).

Spec: `docs/superpowers/specs/2026-06-14-submit-check-then-confirm-design.md`

---

## File Structure

- Modify `backend/tests/test_api_applications.py` — add a contract test that `/preview` does not persist.
- Modify `frontend/src/pages/SubmitPage.tsx` — rework to check-then-confirm (imports, `SubmitPage`, replace `SubmissionFeedback` with `CheckFeedback` + `SubmittedBanner`; `DropZone` and `FIELDS` unchanged).
- Modify `frontend/e2e/submit-review.spec.ts` — update both tests to the new flow + a queue-count-delta assertion proving Check persists nothing.
- Modify `docs/users.md` — UC1 describes check-then-confirm; move applicant pre-check into scope.

---

## Task 1: Lock the `/preview` non-persist contract (backend)

The whole flow relies on `/preview` verifying without persisting. This test locks that invariant. (It exercises existing behavior, so it should PASS immediately — it is a regression guard, not red→green. If it ever FAILS, that's a real bug the flow depends on.)

**Files:**
- Modify: `backend/tests/test_api_applications.py`

- [ ] **Step 1: Add the test**

Append to `backend/tests/test_api_applications.py`:

```python
@pytest.mark.skipif(not CLEAN.exists(), reason="seed corpus not generated")
def test_preview_verifies_without_persisting():
    fields = dict(commodity_type="distilled_spirits", brand_name="OLD TOM DISTILLERY",
                  class_type="Kentucky Straight Bourbon Whiskey",
                  alcohol_content="45% Alc./Vol. (90 Proof)", net_contents="750 mL")
    before = len(client.get("/api/applications").json())
    with open(CLEAN, "rb") as fh:
        r = client.post("/api/applications/preview", data=fields,
                        files={"image": ("label.png", fh, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["overall"] in ("pass", "warn", "needs_review", "fail")
    after = len(client.get("/api/applications").json())
    assert after == before  # preview must NOT create a queue item
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/test_api_applications.py::test_preview_verifies_without_persisting -v`
Expected: PASS (contract holds). If it FAILS, stop and report — the flow's premise is broken.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_api_applications.py
git commit -m "Lock /preview non-persist contract for submit-time check"
```

(Stage only this file; the working tree has other unrelated changes.)

---

## Task 2: Rewrite the e2e for check-then-confirm (failing test)

**Files:**
- Modify: `frontend/e2e/submit-review.spec.ts`

- [ ] **Step 1: Add a queue-count helper near the top of the file**

After the `hoverField` helper in `frontend/e2e/submit-review.spec.ts`, add:

```typescript
// Count applications via the API (the e2e backend reuses a /tmp db across runs, so assert
// on the DELTA, not an absolute empty queue).
async function appCount(page: import("@playwright/test").Page): Promise<number> {
  const r = await page.request.get("/api/applications");
  return ((await r.json()) as unknown[]).length;
}
```

- [ ] **Step 2: Replace the first test's body (submit → approve) with the check-then-confirm flow**

In `frontend/e2e/submit-review.spec.ts`, replace everything from `// --- Submitter: fill + submit ---...` through the end of the net-contents/warning highlight screenshots (i.e., the block that fills the form, clicks "Submit for review", asserts "Submitted — automated check complete", and does the hover highlights) with:

```typescript
  // --- Submitter: fill + CHECK (no persist) -----------------------------------
  await page.goto("/submit");
  await page.getByPlaceholder("OLD TOM DISTILLERY").fill("OLD TOM DISTILLERY");
  await page.getByPlaceholder("Kentucky Straight Bourbon Whiskey").fill("Kentucky Straight Bourbon Whiskey");
  await page.getByPlaceholder("45% Alc./Vol. (90 Proof)").fill("45% Alc./Vol. (90 Proof)");
  await page.getByPlaceholder("750 mL").fill("750 mL");
  await page.locator('input[type="file"]').setInputFiles(LABEL);

  const before = await appCount(page);
  await page.getByRole("button", { name: "Check label" }).click();

  // Feedback appears IN-PAGE and nothing is persisted yet.
  await expect(
    page.getByText(/Looks good — ready to submit|Review these before submitting/).first(),
  ).toBeVisible({ timeout: 45_000 });
  await expect(page).toHaveURL(/\/submit$/);
  expect(await appCount(page), "Check must not create a queue item").toBe(before);
  // Per-field declared-vs-found shown in the feedback panel.
  await expect(page.getByText("Declared").first()).toBeVisible();
  await expect(page.getByText("Found").first()).toBeVisible();
  // The submitter does NOT get the agent's decision controls.
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await page.screenshot({ path: path.join(ART, "01-check-feedback.png"), fullPage: true });

  // Net contents highlights its region on hover (vertical "750 mL").
  const label = page.getByAltText("submitted label");
  await expect(label).toBeVisible();
  await expect.poll(() => label.evaluate((e) => (e as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await hoverField(page, "Net contents");
  await expect.poll(() => page.locator("svg rect").count()).toBeGreaterThan(0);
  await page.screenshot({ path: path.join(ART, "02-net-contents-highlight.png"), fullPage: true });

  // Government warning highlights EVERY line, not just the prefix (>= 2 rects).
  await hoverField(page, "Government warning text");
  await expect.poll(() => page.locator("svg rect").count()).toBeGreaterThan(1);
  await page.screenshot({ path: path.join(ART, "02b-warning-highlight.png"), fullPage: true });

  // Stale-guard: editing a field after a check hides the confirm action until re-checked.
  await page.getByPlaceholder("750 mL").fill("750 mL ");
  await expect(page.getByRole("button", { name: /^Submit/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Check label" }).click();
  await expect(
    page.getByText(/Looks good — ready to submit|Review these before submitting/).first(),
  ).toBeVisible({ timeout: 45_000 });

  // --- Submitter: CONFIRM -> now it enters the queue --------------------------
  await page.getByRole("button", { name: /^Submit/ }).click();
  await expect(page.getByText("Submitted — now in the review queue")).toBeVisible();
  expect(await appCount(page), "Confirm must create exactly one queue item").toBe(before + 1);
  await page.screenshot({ path: path.join(ART, "03-submitted.png"), fullPage: true });
```

(Leave the `// --- Agent: open it from the queue and approve ---` block and the trailing console/error assertions unchanged.)

- [ ] **Step 3: Update the second test (arc label) to the new button + feedback text**

In the second test (`"hard arc label is rescued..."`), make two replacements:

Replace:
```typescript
  await page.getByRole("button", { name: "Submit for review" }).click();
```
with:
```typescript
  await page.getByRole("button", { name: "Check label" }).click();
```

Replace:
```typescript
  await expect(page.getByText("Submitted — automated check complete")).toBeVisible({ timeout: 45_000 });
```
with:
```typescript
  await expect(
    page.getByText(/Looks good — ready to submit|Review these before submitting/).first(),
  ).toBeVisible({ timeout: 45_000 });
```

- [ ] **Step 4: Run the e2e to confirm it FAILS against the current page**

Run: `cd /Users/gustavohornedo/gauntlet/label-check/frontend && npx playwright test e2e/submit-review.spec.ts`
Expected: FAIL — the current page has a "Submit for review" button and shows "Submitted — automated check complete", so `getByRole("button", { name: "Check label" })` won't be found. This proves the test drives the new flow.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/submit-review.spec.ts
git commit -m "e2e: drive submit-time check-then-confirm flow"
```

---

## Task 3: Implement the check-then-confirm SubmitPage (make it pass)

**Files:**
- Modify: `frontend/src/pages/SubmitPage.tsx`

- [ ] **Step 1: Replace the import block (top of file)**

Replace:
```tsx
import { useRef, useState } from "react";
import { getApplication, submitApplication } from "../api";
import type { AppDetail } from "../types";
import { VerificationView } from "../VerificationView";
import { Field, PageHeading, StatusBadge, VERDICT, inputCls } from "../ui";
```
with:
```tsx
import { useRef, useState } from "react";
import { previewApplication, submitApplication } from "../api";
import type { Verification } from "../types";
import { VerificationView } from "../VerificationView";
import { Field, PageHeading, VerdictPill, inputCls } from "../ui";
```

- [ ] **Step 2: Replace the `SubmitPage` function**

Replace the entire `export function SubmitPage() { ... }` function (from `export function SubmitPage()` down to its closing `}` just before the `/** Left column: ... DropZone */` comment) with:

```tsx
export function SubmitPage() {
  const formRef = useRef<HTMLFormElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<Verification | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [formKey, setFormKey] = useState(0); // bump to remount the form subtree (full reset)

  // Any edit after a check invalidates it — you can never submit data that wasn't checked.
  function invalidate() {
    setError(null);
    setSubmitted(false);
    setChecked(null);
    setImageUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
  }

  async function onCheck(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const verification = await previewApplication(fd);
      const file = fd.get("image");
      setImageUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return file instanceof File ? URL.createObjectURL(file) : null;
      });
      setChecked(verification);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    const form = formRef.current;
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      await submitApplication(new FormData(form));
      setSubmitted(true);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function onAgain() {
    setFormKey((k) => k + 1); // remount the form -> clears inputs AND the DropZone preview state
    invalidate();
  }

  return (
    <div className="rise mx-auto max-w-6xl">
      <PageHeading
        title="Submit an application"
        subtitle="Drop the label artwork on the left, then enter the declared fields on the right. Combine every panel (front, back, side) into one image."
      />
      <form key={formKey} ref={formRef} onSubmit={onCheck} onChange={invalidate} className="mt-6 grid items-start gap-6 lg:grid-cols-[3fr_2fr]">
        <DropZone />
        <div className="space-y-5 rounded-xl border border-line bg-surface p-6 shadow-sm">
          <Field label="Product type">
            <select name="commodity_type" defaultValue="distilled_spirits" className={inputCls}>
              <option value="distilled_spirits">Distilled spirits</option>
              <option value="wine">Wine</option>
              <option value="malt_beverage">Malt beverage</option>
            </select>
          </Field>
          {FIELDS.map((f) => (
            <Field key={f.name} label={f.label}>
              <input name={f.name} required placeholder={f.placeholder} className={inputCls} />
            </Field>
          ))}
          <button
            disabled={busy}
            className="w-full rounded-md bg-brand px-5 py-3 text-base font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
          >
            {busy && !checked ? "Checking…" : "Check label"}
          </button>
          {error && <p className="text-sm text-fail">Could not check: {error}</p>}
        </div>
      </form>

      {submitted ? (
        <SubmittedBanner onAgain={onAgain} />
      ) : (
        checked && <CheckFeedback verification={checked} imageUrl={imageUrl} busy={busy} onConfirm={onConfirm} />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Replace the `SubmissionFeedback` function with `CheckFeedback` + `SubmittedBanner`**

Replace the entire `function SubmissionFeedback({ app, onAgain }: ...) { ... }` function with:

```tsx
/** Inline feedback after a check: the verdict + per-field evidence, then the confirm action.
 *  A PASS offers "Submit"; anything flagged offers "Submit anyway" (a TTB reviewer decides). */
function CheckFeedback({
  verification,
  imageUrl,
  busy,
  onConfirm,
}: {
  verification: Verification;
  imageUrl: string | null;
  busy: boolean;
  onConfirm: () => void;
}) {
  const pass = verification.overall === "pass";
  return (
    <div className="rise mt-8 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-serif text-2xl font-semibold text-ink">
          {pass ? "Looks good — ready to submit" : "Review these before submitting"}
        </h2>
        <VerdictPill verdict={verification.overall} />
      </div>

      <VerificationView verification={verification} imageSrc={imageUrl ?? ""} />

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={onConfirm}
          className="rounded-md bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
        >
          {busy ? "Submitting…" : pass ? "Submit" : "Submit anyway"}
        </button>
        {!pass && (
          <span className="text-sm text-muted">
            Edit a field and check again, or submit anyway — a TTB reviewer makes the final decision.
          </span>
        )}
      </div>
    </div>
  );
}

/** Shown after the submitter confirms: the application is now in the agent queue. */
function SubmittedBanner({ onAgain }: { onAgain: () => void }) {
  return (
    <div className="rise mt-8 space-y-4 rounded-xl border border-line bg-surface p-6 shadow-sm">
      <h2 className="font-serif text-2xl font-semibold text-ink">Submitted — now in the review queue</h2>
      <p className="text-muted">A TTB reviewer will make the final decision. You can submit another application.</p>
      <button
        type="button"
        onClick={onAgain}
        className="rounded-md bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-110"
      >
        Submit another application
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Typecheck**

Run: `cd /Users/gustavohornedo/gauntlet/label-check/frontend && npx tsc --noEmit`
Expected: no errors. (If `VerdictPill` or `Verification` names are off, fix the import to match `frontend/src/ui.tsx` / `frontend/src/types.ts`.)

- [ ] **Step 5: Run the e2e to confirm it now PASSES**

Run: `cd /Users/gustavohornedo/gauntlet/label-check/frontend && npx playwright test e2e/submit-review.spec.ts`
Expected: PASS — both tests green; the count-delta assertions confirm Check persists nothing and Confirm creates exactly one.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SubmitPage.tsx
git commit -m "Submit page: check-then-confirm before queueing an application"
```

---

## Task 4: Update users.md

**Files:**
- Modify: `docs/users.md`

- [ ] **Step 1: Rewrite UC1**

In `docs/users.md`, replace the UC1 paragraph:
```
**UC1 — Submit an application** *(Applicant · built)*
The Applicant enters the declared fields and uploads the label image, and submits. → A new
application appears in the review queue, awaiting review.
```
with:
```
**UC1 — Submit an application (check-then-confirm)** *(Applicant · built)*
The Applicant enters the declared fields and uploads the label image, then **Checks** it: the
automated reading + rules run as a pre-flight and the results are shown inline — nothing is
persisted yet. The Applicant either corrects a flagged field and re-checks, or **confirms**
("Submit" / "Submit anyway" — a TTB reviewer makes the final decision). → Only on confirmation
does a new application enter the review queue.
```

- [ ] **Step 2: Move applicant pre-check into scope**

In the `**Out of scope**` line, remove `applicant self-service pre-check;` (it is now in scope via UC1's check step). Leave the other out-of-scope items intact.

- [ ] **Step 3: Commit**

```bash
git add docs/users.md
git commit -m "docs: UC1 check-then-confirm; applicant pre-check now in scope"
```

---

## Final verification

- [ ] Backend suite green: `cd backend && .venv/bin/python -m pytest -q` — all pass, 4 skipped (vlm).
- [ ] Frontend typecheck clean: `cd frontend && npx tsc --noEmit`.
- [ ] E2e green: `cd frontend && npx playwright test e2e/submit-review.spec.ts` — both tests pass; Check persists nothing, Confirm queues exactly one.
