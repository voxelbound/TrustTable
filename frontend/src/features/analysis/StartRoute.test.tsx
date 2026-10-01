import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, redirect, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it } from 'vitest'
import { server } from '../../test/msw/server'
import {
  apiErrorBody,
  DEMO_ANALYSIS_ID,
  makeUploadAnalysisResponse,
} from '../../test/msw/handlers'
import { AnalysisLayoutRoute } from './AnalysisLayoutRoute'
import { StartRoute } from './StartRoute'

function renderStartRoute() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/', loader: () => redirect('/analyses/new') },
      { path: '/analyses/new', element: <StartRoute /> },
      {
        path: '/analyses/:analysisId',
        element: <AnalysisLayoutRoute />,
        children: [{ path: 'overview', element: <p>Overview screen</p> }],
      },
    ],
    { initialEntries: ['/'] },
  )

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )

  return router
}

describe('StartRoute', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('AC-01: "/" redirects to "/analyses/new" and renders the Start screen', async () => {
    renderStartRoute()

    expect(
      await screen.findByRole('heading', { name: 'TrustTable' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Try the sales demo' }),
    ).toBeInTheDocument()
  })

  it('AC-01: presents an enabled CSV and Excel upload control', async () => {
    renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    const fileInput = screen.getByLabelText('Choose a file to upload')
    expect(fileInput).toBeEnabled()
    expect(fileInput).toHaveAttribute('accept', '.csv,.xlsx')
    expect(
      screen.getByText(/CSV and Excel \(\.xlsx\) files/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/\.xlsm\) are not supported/i)).toBeInTheDocument()
  })

  it('WP-029: selecting a CSV file uploads it and navigates to the overview route', async () => {
    const user = userEvent.setup()
    const router = renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    const fileInput = screen.getByLabelText('Choose a file to upload')
    const file = new File(['name,amount\nAlice,10\n'], 'sample.csv', {
      type: 'text/csv',
    })
    await user.upload(fileInput, file)

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(
        `/analyses/${DEMO_ANALYSIS_ID}/overview`,
      )
    })
  })

  it('WP-029: a rejected upload shows a safe inline error and does not navigate', async () => {
    // The input's `accept` attribute means `userEvent.upload` will not
    // attach a non-matching file at all — this exercises a server-side
    // rejection (the authoritative check) on an otherwise `.csv`-named
    // file, not a client-side extension mismatch.
    server.use(
      http.post('http://localhost/api/v1/analyses', () => {
        return HttpResponse.json(
          apiErrorBody(
            'FILE_TOO_LARGE',
            'The uploaded file exceeds the maximum allowed size.',
          ),
          { status: 413 },
        )
      }),
    )
    const user = userEvent.setup()
    const router = renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    const fileInput = screen.getByLabelText('Choose a file to upload')
    const file = new File(['name,amount\n'], 'huge.csv', { type: 'text/csv' })
    await user.upload(fileInput, file)

    expect(
      await screen.findByText(
        'The uploaded file exceeds the maximum allowed size.',
      ),
    ).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/analyses/new')
  })

  describe('Excel upload (ING-03)', () => {
    const XLSX_TYPE =
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    const workbookFile = (name = 'book.xlsx') =>
      new File(['PK-not-parsed-in-the-browser'], name, { type: XLSX_TYPE })

    /** Records each `POST /analyses` multipart body and answers with the
     * next queued response (a refusal or the default success). */
    function recordUploads(
      responses: Array<() => Response | Promise<Response>> = [],
    ) {
      // Only the `worksheet` field is recorded: the jsdom `File` is not
      // carried faithfully by the test HTTP layer, so which *file* was sent
      // is proven separately, on the SDK call (`StartRouteWorksheet.test`).
      const seen: Array<{ worksheet: FormDataEntryValue | null }> = []
      server.use(
        http.post('http://localhost/api/v1/analyses', async ({ request }) => {
          const form = await request.formData()
          seen.push({ worksheet: form.get('worksheet') })
          const next = responses[seen.length - 1]
          return next
            ? next()
            : HttpResponse.json(makeUploadAnalysisResponse(), { status: 202 })
        }),
      )
      return seen
    }

    const worksheetRequired = (worksheets: unknown) => () =>
      HttpResponse.json(
        apiErrorBody(
          'WORKSHEET_REQUIRED',
          'The workbook has several worksheets; choose one with the worksheet field.',
          { worksheets },
        ),
        { status: 400 },
      )

    it('sends a CSV upload without any worksheet field', async () => {
      const seen = recordUploads()
      const user = userEvent.setup()
      const router = renderStartRoute()
      await screen.findByRole('heading', { name: 'TrustTable' })

      await user.upload(
        screen.getByLabelText('Choose a file to upload'),
        new File(['a,b\n1,2\n'], 'plain.csv', { type: 'text/csv' }),
      )

      await waitFor(() => {
        expect(router.state.location.pathname).toBe(
          `/analyses/${DEMO_ANALYSIS_ID}/overview`,
        )
      })
      expect(seen).toHaveLength(1)
      expect(seen[0].worksheet).toBeNull()
    })

    it('uploads a single-sheet workbook directly, with no worksheet field and no chooser', async () => {
      const seen = recordUploads()
      const user = userEvent.setup()
      const router = renderStartRoute()
      await screen.findByRole('heading', { name: 'TrustTable' })

      await user.upload(
        screen.getByLabelText('Choose a file to upload'),
        workbookFile(),
      )

      await waitFor(() => {
        expect(router.state.location.pathname).toBe(
          `/analyses/${DEMO_ANALYSIS_ID}/overview`,
        )
      })
      expect(seen).toHaveLength(1)
      expect(seen[0].worksheet).toBeNull()
      expect(screen.queryByRole('group')).not.toBeInTheDocument()
    })

    it('asks which worksheet to analyze and sends exactly the picked one with the same file', async () => {
      const seen = recordUploads([worksheetRequired(['Sales', 'Costs'])])
      const user = userEvent.setup()
      const router = renderStartRoute()
      await screen.findByRole('heading', { name: 'TrustTable' })

      await user.upload(
        screen.getByLabelText('Choose a file to upload'),
        workbookFile('multi.xlsx'),
      )

      const group = await screen.findByRole('group', {
        name: /Which one should be analyzed/i,
      })
      expect(
        within(group)
          .getAllByRole('radio')
          .map((radio) => (radio as HTMLInputElement).value),
      ).toEqual(['Sales', 'Costs'])
      // Nothing is analyzed until a worksheet is picked, and the generic
      // error is not shown for this expected refusal.
      const analyze = screen.getByRole('button', {
        name: 'Analyze this worksheet',
      })
      expect(analyze).toBeDisabled()
      expect(seen).toHaveLength(1)
      expect(router.state.location.pathname).toBe('/analyses/new')
      expect(
        screen.queryByText('Could not analyze the uploaded file'),
      ).not.toBeInTheDocument()

      await user.click(within(group).getByRole('radio', { name: 'Costs' }))
      expect(analyze).toBeEnabled()
      await user.click(analyze)

      await waitFor(() => {
        expect(router.state.location.pathname).toBe(
          `/analyses/${DEMO_ANALYSIS_ID}/overview`,
        )
      })
      expect(seen).toHaveLength(2)
      expect(seen[1].worksheet).toBe('Costs')
      expect(seen[0].worksheet).toBeNull()
    })

    it('shows worksheet names containing markup as inert text', async () => {
      const hostile = '<img src=x onerror=alert(1)>'
      recordUploads([worksheetRequired([hostile, 'Safe'])])
      const user = userEvent.setup()
      renderStartRoute()
      await screen.findByRole('heading', { name: 'TrustTable' })

      await user.upload(
        screen.getByLabelText('Choose a file to upload'),
        workbookFile(),
      )

      const group = await screen.findByRole('group')
      expect(within(group).getByText(hostile)).toBeInTheDocument()
      expect(group.querySelector('img')).toBeNull()
    })

    it('ignores a malformed worksheet list and shows the API message instead of a chooser', async () => {
      recordUploads([worksheetRequired('not-a-list')])
      const user = userEvent.setup()
      renderStartRoute()
      await screen.findByRole('heading', { name: 'TrustTable' })

      await user.upload(
        screen.getByLabelText('Choose a file to upload'),
        workbookFile(),
      )

      expect(screen.queryByRole('group')).not.toBeInTheDocument()
      // `WORKSHEET_REQUIRED` is hidden from the generic alert only when a
      // chooser can resolve it; here nothing can, so the user must see the
      // message rather than get a silent no-op.
      expect(
        await screen.findByText('Could not analyze the uploaded file'),
      ).toBeInTheDocument()
    })

    it.each([
      [
        'MACRO_ENABLED_FILE',
        415,
        'The workbook contains macros and is not supported.',
      ],
      [
        'MALFORMED_FILE',
        400,
        'The file could not be read as a valid .xlsx workbook.',
      ],
      [
        'WORKBOOK_EXPANSION_LIMIT',
        413,
        'The workbook exceeds the size limits once unpacked.',
      ],
    ])(
      'shows the %s refusal inline without a chooser or navigation',
      async (code, status, message) => {
        recordUploads([
          () => HttpResponse.json(apiErrorBody(code, message), { status }),
        ])
        const user = userEvent.setup()
        const router = renderStartRoute()
        await screen.findByRole('heading', { name: 'TrustTable' })

        await user.upload(
          screen.getByLabelText('Choose a file to upload'),
          workbookFile(),
        )

        expect(await screen.findByText(message)).toBeInTheDocument()
        expect(screen.queryByRole('group')).not.toBeInTheDocument()
        expect(router.state.location.pathname).toBe('/analyses/new')
      },
    )

    it('keeps the chooser and shows the message when the picked worksheet is refused', async () => {
      recordUploads([
        worksheetRequired(['Sales', 'Costs']),
        () =>
          HttpResponse.json(
            apiErrorBody(
              'INVALID_REQUEST',
              'The requested worksheet does not exist in the workbook.',
              { worksheets: ['Sales', 'Costs'] },
            ),
            { status: 400 },
          ),
      ])
      const user = userEvent.setup()
      const router = renderStartRoute()
      await screen.findByRole('heading', { name: 'TrustTable' })
      await user.upload(
        screen.getByLabelText('Choose a file to upload'),
        workbookFile(),
      )
      await user.click(await screen.findByRole('radio', { name: 'Sales' }))
      await user.click(
        screen.getByRole('button', { name: 'Analyze this worksheet' }),
      )

      expect(
        await screen.findByText(
          'The requested worksheet does not exist in the workbook.',
        ),
      ).toBeInTheDocument()
      expect(screen.getByRole('group')).toBeInTheDocument()
      expect(router.state.location.pathname).toBe('/analyses/new')
    })

    it('cancelling the chooser removes it and uploads nothing further', async () => {
      const seen = recordUploads([worksheetRequired(['Sales', 'Costs'])])
      const user = userEvent.setup()
      const router = renderStartRoute()
      await screen.findByRole('heading', { name: 'TrustTable' })
      await user.upload(
        screen.getByLabelText('Choose a file to upload'),
        workbookFile(),
      )
      await screen.findByRole('group')

      await user.click(screen.getByRole('button', { name: 'Cancel' }))

      expect(screen.queryByRole('group')).not.toBeInTheDocument()
      expect(seen).toHaveLength(1)
      expect(router.state.location.pathname).toBe('/analyses/new')
    })
  })

  it('AC-01: renders the fixed AI-disabled status', async () => {
    renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    expect(screen.getByText(/AI is disabled/i)).toBeInTheDocument()
  })

  it('AC-02: activating the demo action calls the demo endpoint once and navigates to the overview route', async () => {
    let callCount = 0
    server.use(
      http.post('http://localhost/api/v1/demo/sales', () => {
        callCount += 1
        return HttpResponse.json(
          {
            analysis: {
              analysis_id: DEMO_ANALYSIS_ID,
              state: 'completed',
              dataset: {
                dataset_id: 'd1',
                original_filename: 'sales_demo.csv',
                format: 'csv',
                byte_size: 1,
                content_hash: 'h',
                source_type: 'bundled_demo',
                created_at: '2026-08-30T00:00:00Z',
              },
              security_exposure: {
                model_provider_enabled: false,
                sample_transmission_enabled: false,
              },
              trust_assessment: null,
              finding_count: 0,
              failure: null,
              created_at: '2026-08-30T00:00:00Z',
              started_at: null,
              completed_at: null,
              failed_at: null,
              cancelled_at: null,
            },
            status_url: `/api/v1/analyses/${DEMO_ANALYSIS_ID}/status`,
          },
          { status: 202 },
        )
      }),
    )
    const user = userEvent.setup()
    const router = renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    await user.click(screen.getByRole('button', { name: 'Try the sales demo' }))

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(
        `/analyses/${DEMO_ANALYSIS_ID}/overview`,
      )
    })
    expect(callCount).toBe(1)
  })

  it('renders a safe error message when the demo action fails, without a raw exception', async () => {
    server.use(
      http.post('http://localhost/api/v1/demo/sales', () => {
        return HttpResponse.json(
          apiErrorBody(
            'INTERNAL_ERROR',
            'The demo analysis could not be started.',
          ),
          { status: 500 },
        )
      }),
    )
    const user = userEvent.setup()
    renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    await user.click(screen.getByRole('button', { name: 'Try the sales demo' }))

    expect(
      await screen.findByText('The demo analysis could not be started.'),
    ).toBeInTheDocument()
  })
})
