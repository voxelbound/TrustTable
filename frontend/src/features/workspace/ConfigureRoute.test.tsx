import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it } from 'vitest'
import { server } from '../../test/msw/server'
import {
  apiErrorBody,
  DEMO_ANALYSIS_ID,
  makeStagedUploadResponse,
  makeUploadAnalysisResponse,
  STAGED_REF,
} from '../../test/msw/handlers'
import { AnalysisLayoutRoute } from '../analysis/AnalysisLayoutRoute'
import { ConfigureRoute } from './ConfigureRoute'
import {
  forgetStagedReference,
  readStagedReference,
  rememberStagedReference,
} from './stagedReference'

const BASE = 'http://localhost/api/v1'
const UNAVAILABLE = apiErrorBody(
  'STAGED_UPLOAD_UNAVAILABLE',
  'This file is no longer available. Chosen files are kept only briefly; choose the file again.',
)

function renderConfigure() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/', element: <p>Workspace screen</p> },
      { path: '/configure', element: <ConfigureRoute /> },
      {
        path: '/analyses/:analysisId',
        element: <AnalysisLayoutRoute />,
        children: [{ path: 'overview', element: <p>Overview screen</p> }],
      },
    ],
    { initialEntries: ['/configure'] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const TWO_SHEETS = [
  { name: 'Alpha', visible: true },
  { name: 'Beta', visible: true },
]

/** Answers inspect requests, recording each body, from `answer(worksheet)`. */
function recordInspect(
  answer: (
    worksheet: string | null,
  ) => ReturnType<typeof makeStagedUploadResponse>,
) {
  const seen: Array<{ staging_ref: string; worksheet: string | null }> = []
  server.use(
    http.post(`${BASE}/staged-uploads/inspect`, async ({ request }) => {
      const body = (await request.json()) as {
        staging_ref: string
        worksheet: string | null
      }
      seen.push(body)
      return HttpResponse.json(answer(body.worksheet))
    }),
  )
  return seen
}

describe('ConfigureRoute', () => {
  beforeEach(() => {
    server.resetHandlers()
    forgetStagedReference()
    rememberStagedReference(STAGED_REF)
  })

  it('returns to the workspace when there is no staged file in this tab', async () => {
    forgetStagedReference()
    renderConfigure()

    expect(await screen.findByText('Workspace screen')).toBeInTheDocument()
  })

  it('shows the file facts and says nothing has been analyzed yet', async () => {
    const router = renderConfigure()

    expect(
      await screen.findByRole('heading', { name: 'Review your file' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Nothing has been analyzed yet/),
    ).toBeInTheDocument()
    const facts = await screen.findByRole('region', { name: 'Your file' })
    expect(within(facts).getByText('my-data.csv')).toBeInTheDocument()
    expect(within(facts).getByText('CSV file')).toBeInTheDocument()
    expect(within(facts).getByText('2.0 KB')).toBeInTheDocument()
    expect(within(facts).getByText('120')).toBeInTheDocument()
    expect(within(facts).getByText('5')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/configure')
  })

  it('marks Configure as the current step and focuses the page heading', async () => {
    renderConfigure()

    const heading = await screen.findByRole('heading', {
      name: 'Review your file',
    })
    const steps = screen.getByRole('list', { name: 'Steps' })
    expect(within(steps).getByText('Configure')).toHaveAttribute(
      'aria-current',
      'step',
    )
    expect(within(steps).getByText('Choose data')).not.toHaveAttribute(
      'aria-current',
    )
    await waitFor(() => expect(heading).toHaveFocus())
  })

  it('states how long the temporary copy is kept', async () => {
    renderConfigure()

    expect(
      await screen.findByText(
        /This copy is kept until .* and is then deleted\./,
      ),
    ).toBeInTheDocument()
  })

  it('summarises what is checked by group without detector names or any on/off control', async () => {
    renderConfigure()

    const section = await screen.findByRole('region', {
      name: 'What TrustTable will check',
    })
    // The group titles are listed once; their descriptions sit behind the
    // disclosure (so each title appears again there as a term).
    const titles = within(within(section).getAllByRole('list')[0])
      .getAllByRole('listitem')
      .map((item) => item.textContent)
    expect(titles).toEqual([
      'Missing and empty data',
      'Inconsistent formatting',
    ])
    expect(section).toHaveTextContent('nothing to switch on or off')
    expect(
      within(section).getByText('What each group looks for', {
        selector: 'summary',
      }),
    ).toBeInTheDocument()
    expect(section).toHaveTextContent('Empty rows and values that are missing.')
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(
      /structural\.|completeness\.|detector/i,
    )
  })

  it('shows the honest Local AI status and a privacy statement', async () => {
    renderConfigure()

    expect(
      await screen.findByRole('region', { name: 'Local AI and privacy' }),
    ).toBeInTheDocument()
    expect(await screen.findByText('AI assistance: off')).toBeInTheDocument()
    const privacy = screen.getByRole('region', { name: 'Privacy' })
    expect(privacy).toHaveTextContent(
      'Your file stays on the machine that runs TrustTable.',
    )
    expect(privacy).toHaveTextContent('deleted when you run the analysis')
  })

  it('never shows the reference or any content hash, and keeps the reference out of the address', async () => {
    const router = renderConfigure()
    await screen.findByRole('heading', { name: 'Review your file' })

    expect(document.body.innerHTML).not.toContain(STAGED_REF)
    expect(document.body.textContent).not.toMatch(/hash|sha-?256/i)
    expect(router.state.location.pathname + router.state.location.search).toBe(
      '/configure',
    )
  })

  describe('Run analysis', () => {
    it('analyzes the staged file with the staged reference and opens its overview', async () => {
      const runs: unknown[] = []
      server.use(
        http.post(`${BASE}/staged-uploads/run`, async ({ request }) => {
          runs.push(await request.json())
          return HttpResponse.json(makeUploadAnalysisResponse(), {
            status: 202,
          })
        }),
      )
      const user = userEvent.setup()
      const router = renderConfigure()
      const run = await screen.findByRole('button', { name: 'Run analysis' })
      await waitFor(() => expect(run).toBeEnabled())

      await user.click(run)

      await waitFor(() => {
        expect(router.state.location.pathname).toBe(
          `/analyses/${DEMO_ANALYSIS_ID}/overview`,
        )
      })
      expect(runs).toEqual([{ staging_ref: STAGED_REF, worksheet: null }])
      expect(readStagedReference()).toBeNull()
    })

    it('shows a starting state and disables both actions while the run is submitted', async () => {
      let release: () => void = () => {}
      const gate = new Promise<void>((resolve) => {
        release = resolve
      })
      server.use(
        http.post(`${BASE}/staged-uploads/run`, async () => {
          await gate
          return HttpResponse.json(makeUploadAnalysisResponse(), {
            status: 202,
          })
        }),
      )
      const user = userEvent.setup()
      renderConfigure()
      const run = await screen.findByRole('button', { name: 'Run analysis' })
      await waitFor(() => expect(run).toBeEnabled())

      await user.click(run)

      expect(
        await screen.findByRole('button', { name: 'Starting…' }),
      ).toBeDisabled()
      expect(
        screen.getByRole('button', { name: 'Choose a different file' }),
      ).toBeDisabled()
      release()
    })

    it('is unavailable while the file has a blocking problem, and the problem is announced', async () => {
      recordInspect(() =>
        makeStagedUploadResponse({
          can_run: false,
          problems: [
            {
              code: 'WORKSHEET_UNREADABLE',
              message:
                'This worksheet could not be read as a table with a header row. Choose another worksheet.',
            },
          ],
        }),
      )
      renderConfigure()

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent('This file cannot be analyzed as it is')
      expect(alert).toHaveTextContent('This worksheet could not be read')
      expect(
        screen.getByRole('button', { name: 'Run analysis' }),
      ).toBeDisabled()
    })

    it('shows non-blocking notices and still allows Run', async () => {
      recordInspect(() =>
        makeStagedUploadResponse({
          notices: [
            {
              code: 'parsing.ragged_row',
              message:
                '2 rows have a different number of values than the header row.',
              count: 2,
            },
          ],
        }),
      )
      renderConfigure()

      const notice = await screen.findByText(
        /2 rows have a different number of values/,
      )
      expect(notice).toBeInTheDocument()
      expect(
        screen.getByText('Worth knowing before you run'),
      ).toBeInTheDocument()
      await waitFor(() =>
        expect(
          screen.getByRole('button', { name: 'Run analysis' }),
        ).toBeEnabled(),
      )
    })

    it('shows the same problem text when a Run is refused, keeps the file and allows another try', async () => {
      server.use(
        http.post(`${BASE}/staged-uploads/run`, () =>
          HttpResponse.json(
            apiErrorBody(
              'STAGED_UPLOAD_NOT_RUNNABLE',
              'This file cannot be analyzed as chosen.',
              {
                problems: [
                  {
                    code: 'CELL_LIMIT_EXCEEDED',
                    message:
                      'The workbook exceeds the row, column or cell limits.',
                  },
                ],
              },
            ),
            { status: 400 },
          ),
        ),
      )
      const user = userEvent.setup()
      const router = renderConfigure()
      const run = await screen.findByRole('button', { name: 'Run analysis' })
      await waitFor(() => expect(run).toBeEnabled())

      await user.click(run)

      const alert = await screen.findByText('The analysis was not started')
      expect(alert.closest('[role="alert"]')).toHaveTextContent(
        'The workbook exceeds the row, column or cell limits.',
      )
      expect(readStagedReference()).toBe(STAGED_REF)
      expect(router.state.location.pathname).toBe('/configure')
      expect(screen.getByRole('button', { name: 'Run analysis' })).toBeEnabled()
    })

    it('shows the server message for any other refusal without leaving the page', async () => {
      server.use(
        http.post(`${BASE}/staged-uploads/run`, () =>
          HttpResponse.json(
            apiErrorBody(
              'WORKSHEET_REQUIRED',
              'The workbook has several worksheets; choose one with the worksheet field.',
            ),
            { status: 400 },
          ),
        ),
      )
      const user = userEvent.setup()
      const router = renderConfigure()
      const run = await screen.findByRole('button', { name: 'Run analysis' })
      await waitFor(() => expect(run).toBeEnabled())

      await user.click(run)

      expect(
        await screen.findByText(
          /The workbook has several worksheets; choose one/,
        ),
      ).toBeInTheDocument()
      expect(router.state.location.pathname).toBe('/configure')
    })
  })

  describe('worksheets', () => {
    const twoSheetAnswer = (worksheet: string | null) =>
      makeStagedUploadResponse({
        filename: 'book.xlsx',
        format: 'xlsx',
        worksheets: TWO_SHEETS,
        selected_worksheet: worksheet,
        shape:
          worksheet === null
            ? null
            : { row_count: worksheet === 'Beta' ? 7 : 3, column_count: 4 },
        can_run: worksheet !== null,
      })

    it('preselects nothing for several visible worksheets and blocks Run until one is chosen', async () => {
      recordInspect(twoSheetAnswer)
      renderConfigure()

      const group = await screen.findByRole('group', {
        name: 'Which worksheet should be analyzed?',
      })
      const radios = within(group).getAllByRole('radio') as HTMLInputElement[]
      expect(radios.map((radio) => radio.value)).toEqual(['Alpha', 'Beta'])
      expect(radios.every((radio) => !radio.checked)).toBe(true)
      expect(
        within(group).getByText(/you need to choose one/),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'Run analysis' }),
      ).toBeDisabled()
      expect(screen.getByText('Excel workbook')).toBeInTheDocument()
    })

    it('inspects the chosen worksheet, shows its shape and runs exactly that worksheet', async () => {
      const seen = recordInspect(twoSheetAnswer)
      const runs: unknown[] = []
      server.use(
        http.post(`${BASE}/staged-uploads/run`, async ({ request }) => {
          runs.push(await request.json())
          return HttpResponse.json(makeUploadAnalysisResponse(), {
            status: 202,
          })
        }),
      )
      const user = userEvent.setup()
      const router = renderConfigure()
      const group = await screen.findByRole('group', {
        name: 'Which worksheet should be analyzed?',
      })

      await user.click(within(group).getByRole('radio', { name: 'Beta' }))

      await waitFor(() => {
        expect(seen.at(-1)).toEqual({
          staging_ref: STAGED_REF,
          worksheet: 'Beta',
        })
      })
      const facts = await screen.findByRole('region', { name: 'Your file' })
      await waitFor(() =>
        expect(within(facts).getByText('7')).toBeInTheDocument(),
      )
      const run = screen.getByRole('button', { name: 'Run analysis' })
      await waitFor(() => expect(run).toBeEnabled())
      await user.click(run)

      await waitFor(() => {
        expect(router.state.location.pathname).toBe(
          `/analyses/${DEMO_ANALYSIS_ID}/overview`,
        )
      })
      expect(runs).toEqual([{ staging_ref: STAGED_REF, worksheet: 'Beta' }])
    })

    it('shows a preselected worksheet as chosen when there is only one visible sheet', async () => {
      recordInspect(() =>
        makeStagedUploadResponse({
          format: 'xlsx',
          filename: 'book.xlsx',
          worksheets: [
            { name: 'Data', visible: true },
            { name: 'Scratch', visible: false },
          ],
          selected_worksheet: 'Data',
        }),
      )
      renderConfigure()

      const data = await screen.findByRole('radio', { name: 'Data' })
      expect(data).toBeChecked()
      expect(
        screen.getByRole('radio', { name: 'Scratch (hidden in the workbook)' }),
      ).not.toBeChecked()
      await waitFor(() =>
        expect(
          screen.getByRole('button', { name: 'Run analysis' }),
        ).toBeEnabled(),
      )
    })

    it('shows worksheet names containing markup as inert text', async () => {
      const hostile = '<img src=x onerror=alert(1)>'
      recordInspect(() =>
        makeStagedUploadResponse({
          format: 'xlsx',
          filename: 'book.xlsx',
          worksheets: [
            { name: hostile, visible: true },
            { name: 'Safe', visible: true },
          ],
        }),
      )
      renderConfigure()

      const group = await screen.findByRole('group', {
        name: 'Which worksheet should be analyzed?',
      })
      expect(within(group).getByText(hostile)).toBeInTheDocument()
      expect(group.querySelector('img')).toBeNull()
    })

    it('keeps showing the previous file facts while another worksheet is being read', async () => {
      let release: () => void = () => {}
      const gate = new Promise<void>((resolve) => {
        release = resolve
      })
      server.use(
        http.post(`${BASE}/staged-uploads/inspect`, async ({ request }) => {
          const body = (await request.json()) as { worksheet: string | null }
          if (body.worksheet !== null) {
            await gate
          }
          return HttpResponse.json(twoSheetAnswer(body.worksheet))
        }),
      )
      const user = userEvent.setup()
      renderConfigure()
      const group = await screen.findByRole('group', {
        name: 'Which worksheet should be analyzed?',
      })

      await user.click(within(group).getByRole('radio', { name: 'Alpha' }))

      expect(
        await screen.findByText('Reading the worksheet…'),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('region', { name: 'Your file' }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: 'Run analysis' }),
      ).toBeDisabled()
      release()
    })
  })

  describe('a file that is no longer available', () => {
    it('says so, forgets the reference and offers to choose the file again when inspecting', async () => {
      server.use(
        http.post(`${BASE}/staged-uploads/inspect`, () =>
          HttpResponse.json(UNAVAILABLE, { status: 410 }),
        ),
      )
      const user = userEvent.setup()
      const router = renderConfigure()

      expect(
        await screen.findByRole('heading', {
          name: 'Your file is no longer available',
        }),
      ).toBeInTheDocument()
      expect(screen.getByRole('status')).toHaveTextContent(/kept only briefly/)
      expect(readStagedReference()).toBeNull()

      await user.click(screen.getByRole('button', { name: 'Choose a file' }))
      expect(router.state.location.pathname).toBe('/')
    })

    it('shows the same recovery when the run finds the file gone', async () => {
      server.use(
        http.post(`${BASE}/staged-uploads/run`, () =>
          HttpResponse.json(UNAVAILABLE, { status: 410 }),
        ),
      )
      const user = userEvent.setup()
      renderConfigure()
      const run = await screen.findByRole('button', { name: 'Run analysis' })
      await waitFor(() => expect(run).toBeEnabled())

      await user.click(run)

      expect(
        await screen.findByRole('heading', {
          name: 'Your file is no longer available',
        }),
      ).toBeInTheDocument()
      expect(readStagedReference()).toBeNull()
    })

    it('shows an ordinary error, and keeps the file, when inspecting fails for another reason', async () => {
      server.use(
        http.post(`${BASE}/staged-uploads/inspect`, () =>
          HttpResponse.json(
            apiErrorBody(
              'INTERNAL_ERROR',
              'An internal server error occurred.',
            ),
            {
              status: 500,
            },
          ),
        ),
      )
      renderConfigure()

      expect(
        await screen.findByText('Could not read your file'),
      ).toBeInTheDocument()
      expect(readStagedReference()).toBe(STAGED_REF)
    })
  })

  it('"Choose a different file" discards the staged copy, forgets it and returns to the workspace', async () => {
    const discarded: unknown[] = []
    server.use(
      http.post(`${BASE}/staged-uploads/discard`, async ({ request }) => {
        discarded.push(await request.json())
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    const router = renderConfigure()
    await screen.findByRole('heading', { name: 'Review your file' })

    await user.click(
      screen.getByRole('button', { name: 'Choose a different file' }),
    )

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/')
    })
    expect(discarded).toEqual([{ staging_ref: STAGED_REF }])
    expect(readStagedReference()).toBeNull()
  })
})
