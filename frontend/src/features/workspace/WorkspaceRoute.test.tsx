import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it } from 'vitest'
import { server } from '../../test/msw/server'
import {
  apiErrorBody,
  DEMO_ANALYSIS_ID,
  makeAiStatusResponse,
  makeStagedUploadResponse,
  STAGED_REF,
} from '../../test/msw/handlers'
import { AnalysisLayoutRoute } from '../analysis/AnalysisLayoutRoute'
import {
  forgetStagedReference,
  readStagedReference,
  rememberStagedReference,
} from './stagedReference'
import { WorkspaceRoute } from './WorkspaceRoute'

const BASE = 'http://localhost/api/v1'

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/', element: <WorkspaceRoute /> },
      { path: '/configure', element: <p>Configure screen</p> },
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

/** Counts the calls that would start or create an analysis. */
function watchAnalysisStarts() {
  const calls = { analyses: 0, demo: 0, run: 0, staged: 0 }
  server.use(
    http.post(`${BASE}/analyses`, () => {
      calls.analyses += 1
      return HttpResponse.json({}, { status: 500 })
    }),
    http.post(`${BASE}/demo/sales`, () => {
      calls.demo += 1
      return HttpResponse.json({}, { status: 500 })
    }),
    http.post(`${BASE}/staged-uploads/run`, () => {
      calls.run += 1
      return HttpResponse.json({}, { status: 500 })
    }),
    http.post(`${BASE}/staged-uploads`, () => {
      calls.staged += 1
      return HttpResponse.json(makeStagedUploadResponse(), { status: 201 })
    }),
  )
  return calls
}

const csvFile = (name = 'sample.csv') =>
  new File(['name,amount\nAlice,10\n'], name, { type: 'text/csv' })

