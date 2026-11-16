import { defineConfig } from '@playwright/test';

/**
 * Browser end-to-end journeys (docs/TESTING.md). They run against a running stack: the API on :8000 with
 * SMS_PROVIDER=dev_outbox and the web app on :3000 (E2E_BASE_URL to change it). The installed Google Chrome
 * is used, so no browser download is needed. Journeys share one signed-in user, so they run serially.
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
    channel: 'chrome',
    headless: true,
    locale: 'en-IN',
    timezoneId: 'Asia/Kolkata',
    viewport: { width: 1280, height: 800 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  outputDir: '../../.playwright-results',
});
