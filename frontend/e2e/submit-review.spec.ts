import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

const ART = path.resolve("artifacts/e2e");
const LABEL = path.resolve("../backend/corpus/images/old_tom_clean.png");

test("submit → review → approve, with zero console errors", async ({ page }) => {
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

  // Submit page (routed)
  await page.goto("/submit");
  await page.getByPlaceholder("OLD TOM DISTILLERY").fill("OLD TOM DISTILLERY");
  await page.getByPlaceholder("Kentucky Straight Bourbon Whiskey").fill("Kentucky Straight Bourbon Whiskey");
  await page.getByPlaceholder("45% Alc./Vol. (90 Proof)").fill("45% Alc./Vol. (90 Proof)");
  await page.getByPlaceholder("750 mL").fill("750 mL");
  await page.locator('input[type="file"]').setInputFiles(LABEL);
  await page.getByRole("button", { name: "Submit for review" }).click();

  // A successful submit routes straight to the review of that application.
  await expect(page).toHaveURL(/\/queue\/[a-f0-9]+/, { timeout: 45_000 });
  // First verification runs here (OCR model load) — allow time.
  await expect(page.getByText("Brand name")).toBeVisible({ timeout: 45_000 });
  // A caught submit error would have surfaced as this banner (and kept us on /submit).
  await expect(page.getByText(/Could not submit/)).toHaveCount(0);
  await page.screenshot({ path: path.join(ART, "01-review.png"), fullPage: true });

  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved")).toBeVisible();
  await page.screenshot({ path: path.join(ART, "02-approved.png"), fullPage: true });

  // Browser back/forward navigation works (router).
  await page.goBack();
  await expect(page).toHaveURL(/\/submit$/);

  fs.writeFileSync(path.join(ART, "console.log"), logs.join("\n"));
  expect(errors, `console/page errors:\n${errors.join("\n")}`).toHaveLength(0);
});