describe('WorkspaceRoute', () => {
  beforeEach(() => {
    server.resetHandlers()
    forgetStagedReference()
  })

  it('shows the workspace: choose data, the demo, Local AI status and a disabled Compare area', async () => {
    renderWorkspace()

    expect(
      await screen.findByRole('heading', { name: 'TrustTable' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('region', { name: 'Choose data' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Try the sales demo' }),
    ).toBeEnabled()
    expect(
      await screen.findByRole('region', { name: 'Local AI and privacy' }),
    ).toBeInTheDocument()

    const compare = screen.getByRole('region', { name: /Compare datasets/ })
    expect(compare).toHaveTextContent('Planned')
    expect(compare).toHaveTextContent(
      'Comparing two datasets is planned and is not available yet.',
    )
    const compareButton = screen.getByRole('button', {
      name: 'Compare datasets',
    })
    expect(compareButton).toBeDisabled()
    expect(compareButton).toHaveAccessibleDescription(
      'Comparing two datasets is planned and is not available yet.',
    )
  })

  it('offers a CSV and Excel file picker', async () => {
    renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    const input = screen.getByLabelText('Choose a file to analyze')
    expect(input).toBeEnabled()
    expect(input).toHaveAttribute('accept', '.csv,.xlsx')
    expect(screen.getByText(/Macro-enabled workbooks/)).toBeInTheDocument()
    expect(
      screen.getByText(/does not start an analysis; you will review it first/),
    ).toBeInTheDocument()
  })

  it('choosing a file stages it and opens Configure without starting any analysis', async () => {
    const calls = watchAnalysisStarts()
    const user = userEvent.setup()
    const router = renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    await user.upload(
      screen.getByLabelText('Choose a file to analyze'),
      csvFile(),
    )

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/configure')
    })
    expect(calls.staged).toBe(1)
    expect(calls.analyses).toBe(0)
    expect(calls.demo).toBe(0)
    expect(calls.run).toBe(0)
    // The reference is kept for the tab, and never put in the address.
    expect(readStagedReference()).toBe(STAGED_REF)
    expect(
      `${router.state.location.pathname}${router.state.location.search}${router.state.location.hash}`,
    ).not.toContain(STAGED_REF)
  })

  it('a dropped file is staged the same way and starts nothing', async () => {
    const calls = watchAnalysisStarts()
    const router = renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    fireEvent.drop(screen.getByRole('region', { name: 'Choose data' }), {
      dataTransfer: { files: [csvFile('dropped.csv')] },
    })

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/configure')
    })
    expect(calls.staged).toBe(1)
    expect(calls.analyses + calls.demo + calls.run).toBe(0)
  })

  it('stages only the first of several dropped files', async () => {
    const calls = watchAnalysisStarts()
    const router = renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    fireEvent.drop(screen.getByRole('region', { name: 'Choose data' }), {
      dataTransfer: { files: [csvFile('first.csv'), csvFile('second.csv')] },
    })

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/configure')
    })
    expect(calls.staged).toBe(1)
  })

  it('tells the user, in words, that extra dropped files were ignored', async () => {
    server.use(
      http.post(`${BASE}/staged-uploads`, () =>
        HttpResponse.json(
          makeStagedUploadResponse({
            staging_ref: null,
            expires_at: null,
            shape: null,
            can_run: false,
            problems: [
              {
                code: 'NO_HEADER_ROW',
                message: 'The file has no header row with column names.',
              },
            ],
          }),
        ),
      ),
    )
    renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    fireEvent.drop(screen.getByRole('region', { name: 'Choose data' }), {
      dataTransfer: { files: [csvFile('first.csv'), csvFile('second.csv')] },
    })

    const notice = await screen.findByText(
      'Only one file can be chosen at a time',
    )
    expect(notice.closest('[role="status"]')).toHaveTextContent('first.csv')
    expect(notice.closest('[role="status"]')).toHaveTextContent(
      'Choose the others separately.',
    )
  })

  it('does not show the ignored-files notice for a single dropped file', async () => {
    watchAnalysisStarts()
    renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    fireEvent.drop(screen.getByRole('region', { name: 'Choose data' }), {
      dataTransfer: { files: [csvFile('only.csv')] },
    })

    await waitFor(() => {
      expect(
        screen.queryByText('Only one file can be chosen at a time'),
      ).not.toBeInTheDocument()
    })
  })

  it('shows reading progress while a file is being staged and blocks a second choice', async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.post(`${BASE}/staged-uploads`, async () => {
        await gate
        return HttpResponse.json(makeStagedUploadResponse(), { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    await user.upload(
      screen.getByLabelText('Choose a file to analyze'),
      csvFile(),
    )

    expect(await screen.findByText('Reading the file…')).toBeInTheDocument()
    expect(screen.getByLabelText('Choose a file to analyze')).toBeDisabled()
    release()
  })

  it('lists why an unreadable file was refused, keeps nothing and does not navigate', async () => {
    server.use(
      http.post(`${BASE}/staged-uploads`, () =>
        HttpResponse.json(
          makeStagedUploadResponse({
            staging_ref: null,
            expires_at: null,
            filename: 'latin1.csv',
            shape: null,
            can_run: false,
            problems: [
              {
                code: 'FILE_NOT_UTF8',
                message:
                  'This file does not appear to use UTF-8 text encoding, so TrustTable cannot read it reliably. Save or export it as CSV UTF-8 and choose it again.',
              },
            ],
          }),
          { status: 200 },
        ),
      ),
    )
    const user = userEvent.setup()
    const router = renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    await user.upload(
      screen.getByLabelText('Choose a file to analyze'),
      csvFile('latin1.csv'),
    )

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('TrustTable cannot read this file')
    expect(alert).toHaveTextContent('latin1.csv')
    expect(alert).toHaveTextContent('UTF-8 text encoding')
    expect(alert).toHaveTextContent('Choose a different file to continue.')
    expect(router.state.location.pathname).toBe('/')
    expect(readStagedReference()).toBeNull()
  })

  it('explains a full staging area in plain words, including how long files wait', async () => {
    server.use(
      http.post(`${BASE}/staged-uploads`, () =>
        HttpResponse.json(
          apiErrorBody(
            'STAGING_FULL',
            'Several files are already waiting to be analyzed. Finish or discard one, or wait for them to expire.',
            { ttl_minutes: 45 },
          ),
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    const router = renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    await user.upload(
      screen.getByLabelText('Choose a file to analyze'),
      csvFile(),
    )

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Too many files are waiting')
    expect(alert).toHaveTextContent('up to 45 minutes')
    expect(alert).toHaveTextContent('another tab')
    expect(router.state.location.pathname).toBe('/')
  })

  it('shows a refused file type as the server message without navigating', async () => {
    server.use(
      http.post(`${BASE}/staged-uploads`, () =>
        HttpResponse.json(
          apiErrorBody(
            'UNSUPPORTED_FILE_TYPE',
            'Only .csv and .xlsx files are currently supported.',
          ),
          { status: 415 },
        ),
      ),
    )
    const user = userEvent.setup()
    const router = renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })

    await user.upload(
      screen.getByLabelText('Choose a file to analyze'),
      csvFile(),
    )

    expect(
      await screen.findByText(
        'Only .csv and .xlsx files are currently supported.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Could not read the file',
    )
    expect(router.state.location.pathname).toBe('/')
  })

  it('lets the same file be chosen again after an error', async () => {
    let attempts = 0
    server.use(
      http.post(`${BASE}/staged-uploads`, () => {
        attempts += 1
        return attempts === 1
          ? HttpResponse.json(apiErrorBody('INTERNAL_ERROR', 'Try again.'), {
              status: 500,
            })
          : HttpResponse.json(makeStagedUploadResponse(), { status: 201 })
      }),
    )
    const user = userEvent.setup()
    const router = renderWorkspace()
    await screen.findByRole('heading', { name: 'TrustTable' })
    const input = screen.getByLabelText('Choose a file to analyze')

    await user.upload(input, csvFile())
    await screen.findByRole('alert')
    await user.upload(input, csvFile())

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/configure')
    })
    expect(attempts).toBe(2)
  })

  describe('sales demo', () => {
    it('is a separate, explicit action that starts the demo analysis when pressed', async () => {
      const user = userEvent.setup()
      const router = renderWorkspace()
      await screen.findByRole('heading', { name: 'TrustTable' })
      expect(
        screen.getByText(/starts an analysis of a synthetic sales dataset/),
      ).toBeInTheDocument()

      await user.click(
        screen.getByRole('button', { name: 'Try the sales demo' }),
      )

      await waitFor(() => {
        expect(router.state.location.pathname).toBe(
          `/analyses/${DEMO_ANALYSIS_ID}/overview`,
        )
      })
    })

    it('renders a safe error when the demo cannot be started', async () => {
      server.use(
        http.post(`${BASE}/demo/sales`, () =>
          HttpResponse.json(
            apiErrorBody(
              'INTERNAL_ERROR',
              'The demo analysis could not be started.',
            ),
            { status: 500 },
          ),
        ),
      )
      const user = userEvent.setup()
      renderWorkspace()
      await screen.findByRole('heading', { name: 'TrustTable' })

      await user.click(
        screen.getByRole('button', { name: 'Try the sales demo' }),
      )

      expect(
        await screen.findByText('The demo analysis could not be started.'),
      ).toBeInTheDocument()
    })
  })

  describe('a file already waiting in this tab', () => {
    it('offers to continue with it or discard it, and discarding tells the server', async () => {
      rememberStagedReference(STAGED_REF)
      const discarded: unknown[] = []
      server.use(
        http.post(`${BASE}/staged-uploads/discard`, async ({ request }) => {
          discarded.push(await request.json())
          return new HttpResponse(null, { status: 204 })
        }),
      )
      const user = userEvent.setup()
      renderWorkspace()

      expect(
        await screen.findByText('You have a file waiting'),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('link', { name: 'Continue with it' }),
      ).toHaveAttribute('href', '/configure')

      await user.click(screen.getByRole('button', { name: 'Discard it' }))

      await waitFor(() => {
        expect(discarded).toEqual([{ staging_ref: STAGED_REF }])
      })
      expect(
        screen.queryByText('You have a file waiting'),
      ).not.toBeInTheDocument()
      expect(readStagedReference()).toBeNull()
      // Keyboard and screen-reader users are told it happened.
      const confirmation = screen.getByText('File discarded')
      expect(confirmation.closest('[role="status"]')).toHaveTextContent(
        'The file that was waiting has been discarded.',
      )
    })

    it('shows nothing about a waiting file when there is none', async () => {
      renderWorkspace()
      await screen.findByRole('heading', { name: 'TrustTable' })

      expect(
        screen.queryByText('You have a file waiting'),
      ).not.toBeInTheDocument()
    })
  })

  describe('Local AI status', () => {
    it('states that AI assistance is off, in the server wording, by default', async () => {
      renderWorkspace()

      expect(await screen.findByText('AI assistance: off')).toBeInTheDocument()
      expect(
        screen.getByText(/no dataset content is sent to any model/),
      ).toBeInTheDocument()
    })

    it('does not claim AI is disabled when a runtime is configured and ready', async () => {
      server.use(
        http.get(`${BASE}/ai/status`, () =>
          HttpResponse.json(
            makeAiStatusResponse({
              assistance: 'on',
              state: 'ready',
              location: 'local',
              provider_label: 'Local AI',
              runtime_label: 'llama.cpp',
              model_label: 'Qwen3.5 4B',
              summary:
                'AI assistance is on and the llama.cpp runtime is ready, on this machine.',
            }),
          ),
        ),
      )
      renderWorkspace()

      expect(
        await screen.findByText('AI assistance: on and ready'),
      ).toBeInTheDocument()
      expect(
        screen.getByText('Runtime: llama.cpp · Model: Qwen3.5 4B'),
      ).toBeInTheDocument()
      expect(screen.queryByText(/AI is disabled/i)).not.toBeInTheDocument()
    })
  })
})
