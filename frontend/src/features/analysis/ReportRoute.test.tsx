import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../test/msw/server'
import { ReportRoute } from './ReportRoute'

const ANALYSIS_ID = 'analysis-under-test'
const BASE = 'http://localhost/api/v1/analyses/:analysisId/reports'

function makeReport(overrides: Record<string, unknown> = {}) {
  return {
    report_id: 'report-1',
    analysis_id: ANALYSIS_ID,
    generated_at: '2026-09-29T10:00:00Z',
    schema_version: '1',
    content_sha256: 'a'.repeat(64),
    options: {
      include_dismissed: false,
      include_technical_appendix: false,
      include_bounded_examples: false,
    },
    ...overrides,
  }
}

function useReportList(reports: unknown[]) {
  server.use(http.get(BASE, () => HttpResponse.json({ reports })))
}

function renderReport() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [{ path: '/analyses/:analysisId/report', element: <ReportRoute /> }],
    { initialEntries: [`/analyses/${ANALYSIS_ID}/report`] },
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

describe('ReportRoute', () => {
  const createObjectURL = vi.fn(() => 'blob:report')
  const revokeObjectURL = vi.fn()

  beforeEach(() => {
    createObjectURL.mockClear()
    revokeObjectURL.mockClear()
    // Patch only the two static methods: replacing `URL` itself would
    // break `fetch` and MSW, which construct URLs.
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = revokeObjectURL
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  })

  afterEach(() => {
    Reflect.deleteProperty(URL, 'createObjectURL')
    Reflect.deleteProperty(URL, 'revokeObjectURL')
    vi.restoreAllMocks()
  })

  it('shows an honest empty state and all options off by default', async () => {
    useReportList([])
    renderReport()

    expect(
      await screen.findByText(/No reports have been generated/),
    ).toBeInTheDocument()
    for (const name of [
      'Include dismissed findings',
      'Include technical appendix',
      'Include bounded examples',
    ]) {
      expect(screen.getByRole('checkbox', { name })).not.toBeChecked()
    }
    expect(
      screen.getByRole('checkbox', { name: 'Include bounded examples' }),
    ).toHaveAccessibleDescription(/may quote values from your dataset/)
  })

  it('lists reports in the order served with time, options and hash', async () => {
    useReportList([
      makeReport(),
      makeReport({
        report_id: 'report-2',
        generated_at: '2026-09-29T11:00:00Z',
        content_sha256: 'b'.repeat(64),
        options: {
          include_dismissed: true,
          include_technical_appendix: false,
          include_bounded_examples: true,
        },
      }),
    ])
    renderReport()

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByText(/2026-09-29T10:00:00Z/)).toBeVisible()
    expect(within(items[0]).getByText('Default options')).toBeVisible()
    expect(within(items[0]).getByText(/a{64}/)).toBeVisible()
    expect(within(items[1]).getByText(/2026-09-29T11:00:00Z/)).toBeVisible()
    expect(
      within(items[1]).getByText('dismissed findings, bounded examples'),
    ).toBeVisible()
  })

  it('generate posts exactly the chosen options and shows the new report', async () => {
    let reports: unknown[] = []
    let postedBody: unknown = null
    server.use(
      http.get(BASE, () => HttpResponse.json({ reports })),
      http.post(BASE, async ({ request }) => {
        postedBody = await request.json()
        const report = makeReport({
          options: {
            include_dismissed: true,
            include_technical_appendix: false,
            include_bounded_examples: false,
          },
        })
        reports = [report]
        return HttpResponse.json(report, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderReport()

    await user.click(
      await screen.findByRole('checkbox', {
        name: 'Include dismissed findings',
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Generate report' }))

    expect(await screen.findByText('dismissed findings')).toBeInTheDocument()
    expect(postedBody).toEqual({
      options: {
        include_dismissed: true,
        include_technical_appendix: false,
        include_bounded_examples: false,
      },
    })
  })

  it('generate with untouched options sends every option off', async () => {
    useReportList([])
    let postedBody: unknown = null
    server.use(
      http.post(BASE, async ({ request }) => {
        postedBody = await request.json()
        return HttpResponse.json(makeReport(), { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderReport()

    await user.click(
      await screen.findByRole('button', { name: 'Generate report' }),
    )

    await waitFor(() => expect(postedBody).not.toBeNull())
    expect(postedBody).toEqual({
      options: {
        include_dismissed: false,
        include_technical_appendix: false,
        include_bounded_examples: false,
      },
    })
  })

  it('shows an inline error when generation fails and stays on the page', async () => {
    useReportList([])
    server.use(
      http.post(BASE, () =>
        HttpResponse.json(
          errorBody(
            'INVALID_ANALYSIS_STATE',
            'A report needs a completed analysis.',
          ),
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderReport()

    await user.click(
      await screen.findByRole('button', { name: 'Generate report' }),
    )

    expect(
      await screen.findByText('A report needs a completed analysis.'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Generate report' }),
    ).toBeEnabled()
  })

  it('disables generate while the request is pending', async () => {
    useReportList([])
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.post(BASE, async () => {
        await gate
        return HttpResponse.json(makeReport(), { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderReport()

    await user.click(
      await screen.findByRole('button', { name: 'Generate report' }),
    )

    expect(
      await screen.findByRole('button', { name: 'Generating…' }),
    ).toBeDisabled()
    release()
  })

  it('download fetches the stored Markdown for that report and saves it', async () => {
    useReportList([makeReport()])
    let downloadedId: string | readonly string[] | undefined
    server.use(
      http.get(`${BASE}/:reportId/download`, ({ params }) => {
        downloadedId = params.reportId
        return new HttpResponse('# Stored <b>report</b>\n', {
          headers: { 'Content-Type': 'text/markdown' },
        })
      }),
    )
    const user = userEvent.setup()
    renderReport()

    await user.click(
      await screen.findByRole('button', { name: /Download report generated/ }),
    )

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1))
    expect(downloadedId).toBe('report-1')
    const blob = (createObjectURL.mock.calls[0] as unknown as [Blob])[0]
    expect(await blob.text()).toBe('# Stored <b>report</b>\n')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:report')
    // The report text is saved, never rendered into the page.
    expect(document.body.innerHTML).not.toContain('<b>report</b>')
  })

  it('shows an inline error when a download fails', async () => {
    useReportList([makeReport()])
    server.use(
      http.get(`${BASE}/:reportId/download`, () =>
        HttpResponse.json(
          errorBody('REPORT_NOT_FOUND', 'That report no longer exists.'),
          { status: 404 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderReport()

    await user.click(
      await screen.findByRole('button', { name: /Download report generated/ }),
    )

    expect(
      await screen.findByText('That report no longer exists.'),
    ).toBeInTheDocument()
    expect(createObjectURL).not.toHaveBeenCalled()
  })

  it('shows an inline error when the list cannot be loaded', async () => {
    server.use(
      http.get(BASE, () =>
        HttpResponse.json(errorBody('INTERNAL_ERROR', 'Reports unavailable.'), {
          status: 500,
        }),
      ),
    )
    renderReport()

    expect(await screen.findByText('Reports unavailable.')).toBeInTheDocument()
  })
})
