import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

// Capture full-page screenshots of every page for the UI redesign baseline / after comparison.
// Output dir is overridable: SHOT_DIR=artifacts/ui/after npx playwright test screenshots
const OUT = path.resolve(process.env.SHOT_DIR || "artifacts/ui/before");
const CLEAN = path.resolve("../backend/tests/fixtures/labels/old_tom_clean.png");

async function fillForm(page: import("@playwright/test").Page) {
  await page.getByPlaceholder("OLD TOM DISTILLERY").fill("OLD TOM DISTILLERY");
  await page.getByPlaceholder("Kentucky Straight Bourbon Whiskey").fill("Kentucky Straight Bourbon Whiskey");
  await page.getByPlaceholder("45% Alc./Vol. (90 Proof)").fill("45% Alc./Vol. (90 Proof)");
  await page.getByPlaceholder("750 mL").fill("750 mL");
  await page.getByPlaceholder("Bottled by ACME Distillery, City, ST").fill("Old Tom Distillery, Louisville, KY");
  await page.locator('input[type="file"]').setInputFiles(CLEAN);
}

test("capture all pages", async ({ page }) => {
  fs.mkdirSync(OUT, { recursive: true });

  // 1. Submit — empty form
  await page.goto("/submit");
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: path.join(OUT, "01-submit-empty.png"), fullPage: true });

  // 2. Submit — check feedback
  await fillForm(page);
  await page.getByRole("button", { name: "Check label" }).click();
  await page.getByText(/Looks good — ready to submit|Review these before submitting/).first()
    .waitFor({ timeout: 45_000 });
  await page.screenshot({ path: path.join(OUT, "02-submit-feedback.png"), fullPage: true });

  // 3. Submitted banner — intercept the POST to capture the application ID.
  const submitResponse = page.waitForResponse(
    (r) => /\/api\/applications$/.test(r.url()) && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Submit/ }).click();
  const submitJson = await (await submitResponse).json() as { id: string };
  const appId = submitJson.id;
  await page.getByText("Submitted — now in the review queue").waitFor();
  await page.screenshot({ path: path.join(OUT, "03-submitted.png"), fullPage: true });

  // 4. Queue — wait via API until the background worker finishes verifying, then navigate.
  // The clean label lands in "Recommended to approve"; activate that tab to see it.
  await expect.poll(
    async () => {
      const r = await page.request.get(`/api/applications/${appId}`);
      const a = await r.json() as { verify_status: string };
      return a.verify_status === "verified" || a.verify_status === "error";
    },
    { timeout: 45_000, intervals: [1_000] },
  ).toBe(true);
  await page.goto("/queue");
  await page.waitForLoadState("networkidle");
  const approveTab = page.getByRole("tab", { name: /Recommended to approve/ });
  await expect(approveTab).toBeVisible({ timeout: 15_000 });
  await approveTab.click();
  await page.getByRole("link", { name: "OLD TOM DISTILLERY" }).first().waitFor({ timeout: 15_000 });
  await page.screenshot({ path: path.join(OUT, "04-queue.png"), fullPage: true });

  // 5. Review page (open the item)
  await page.getByRole("link", { name: "OLD TOM DISTILLERY" }).first().click();
  await page.getByText("Brand name").first().waitFor({ timeout: 45_000 });
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: path.join(OUT, "05-review.png"), fullPage: true });
});
