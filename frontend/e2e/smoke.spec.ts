import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/**
 * Playwright browser/accessibility smoke test (FND-01, AC-08; updated
 * `UI-01`/`WP-025` — `/` now redirects to the real Start screen instead
 * of the repository-foundation placeholder route).
 *
 * Runs against the Compose/Nginx origin (see playwright.config.ts).
 * **Authored and typechecked, not live-executed by `WP-025`** — see
 * that work package's disclosed EDS tooling-gap note (no broker-safe
 * operation class currently runs Playwright); this repository's own
 * `test-location-map.md` already classifies browser/e2e tests as a
 * release-candidate gate, not a PR gate.
 */

test('redirects "/" to the Start screen with no browser console errors', async ({
  page,
}) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text())
    }
  })
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message)
  })

  const response = await page.goto('/')

  expect(response?.status()).toBe(200)
  await expect(page).toHaveURL(/\/analyses\/new$/)
  await expect(page.getByRole('heading', { name: 'TrustTable' })).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Try the sales demo' }),
  ).toBeVisible()
  expect(consoleErrors).toEqual([])
})

test('proxies /api/v1/version through Nginx to the backend', async ({
  request,
}) => {
  const response = await request.get('/api/v1/version')

  expect(response.status()).toBe(200)
  const body = (await response.json()) as Record<string, unknown>
  expect(typeof body.application_version).toBe('string')
  expect(typeof body.api_version).toBe('string')
  expect(['development', 'test', 'production']).toContain(body.environment_mode)
})

test('has no serious or critical accessibility violations on the Start screen', async ({
  page,
}) => {
  await page.goto('/')

  const results = await new AxeBuilder({ page }).analyze()
  const seriousOrCritical = results.violations.filter(
    (violation) =>
      violation.impact === 'serious' || violation.impact === 'critical',
  )

  expect(seriousOrCritical).toEqual([])
})
