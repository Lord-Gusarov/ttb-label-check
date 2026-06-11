import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./artifacts/e2e",
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: { baseURL: "http://localhost:5173", screenshot: "only-on-failure", trace: "on-first-retry" },
  timeout: 60_000,
  webServer: [
    {
      command: "cd ../backend && uv run uvicorn app.main:app --port 8000",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --port 5173",
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
