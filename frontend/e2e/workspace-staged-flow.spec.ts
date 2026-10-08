import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

/**
 * Real (non-mocked) staged-upload flow (`UX-02`, `docs/decision-log.md`
 * D-068): Workspace -> choose a file -> Configure -> Run -> Overview.
 *
 * Runs against the Compose/Nginx origin and the real backend (see
 * `playwright.config.ts`). It also exercises the proxy path for an upload
 * larger than nginx's former 1 MB default, which the old configuration would
 * have refused before the backend saw it.
 */

const CSV = 'id,name,amount\n1,Ada,10\n2,Grace,20\n3,Linus,30\n'

function chooseFile(page: Page, name: string, content: string | Buffer) {
  return page.getByLabel('Choose a file to analyze').setInputFiles({
    name,
    mimeType: 'text/csv',
    buffer: Buffer.isBuffer(content) ? content : Buffer.from(content),
  })
}

test('choosing a file starts nothing; Run analyzes exactly the staged file', async ({
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
  await expect(page.getByRole('heading', { name: 'TrustTable' })).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Compare datasets' }),
  ).toBeDisabled()

  await chooseFile(page, 'staged.csv', CSV)

  await expect(page).toHaveURL(/\/configure$/)
  await expect(
    page.getByRole('heading', { name: 'Review your file' }),
  ).toBeVisible()
  await expect(page.getByText('staged.csv')).toBeVisible()
  await expect(page.getByText(/Nothing has been analyzed yet/)).toBeVisible()
  // The reference is never in the address.
  expect(new URL(page.url()).search).toBe('')

  await page.getByRole('button', { name: 'Run analysis' }).click()

  await expect(page).toHaveURL(/\/analyses\/[^/]+\/overview$/, {
    timeout: 30_000,
  })
  await expect(
    page.getByLabel('Dataset summary').getByText('staged.csv'),
  ).toBeVisible()
  expect(consoleErrors).toEqual([])
})

test('accepts an upload larger than 1 MB through the proxy', async ({
  page,
}) => {
  const rows = 'a,b\n' + '1234567,abcdefg\n'.repeat(80_000)
  expect(Buffer.byteLength(rows)).toBeGreaterThan(1024 * 1024)

  await page.goto('/')
  await chooseFile(page, 'large.csv', rows)

  await expect(page).toHaveURL(/\/configure$/, { timeout: 30_000 })
  await expect(page.getByText('large.csv')).toBeVisible()
})

test('reports an unreadable file before anything is kept', async ({ page }) => {
  await page.goto('/')
  await chooseFile(
    page,
    'latin1.csv',
    Buffer.from([0xff, 0xfe, 0x69, 0x64, 0x0a, 0xe9]),
  )

  await expect(page.getByRole('alert')).toContainText(
    'TrustTable cannot read this file',
  )
  await expect(page.getByRole('alert')).toContainText('UTF-8')
  await expect(page).toHaveURL(/\/$/)
})

test('has no serious or critical accessibility violations on the Workspace and Configure screens', async ({
  page,
}) => {
  const seriousOrCritical = async () => {
    const results = await new AxeBuilder({ page }).analyze()
    return results.violations.filter(
      (violation) =>
        violation.impact === 'serious' || violation.impact === 'critical',
    )
  }

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'TrustTable' })).toBeVisible()
  expect(await seriousOrCritical()).toEqual([])

  await chooseFile(page, 'a11y.csv', CSV)
  await expect(
    page.getByRole('heading', { name: 'Review your file' }),
  ).toBeVisible()
  expect(await seriousOrCritical()).toEqual([])
})
