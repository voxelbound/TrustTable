import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/**
 * Real (non-mocked) demo-analysis-flow smoke test (`UI-01`, `WP-025`).
 *
 * Runs against the Compose/Nginx origin and the real backend (see
 * `playwright.config.ts`) — demo action -> overview -> findings, plus
 * an axe-core scan on each of the three real screens.
 *
 * **Authored and typechecked, not live-executed by `WP-025`** — see
 * `smoke.spec.ts`'s disclosed EDS tooling-gap note (no broker-safe
 * operation class currently runs Playwright); this repository's own
 * `test-location-map.md` already classifies browser/e2e tests as a
 * release-candidate gate, not a PR gate. `POST /demo/sales` runs the
 * pipeline synchronously to completion within one request (`WP-023`'s
 * disclosed narrowing) — a real run is expected to observe the analysis
 * already `completed` shortly after navigation, not a multi-frame
 * progress animation.
 */

test('runs the sales demo end to end: Start -> Overview -> Findings', async ({
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

  await page.goto('/')
  await page.getByRole('button', { name: 'Try the sales demo' }).click()

  await expect(page).toHaveURL(/\/analyses\/[^/]+\/overview$/, {
    timeout: 30_000,
  })
  await expect(
    page.getByRole('heading', { name: 'Trust assessment' }),
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Top findings' }),
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Dataset summary' }),
  ).toBeVisible()
  await expect(page.getByText('sales_demo.csv')).toBeVisible()

  await page.getByRole('link', { name: 'View all findings' }).click()
  await expect(page).toHaveURL(/\/analyses\/[^/]+\/findings$/)
  await expect(page.getByRole('table')).toBeVisible()

  expect(consoleErrors).toEqual([])
})

test('has no serious or critical accessibility violations on the Overview screen', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Try the sales demo' }).click()
  await expect(page).toHaveURL(/\/analyses\/[^/]+\/overview$/, {
    timeout: 30_000,
  })
  await expect(
    page.getByRole('heading', { name: 'Trust assessment' }),
  ).toBeVisible()

  const results = await new AxeBuilder({ page }).analyze()
  const seriousOrCritical = results.violations.filter(
    (violation) =>
      violation.impact === 'serious' || violation.impact === 'critical',
  )

  expect(seriousOrCritical).toEqual([])
})

test('has no serious or critical accessibility violations on the Findings screen', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Try the sales demo' }).click()
  await expect(page).toHaveURL(/\/analyses\/[^/]+\/overview$/, {
    timeout: 30_000,
  })
  await page.getByRole('link', { name: 'View all findings' }).click()
  await expect(page.getByRole('table')).toBeVisible()

  const results = await new AxeBuilder({ page }).analyze()
  const seriousOrCritical = results.violations.filter(
    (violation) =>
      violation.impact === 'serious' || violation.impact === 'critical',
  )

  expect(seriousOrCritical).toEqual([])
})
