import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../../api'
import { apiErrorBody, DEMO_ANALYSIS_ID } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { StartRoute } from './StartRoute'

/** Proves *which file and which worksheet* the Start screen hands to the
 * generated upload call (`ING-03`). The test HTTP layer cannot carry a
 * jsdom `File` faithfully, so the identity of the `File` object and the
 * `worksheet` argument are asserted on the SDK call itself; the multipart
 * field is covered separately in `StartRoute.test.tsx`. */
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    postAnalysisUploadApiV1AnalysesPost: vi.fn(
      actual.postAnalysisUploadApiV1AnalysesPost,
    ),
  }
})

const upload = vi.mocked(api.postAnalysisUploadApiV1AnalysesPost)

function renderStartRoute() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/analyses/new', element: <StartRoute /> },
      {
        path: '/analyses/:analysisId/overview',
        element: <p>Overview screen</p>,
      },
    ],
    { initialEntries: ['/analyses/new'] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const bodyOf = (call: number) =>
  upload.mock.calls[call][0] as { body: { file: File; worksheet?: string } }

describe('StartRoute worksheet choice', () => {
  beforeEach(() => {
    server.resetHandlers()
    upload.mockClear()
  })

  it('re-sends the very same file with exactly the worksheet the user picked', async () => {
    let attempt = 0
    server.use(
      http.post('http://localhost/api/v1/analyses', () => {
        attempt += 1
        if (attempt === 1) {
          return HttpResponse.json(
            apiErrorBody('WORKSHEET_REQUIRED', 'Choose a worksheet.', {
              worksheets: ['Sales', 'Costs', 'Notes'],
            }),
            { status: 400 },
          )
        }
        return HttpResponse.json(
          { analysis: { analysis_id: DEMO_ANALYSIS_ID } },
          { status: 202 },
        )
      }),
    )
    const user = userEvent.setup()
    const router = renderStartRoute()
    const file = new File(['x'], 'multi.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })

    await user.upload(screen.getByLabelText('Choose a file to upload'), file)
    await user.click(await screen.findByRole('radio', { name: 'Costs' }))
    await user.click(
      screen.getByRole('button', { name: 'Analyze this worksheet' }),
    )

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(
        `/analyses/${DEMO_ANALYSIS_ID}/overview`,
      )
    })
    expect(upload).toHaveBeenCalledTimes(2)
    // First attempt: the file alone, no worksheet guessed.
    expect(bodyOf(0).body.file).toBe(file)
    expect('worksheet' in bodyOf(0).body).toBe(false)
    // Second attempt: the identical File object and the picked worksheet,
    // not the first, the last, or any other entry of the list.
    expect(bodyOf(1).body.file).toBe(file)
    expect(bodyOf(1).body.worksheet).toBe('Costs')
  })

  it('does not call the API again until a worksheet is picked', async () => {
    server.use(
      http.post('http://localhost/api/v1/analyses', () =>
        HttpResponse.json(
          apiErrorBody('WORKSHEET_REQUIRED', 'Choose a worksheet.', {
            worksheets: ['A', 'B'],
          }),
          { status: 400 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderStartRoute()

    await user.upload(
      screen.getByLabelText('Choose a file to upload'),
      new File(['x'], 'multi.xlsx'),
    )
    await screen.findByRole('group')

    expect(upload).toHaveBeenCalledTimes(1)
    expect(
      screen.getByRole('button', { name: 'Analyze this worksheet' }),
    ).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'A' })).not.toBeChecked()
    expect(screen.getByRole('radio', { name: 'B' })).not.toBeChecked()
  })
})
