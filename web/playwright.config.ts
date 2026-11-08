import { defineConfig } from "@playwright/test";

// Smoke tests against a running stack: API (uvicorn app.api.main:app --port 8000), worker
// (python -m app.worker) and the web app (npm run dev, NEXT_PUBLIC_API_BASE_URL set).
// Uses the installed Chrome, so no browser download is needed.
export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 60_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PW_BASE_URL ?? "http://localhost:3000",
    channel: process.env.PW_CHANNEL ?? "chrome",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
});
