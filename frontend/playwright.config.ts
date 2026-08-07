import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright browser/accessibility smoke test config (FND-01, AC-08).
 *
 * Targets the real Docker Compose / Nginx origin — not the Vite dev
 * server — so the proxy and SPA-fallback behavior under test is the
 * same configuration that ships. `webServer` brings the Compose stack
 * up before the run and tears it down afterward.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8080',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'docker compose -f ../docker-compose.yml up',
    url: 'http://127.0.0.1:8080',
    timeout: 90_000,
    reuseExistingServer: false,
  },
})
