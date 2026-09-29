import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../test/msw/server'
import { RulesRoute } from './RulesRoute'

const ANALYSIS_ID = 'analysis-under-test'
const BASE = 'http://localhost/api/v1/analyses/:analysisId'

function makeResult(overrides: Record<string, unknown> = {}) {
  return {
    pass_count: 290,
    fail_count: 10,
    skipped_count: 0,
    duration_ms: 3,
    error: null,
    executed_at: '2026-09-29T10:00:00Z',
    example_failures: [],
    ...overrides,
  }
}

function makeRule(overrides: Record<string, unknown> = {}) {
  return {
    rule_id: 'rule-1',
    name: 'quantity_range',
    description: 'Quantity must be between 1 and 100',
    rule_type: 'numeric_range',
    severity: 'high',
    enabled: true,
    provenance: 'user_authored',
    schema_version: '1',
    scope: 'column',
    null_handling: 'ignore_null',
    source_finding_ids: [],
    columns: [{ internal_key: 'c1', ordinal: 0, original_name: 'quantity' }],
    minimum: 1,
    maximum: 100,
    minimum_date: null,
    maximum_date: null,
    pattern: null,
    accepted_values: null,
    comparison_operator: null,
    comparison_value: null,
    condition_operator: null,
    condition_value: null,
    threshold_percentage: null,
    tolerance: null,
    last_result: makeResult(),
    ...overrides,
  }
}

function useRuleList(items: unknown[]) {
  server.use(
    http.get(`${BASE}/rules`, () =>
      HttpResponse.json({ items, total_items: items.length }),
    ),
  )
}

