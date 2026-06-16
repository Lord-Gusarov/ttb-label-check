import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

// Resolve relative to the frontend/ cwd that Playwright uses.
// (package.json has "type":"module" so __dirname is unavailable; match the pattern
// used in submit-review.spec.ts: path.resolve(relative-from-cwd).)
const FIXTURE_MANIFEST = path.resolve("e2e/fixtures/manifest.json");
// Use a real label image from the backend fixtures — presented to the form under the
// manifest's referenced name so the server reconciliation finds it.
const SOURCE_IMAGE = path.resolve("../backend/tests/fixtures/labels/old_tom_clean.png");

test("batch upload → progress → queue", async ({ page }) => {
  await page.goto("/batch");

  // Set the manifest file.
  await page.getByLabel("Manifest (.json)").setInputFiles(FIXTURE_MANIFEST);

  // Set the label image under the name referenced in the manifest ("label-a.png").
  const imageBuffer = readFileSync(SOURCE_IMAGE);
  await page.getByLabel("Label images").setInputFiles({
    name: "label-a.png",
    mimeType: "image/png",
    buffer: imageBuffer,
  });

  // Client-side reconciliation should confirm all images are matched.
  await expect(page.getByText(/all matched/)).toBeVisible();

  // Click Upload.
  await page.getByRole("button", { name: /Upload/ }).click();

  // The browser navigates to the batch progress page.
  await expect(page).toHaveURL(/\/batch\//);

  // Wait for the single item to reach the "verified" (or "error") state.
  // The subtitle format is "${done} / ${total} verified".
  await expect(page.getByText(/\/ 1 verified/)).toBeVisible({ timeout: 60_000 });

  // "Go to review queue" link appears once all items are done.
  await page.getByRole("link", { name: "Go to review queue" }).click();

  // Should land on the queue page showing at least one tab.
  await expect(page.getByRole("tab").first()).toBeVisible();
});

test("queue tabs are keyboard navigable", async ({ page }) => {
  await page.goto("/queue");

  // Wait for the queue to load — tabs are only rendered after data arrives.
  await expect(page.getByRole("tab").first()).toBeVisible({ timeout: 15_000 });

  const firstTab = page.getByRole("tab").first();
  await firstTab.focus();

  // Arrow-right moves focus and sets aria-selected on the next tab.
  await page.keyboard.press("ArrowRight");

  await expect(page.getByRole("tab", { selected: true })).toBeVisible();
});
