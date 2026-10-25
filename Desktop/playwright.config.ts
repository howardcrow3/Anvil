import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: 'e2e',
  globalSetup: './e2e/global-setup.ts',
  timeout: 45_000,
  workers: 1,
  reporter: [['list']],
  use: {
    // Use a pre-installed Chromium when given (CI images, sandboxes); otherwise Playwright's own.
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
    baseURL: 'http://127.0.0.1:4173', viewport: { width: 1280, height: 800 }, screenshot: 'only-on-failure' },
  webServer: {
    command: 'npx vite build -c vite.web.config.ts && npx vite preview -c vite.web.config.ts',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,
    timeout: 120_000
  }
})
