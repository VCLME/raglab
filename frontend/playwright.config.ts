import { defineConfig, devices } from "@playwright/test";

// Declared here rather than pulling in @types/node for a single variable.
declare const process: { env: Record<string, string | undefined> };
const CI = !!process.env.CI;

// Fixed, unusual port so the suite never reuses a developer's server.
const PORT = 5179;
const BASE_URL = `http://127.0.0.1:${PORT}`;

/**
 * End-to-end smoke suite. No backend is needed: every /api/* call is answered
 * by the mocks in e2e/fixtures/ (see mock-api.ts). The Vite proxy to :8000 is
 * never reached because the browser requests are intercepted first.
 *
 * Tests run against the production bundle (vite build + vite preview), the
 * code that ships: the dev server wraps the app in React StrictMode double
 * effects, which behaves differently.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  workers: CI ? 2 : undefined,
  reporter: CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: BASE_URL,
    // The app detects its language from localStorage, then the browser:
    // pin French, the app's default, so labels are deterministic.
    locale: "fr-FR",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx vite build && npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !CI,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
