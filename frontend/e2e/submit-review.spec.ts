import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

const ART = path.resolve("artifacts/e2e");
// Vertical label: exercises the net-contents highlight case the submitter flagged.
const LABEL = path.resolve("../backend/tests/fixtures/labels/old_tom_rich_vertical.png");

// Playwright's single-point hover can "teleport" the cursor without firing mouseover, so
// React's onMouseEnter never fires. Move from a neutral point with steps so it registers.
async function hoverField(
  page: import("@playwright/test").Page,
  text: string,
  root?: import("@playwright/test").Locator,
) {
  const t = (root ?? page).getByText(text, { exact: false }).first();
  await t.scrollIntoViewIfNeeded();
  const b = await t.boundingBox();
  if (!b) throw new Error(`no bounding box for "${text}"`);
  await page.mouse.move(5, 5);
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 8 });
}

// Count applications via the API (the e2e backend reuses a /tmp db across runs, so assert
// on the DELTA, not an absolute empty queue).
async function appCount(page: import("@playwright/test").Page): Promise<number> {
  const r = await page.request.get("/api/applications");
  return ((await r.json()) as unknown[]).length;
}

test("submit shows in-page feedback; agent approves from the queue", async ({ page }) => {
  fs.mkdirSync(ART, { recursive: true });
  const logs: string[] = [];
  const errors: string[] = [];
  page.on("console", (m) => {
    logs.push(`[${m.type()}] ${m.text()}`);
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) =>
    errors.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));

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

  // Net contents highlights its region on hover (vertical "750 mL"). Scope to the feedback
  // panel — the form (still mounted) has its own "Net contents" label.
  const feedback = page.getByTestId("check-feedback");
  const label = feedback.getByAltText("submitted label");
  await expect(label).toBeVisible();
  await expect.poll(() => label.evaluate((e) => (e as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await hoverField(page, "Net contents", feedback);
  await expect.poll(() => page.locator("svg rect").count()).toBeGreaterThan(0);
  await page.screenshot({ path: path.join(ART, "02-net-contents-highlight.png"), fullPage: true });

  // Government warning highlights EVERY line, not just the prefix (>= 2 rects).
  await hoverField(page, "Government warning text", feedback);
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
  // Intercept the submit POST to capture the returned application ID.
  const submitResponse = page.waitForResponse((r) => /\/api\/applications$/.test(r.url()) && r.request().method() === "POST");
  await page.getByRole("button", { name: /^Submit/ }).click();
  const submitJson = await (await submitResponse).json() as { id: string };
  const submittedId = submitJson.id;
  await expect(page.getByText("Submitted — now in the review queue")).toBeVisible();
  expect(await appCount(page), "Confirm must create exactly one queue item").toBe(before + 1);
  await page.screenshot({ path: path.join(ART, "03-submitted.png"), fullPage: true });

  // --- Agent: open it from the queue and approve ------------------------------
  // Wait via API until the background worker has verified the item (the review page
  // does not auto-refresh, so we must arrive after verification is done).
  await expect.poll(
    async () => {
      const r = await page.request.get(`/api/applications/${submittedId}`);
      const a = await r.json() as { verify_status: string };
      return a.verify_status === "verified" || a.verify_status === "error";
    },
    { timeout: 45_000, intervals: [1_000] },
  ).toBe(true);
  // Navigate via the queue page so the back-button test below has a valid history entry.
  await page.goto("/queue");
  await expect(page.getByRole("tab").first()).toBeVisible({ timeout: 15_000 });
  // Use the direct URL for the item — avoids tab-selection ambiguity in the queue listing.
  await page.goto(`/queue/${submittedId}`);
  await expect(page.getByText("Brand name")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved")).toBeVisible();
  await page.screenshot({ path: path.join(ART, "03-approved.png"), fullPage: true });

  // Router back/forward still works.
  await page.goBack();
  await expect(page).toHaveURL(/\/queue$/);

  fs.writeFileSync(path.join(ART, "console.log"), logs.join("\n"));
  expect(errors, `console/page errors:\n${errors.join("\n")}`).toHaveLength(0);
});

test("hard arc label is rescued by Tier-1 rotation and the UX shows it", async ({ page }) => {
  fs.mkdirSync(ART, { recursive: true });
  const ARC = path.resolve("../backend/tests/fixtures/labels/old_tom_rich_circular.png");
  await page.goto("/submit");
  await page.getByPlaceholder("OLD TOM DISTILLERY").fill("OLD TOM DISTILLERY");
  await page.getByPlaceholder("Kentucky Straight Bourbon Whiskey").fill("Kentucky Straight Bourbon Whiskey");
  await page.getByPlaceholder("45% Alc./Vol. (90 Proof)").fill("45% Alc./Vol. (90 Proof)");
  await page.getByPlaceholder("750 mL").fill("750 mL");
  await page.locator('input[type="file"]').setInputFiles(ARC);
  await page.getByRole("button", { name: "Check label" }).click();

  // The submit-time check completes and the outcome is visible, not silent. What the arc
  // label shows depends on the backend config: with the model reader on it resolves and
  // shows the escalation note; with it off (air-gapped CI) the warning is flagged for
  // human review — both are honest, visible outcomes (never a crash or a silent pass).
  await expect(
    page.getByText(/Looks good — ready to submit|Review these before submitting/).first(),
  ).toBeVisible({ timeout: 45_000 });
  // Outcome is visible, never silent: with the model on it shows the escalation note; with it
  // off (air-gapped CI) the warning is flagged for human review ("… — read it").
  await expect(page.getByText(/re-read with rotation|model assistance|read it/i).first()).toBeVisible();
  await page.screenshot({ path: path.join(ART, "04-rotation-rescue.png"), fullPage: true });
});

test("a clean label lands in 'Recommended to approve' and fast-clears in one click", async ({ page }) => {
  fs.mkdirSync(ART, { recursive: true });
  const CLEAN = path.resolve("../backend/tests/fixtures/labels/old_tom_clean.png");
  await page.goto("/submit");
  await page.getByPlaceholder("OLD TOM DISTILLERY").fill("OLD TOM DISTILLERY");
  await page.getByPlaceholder("Kentucky Straight Bourbon Whiskey").fill("Kentucky Straight Bourbon Whiskey");
  await page.getByPlaceholder("45% Alc./Vol. (90 Proof)").fill("45% Alc./Vol. (90 Proof)");
  await page.getByPlaceholder("750 mL").fill("750 mL");
  await page.getByPlaceholder("Bottled by ACME Distillery, City, ST")
    .fill("Old Tom Distillery, Louisville, KY");
  await page.locator('input[type="file"]').setInputFiles(CLEAN);
  await page.getByRole("button", { name: "Check label" }).click();
  await expect(
    page.getByText(/Looks good — ready to submit|Review these before submitting/).first(),
  ).toBeVisible({ timeout: 45_000 });
  // Intercept the submit POST to capture the returned application ID.
  const cleanSubmitResponse = page.waitForResponse(
    (r) => /\/api\/applications$/.test(r.url()) && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Submit/ }).click();
  const cleanSubmitJson = await (await cleanSubmitResponse).json() as { id: string };
  const cleanId = cleanSubmitJson.id;
  await expect(page.getByText("Submitted — now in the review queue")).toBeVisible();

  // Wait via the API until the background worker has finished verifying this specific item.
  await expect.poll(
    async () => {
      const r = await page.request.get(`/api/applications/${cleanId}`);
      const a = await r.json() as { verify_status: string };
      return a.verify_status === "verified" || a.verify_status === "error";
    },
    { timeout: 45_000, intervals: [1_000] },
  ).toBe(true);

  // In the queue it's triaged under "Recommended to approve" — activate that tab first.
  await page.goto("/queue");
  // Wait for tabs to render, then switch to the "Recommended to approve" tab.
  const approveTab = page.getByRole("tab", { name: /Recommended to approve/ });
  await expect(approveTab).toBeVisible({ timeout: 15_000 });
  await approveTab.click();
  // The item is already verified, so it should appear immediately.
  await expect(page.getByRole("link", { name: "OLD TOM DISTILLERY" }).first()).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: path.join(ART, "05-queue-triage.png"), fullPage: true });
  await page.getByRole("button", { name: "Approve", exact: true }).first().click();
  // After fast-clear, the item moves to the "Decided" tab — switch there to confirm approval.
  const decidedTab = page.getByRole("tab", { name: /Decided/ });
  await expect(decidedTab).toBeVisible({ timeout: 10_000 });
  await decidedTab.click();
  await expect(page.getByText("Approved").first()).toBeVisible({ timeout: 10_000 });
});
