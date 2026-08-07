import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/**
 * Playwright browser/accessibility smoke test (FND-01, AC-08).
 *
 * Runs against the Compose/Nginx origin (see playwright.config.ts).
 * No real product screens exist yet — this exercises the placeholder
 * route, the Nginx `/api/v1` proxy, and a baseline accessibility scan
 * so the proxy and rendering path are proven before real screens land.
 */

test('renders the placeholder route with no browser console errors', async ({
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
  await expect(page.getByRole('heading', { name: 'TrustTable' })).toBeVisible()
  await expect(
    page.getByRole('form', { name: 'placeholder form' }),
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

test('has no serious or critical accessibility violations on the placeholder route', async ({
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
