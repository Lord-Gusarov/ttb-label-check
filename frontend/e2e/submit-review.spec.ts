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

  await page.goto("/");

  await page.getByRole("tab", { name: "Submit application" }).click();
  await page.getByPlaceholder("OLD TOM DISTILLERY").fill("OLD TOM DISTILLERY");
  await page.getByPlaceholder("Kentucky Straight Bourbon Whiskey").fill("Kentucky Straight Bourbon Whiskey");
  await page.getByPlaceholder("45% Alc./Vol. (90 Proof)").fill("45% Alc./Vol. (90 Proof)");
  await page.getByPlaceholder("750 mL").fill("750 mL");
  await page.locator('input[type="file"]').setInputFiles(LABEL);
  await page.getByRole("button", { name: "Submit application" }).click();
  await expect(page.getByText(/Submitted/)).toBeVisible();
  await page.screenshot({ path: path.join(ART, "01-submitted.png"), fullPage: true });

  await page.getByRole("tab", { name: "Agent review" }).click();
  await page.getByRole("button", { name: /OLD TOM DISTILLERY/ }).click();
  await expect(page.getByText("Brand name")).toBeVisible({ timeout: 45_000 });
  await page.screenshot({ path: path.join(ART, "02-review.png"), fullPage: true });
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/Status:\s*approved/i)).toBeVisible();
  await page.screenshot({ path: path.join(ART, "03-approved.png"), fullPage: true });

  fs.writeFileSync(path.join(ART, "console.log"), logs.join("\n"));
  expect(errors, `console/page errors:\n${errors.join("\n")}`).toHaveLength(0);
});
