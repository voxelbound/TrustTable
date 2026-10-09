import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it } from 'vitest'
import { server } from '../../test/msw/server'
import {
  apiErrorBody,
  makeHistoryItem,
  makeHistoryResponse,
  makeUploadAnalysisResponse,
} from '../../test/msw/handlers'
import { RecentAnalyses } from './RecentAnalyses'

const BASE = 'http://localhost/api/v1'

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/', element: <RecentAnalyses /> },
      { path: '/analyses/:analysisId', element: <p>Analysis screen</p> },
      {
        path: '/analyses/:analysisId/overview',
        element: <p>Overview screen</p>,
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

function serveHistory(items = [makeHistoryItem()]) {
  const live = [...items]
  server.use(
    http.get(`${BASE}/analyses`, () =>
      HttpResponse.json(makeHistoryResponse(live)),
    ),
  )
  return live
}

describe('RecentAnalyses', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('says so when there are no analyses yet', async () => {
    renderList()
    expect(await screen.findByText(/No analyses yet/)).toBeInTheDocument()
  })

  it('lists recent analyses with plain-language state, never a fingerprint', async () => {
    serveHistory([
      makeHistoryItem({ analysis_id: 'a-1', original_filename: 'sales.csv' }),
      makeHistoryItem({
        analysis_id: 'a-2',
        original_filename: 'broken.csv',
        state: 'failed',
        trust_label: null,
        finding_count: null,
      }),
    ])
    renderList()

    const first = await screen.findByText('sales.csv')
    expect(first).toBeInTheDocument()
    expect(screen.getByText(/Finished · 3 findings/)).toBeInTheDocument()
    expect(screen.getByText(/Did not finish/)).toBeInTheDocument()
    expect(screen.getByText(/Trust: Needs review/)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/hash|sha/i)
  })

  it('shows file names as plain text, never as markup', async () => {
    serveHistory([
      makeHistoryItem({
        original_filename: '<img src=x onerror=alert(1)>.csv',
      }),
    ])
    renderList()
    expect(
      await screen.findByText('<img src=x onerror=alert(1)>.csv'),
    ).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })

  it('opens a finished analysis on its overview', async () => {
    serveHistory([makeHistoryItem({ analysis_id: 'a-1' })])
    const router = renderList()
    await userEvent.click(
      await screen.findByRole('link', { name: 'Open sales.csv' }),
    )
    expect(router.state.location.pathname).toBe('/analyses/a-1/overview')
  })

  it('opens an unfinished analysis on its progress view and offers no rerun', async () => {
    serveHistory([
      makeHistoryItem({
        analysis_id: 'a-9',
        state: 'parsing',
        trust_label: null,
      }),
    ])
    renderList()
    const open = await screen.findByRole('link', { name: 'Open sales.csv' })
    expect(open).toHaveAttribute('href', '/analyses/a-9')
    expect(
      screen.queryByRole('button', { name: 'Run sales.csv again' }),
    ).not.toBeInTheDocument()
  })

  it('runs an analysis again as a new analysis and opens it', async () => {
    serveHistory([makeHistoryItem({ analysis_id: 'a-1' })])
    let rerunOf: string | null = null
    server.use(
      http.post(`${BASE}/analyses/:analysisId/rerun`, ({ params }) => {
        rerunOf = String(params.analysisId)
        return HttpResponse.json(
          makeUploadAnalysisResponse({
            analysis: {
              ...makeUploadAnalysisResponse().analysis,
              analysis_id: 'a-new',
            },
          }),
          { status: 202 },
        )
      }),
    )
    const router = renderList()

    await userEvent.click(
      await screen.findByRole('button', { name: 'Run sales.csv again' }),
    )

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/analyses/a-new'),
    )
    expect(rerunOf).toBe('a-1')
  })

  it('reports a rerun that is refused', async () => {
    serveHistory([makeHistoryItem()])
    server.use(
      http.post(`${BASE}/analyses/:analysisId/rerun`, () =>
        HttpResponse.json(
          apiErrorBody(
            'ANALYSIS_NOT_RERUNNABLE',
            'This analysis is still running.',
          ),
          { status: 409 },
        ),
      ),
    )
    renderList()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Run sales.csv again' }),
    )
    expect(
      await screen.findByText('That action could not be completed'),
    ).toBeInTheDocument()
  })

  it('asks before deleting, deletes only on confirmation, and refreshes the list', async () => {
    const live = serveHistory([makeHistoryItem({ analysis_id: 'a-1' })])
    let deleted: string | null = null
    server.use(
      http.delete(`${BASE}/analyses/:analysisId`, ({ params }) => {
        deleted = String(params.analysisId)
        live.length = 0
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderList()

    await userEvent.click(
      await screen.findByRole('button', { name: 'Delete sales.csv' }),
    )
    const dialog = await screen.findByRole('alertdialog')
    expect(deleted).toBeNull()
    expect(dialog).toHaveTextContent(/no longer recognise the file as analysed/)

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Delete permanently' }),
    )

    expect(await screen.findByText(/No analyses yet/)).toBeInTheDocument()
    expect(deleted).toBe('a-1')
  })

  it('does nothing when the deletion is cancelled', async () => {
    serveHistory([makeHistoryItem()])
    let calls = 0
    server.use(
      http.delete(`${BASE}/analyses/:analysisId`, () => {
        calls += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderList()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Delete sales.csv' }),
    )
    await userEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Cancel',
      }),
    )
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(calls).toBe(0)
    expect(screen.getByText('sales.csv')).toBeInTheDocument()
  })

  it('reports a list that cannot be loaded', async () => {
    server.use(
      http.get(`${BASE}/analyses`, () =>
        HttpResponse.json(apiErrorBody('INTERNAL_ERROR', 'Something failed.'), {
          status: 500,
        }),
      ),
    )
    renderList()
    expect(
      await screen.findByText('Could not load your analyses'),
    ).toBeInTheDocument()
  })
})