function renderRules() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [{ path: '/analyses/:analysisId/rules', element: <RulesRoute /> }],
    { initialEntries: [`/analyses/${ANALYSIS_ID}/rules`] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

const errorBody = (code: string, message: string) => ({
  error: { code, message, details: {}, request_id: 'req-1' },
})

describe('RulesRoute', () => {
  const createObjectURL = vi.fn(() => 'blob:rules')
  const revokeObjectURL = vi.fn()
  let clickedDownload: string | null = null

  beforeEach(() => {
    createObjectURL.mockClear()
    revokeObjectURL.mockClear()
    clickedDownload = null
    // Patch only the two static methods: replacing `URL` itself would
    // break `fetch` and MSW, which construct URLs.
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = revokeObjectURL
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clickedDownload = this.download
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(URL, 'createObjectURL')
    Reflect.deleteProperty(URL, 'revokeObjectURL')
    vi.restoreAllMocks()
  })

  it('shows an honest empty state', async () => {
    useRuleList([])
    renderRules()

    expect(
      await screen.findByText(/No validation rules exist/),
    ).toBeInTheDocument()
  })

  it('lists each rule with description, state, severity, provenance and counts', async () => {
    useRuleList([
      makeRule(),
      makeRule({
        rule_id: 'rule-2',
        description: 'Currency must be known',
        enabled: false,
        severity: 'low',
        provenance: 'detector_generated',
        last_result: null,
      }),
      makeRule({
        rule_id: 'rule-3',
        description: 'Broken rule',
        last_result: makeResult({ error: 'column vanished' }),
      }),
    ])
    renderRules()

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(
      within(items[0]).getByText('Quantity must be between 1 and 100'),
    ).toBeVisible()
    expect(within(items[0]).getByText(/Enabled · Severity high/)).toBeVisible()
    expect(
      within(items[0]).getByText('290 passed · 10 failed · 0 skipped'),
    ).toBeVisible()
    expect(within(items[1]).getByText(/Disabled · Severity low/)).toBeVisible()
    expect(within(items[1]).getByText(/detector_generated/)).toBeVisible()
    expect(within(items[1]).getByText('Not run yet.')).toBeVisible()
    expect(
      within(items[2]).getByText(/could not be completed: column vanished/),
    ).toBeVisible()
  })

  it('expands a rule to its columns and only the parameters its type uses, read-only', async () => {
    useRuleList([
      makeRule({
        last_result: makeResult({
          example_failures: [{ row_number: 7, reason: 'Value 0 is below 1' }],
        }),
      }),
    ])
    const user = userEvent.setup()
    renderRules()

    const toggle = await screen.findByRole('button', {
      name: /Show details of rule Quantity/,
    })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)

    const item = screen.getAllByRole('listitem')[0]
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(within(item).getByText('quantity')).toBeVisible()
    expect(within(item).getByText('Minimum')).toBeVisible()
    expect(within(item).getByText('Maximum')).toBeVisible()
    expect(within(item).queryByText('Pattern')).not.toBeInTheDocument()
    expect(within(item).getByText('Row 7: Value 0 is below 1')).toBeVisible()
    expect(within(item).getByText(/shown read-only/)).toBeVisible()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('renders untrusted rule and failure text as escaped text only', async () => {
    useRuleList([
      makeRule({
        description: '<img src=x onerror=alert(1)> rule',
        last_result: makeResult({
          example_failures: [
            { row_number: 2, reason: '<script>alert(2)</script>' },
          ],
        }),
      }),
    ])
    const user = userEvent.setup()
    renderRules()

    await user.click(
      await screen.findByRole('button', { name: /Show details of rule/ }),
    )

    expect(
      screen.getByText('<img src=x onerror=alert(1)> rule'),
    ).toBeInTheDocument()
    expect(document.querySelector('img, script')).toBeNull()
  })

  it('run re-executes that rule and shows the refreshed counts', async () => {
    let rule = makeRule()
    let ranRule: string | readonly string[] | undefined
    server.use(
      http.get(`${BASE}/rules`, () =>
        HttpResponse.json({ items: [rule], total_items: 1 }),
      ),
      http.post(`${BASE}/rules/:ruleId/test`, ({ params }) => {
        ranRule = params.ruleId
        rule = makeRule({
          last_result: makeResult({ pass_count: 300, fail_count: 0 }),
        })
        return HttpResponse.json(rule)
      }),
    )
    const user = userEvent.setup()
    renderRules()

    await user.click(await screen.findByRole('button', { name: /Run rule/ }))

    expect(
      await screen.findByText('300 passed · 0 failed · 0 skipped'),
    ).toBeInTheDocument()
    expect(ranRule).toBe('rule-1')
  })

  it('shows an inline error when a run fails and stays on the page', async () => {
    useRuleList([makeRule()])
    server.use(
      http.post(`${BASE}/rules/:ruleId/test`, () =>
        HttpResponse.json(
          errorBody('RULE_NOT_FOUND', 'That rule no longer exists.'),
          { status: 404 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderRules()

    await user.click(await screen.findByRole('button', { name: /Run rule/ }))

    expect(
      await screen.findByText('That rule no longer exists.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Run rule/ })).toBeEnabled()
  })

  it('delete asks for confirmation, then removes the rule', async () => {
    let rules = [makeRule()]
    let deleted: string | readonly string[] | undefined
    server.use(
      http.get(`${BASE}/rules`, () =>
        HttpResponse.json({ items: rules, total_items: rules.length }),
      ),
      http.delete(`${BASE}/rules/:ruleId`, ({ params }) => {
        deleted = params.ruleId
        rules = []
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderRules()

    await user.click(await screen.findByRole('button', { name: /Delete rule/ }))
    const dialog = await screen.findByRole('alertdialog', {
      name: 'Delete this rule?',
    })
    expect(deleted).toBeUndefined()
    await user.click(
      within(dialog).getByRole('button', { name: 'Delete rule' }),
    )

    expect(
      await screen.findByText(/No validation rules exist/),
    ).toBeInTheDocument()
    expect(deleted).toBe('rule-1')
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('cancelling the delete confirmation deletes nothing', async () => {
    useRuleList([makeRule()])
    let called = false
    server.use(
      http.delete(`${BASE}/rules/:ruleId`, () => {
        called = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderRules()

    await user.click(await screen.findByRole('button', { name: /Delete rule/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(called).toBe(false)
    expect(screen.getByText(/Quantity must be between/)).toBeInTheDocument()
  })

  it('shows an inline error when delete fails and keeps the rule', async () => {
    useRuleList([makeRule()])
    server.use(
      http.delete(`${BASE}/rules/:ruleId`, () =>
        HttpResponse.json(errorBody('INTERNAL_ERROR', 'Could not delete.'), {
          status: 500,
        }),
      ),
    )
    const user = userEvent.setup()
    renderRules()

    await user.click(await screen.findByRole('button', { name: /Delete rule/ }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(
      within(dialog).getByRole('button', { name: 'Delete rule' }),
    )

    expect(await screen.findByText('Could not delete.')).toBeInTheDocument()
    expect(screen.getByText(/Quantity must be between/)).toBeInTheDocument()
  })

  it.each([
    ['JSON', 'json', '{"export_type":"validation_rules"}'],
    ['YAML', 'yaml', 'export_type: validation_rules\n'],
  ])(
    'download %s saves the served file and never renders it',
    async (label, extension, body) => {
      useRuleList([])
      server.use(
        http.get(`${BASE}/exports/rules.${extension}`, () => {
          return new HttpResponse(body, {
            headers: { 'Content-Type': 'text/plain' },
          })
        }),
      )
      const user = userEvent.setup()
      renderRules()

      await user.click(
        await screen.findByRole('button', { name: `Download ${label}` }),
      )

      await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1))
      const blob = (createObjectURL.mock.calls[0] as unknown as [Blob])[0]
      expect(await blob.text()).toBe(body)
      expect(clickedDownload).toBe(`rules-${ANALYSIS_ID}.${extension}`)
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:rules')
      expect(document.body.textContent).not.toContain('validation_rules')
    },
  )

  it('shows an inline error when an export fails', async () => {
    useRuleList([])
    server.use(
      http.get(`${BASE}/exports/rules.json`, () =>
        HttpResponse.json(
          errorBody('INVALID_ANALYSIS_STATE', 'Export needs a completed run.'),
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderRules()

    await user.click(
      await screen.findByRole('button', { name: 'Download JSON' }),
    )

    expect(
      await screen.findByText('Export needs a completed run.'),
    ).toBeInTheDocument()
    expect(createObjectURL).not.toHaveBeenCalled()
  })

  it('shows an inline error when the list cannot be loaded', async () => {
    server.use(
      http.get(`${BASE}/rules`, () =>
        HttpResponse.json(errorBody('INTERNAL_ERROR', 'Rules unavailable.'), {
          status: 500,
        }),
      ),
    )
    renderRules()

    expect(await screen.findByText('Rules unavailable.')).toBeInTheDocument()
  })
})
