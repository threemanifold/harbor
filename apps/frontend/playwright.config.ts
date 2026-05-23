import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config used by the walkthrough flows for SYM-214 and onward.
 *
 * The e2e specs serve the production-built `dist/` directory under Vite's
 * `preview` server so the recordings reflect what users actually see. Tests
 * stub out backend traffic via route handlers — no live Harbor backend is
 * required for the walkthrough.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: 'line',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    video: 'on',
    trace: 'retain-on-failure',
    headless: true,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'pnpm preview --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
