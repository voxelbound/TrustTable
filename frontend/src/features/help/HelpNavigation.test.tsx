import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ContextRoute } from '../analysis/ContextRoute'
import { HelpRoute } from './HelpRoute'

describe('Context to Help navigation', () => {
  const scrolled: string[] = []

  beforeEach(() => {
    scrolled.length = 0
    // jsdom does not implement scrolling; record which element is scrolled to.
    Element.prototype.scrollIntoView = vi.fn(function (this: Element) {
      scrolled.push(this.id)
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
  })

  function renderApp(initialPath: string) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const router = createMemoryRouter(
      [
        { path: '/analyses/:analysisId/context', element: <ContextRoute /> },
        { path: '/help', element: <HelpRoute /> },
      ],
      { initialEntries: [initialPath] },
    )
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )
    return router
  }

  it('UX-07: "What do the sources mean?" lands on and scrolls to the provenance section', async () => {
    const user = userEvent.setup()
    const router = renderApp('/analyses/nav-under-test/context')

    await user.click(
      await screen.findByRole('link', { name: 'What do the sources mean?' }),
    )

    expect(router.state.location.pathname).toBe('/help')
    expect(router.state.location.hash).toBe('#provenance')
    await waitFor(() => expect(scrolled).toContain('provenance'))
    expect(scrolled).not.toContain('findings-and-observations')
  })

  it('opening Help without a hash scrolls nowhere', async () => {
    renderApp('/help')

    await screen.findByRole('heading', { name: 'Help' })
    expect(scrolled).toEqual([])
  })

  it('a malformed hash does not fail the screen', async () => {
    renderApp('/help#%')

    await screen.findByRole('heading', { name: 'Help' })
    expect(scrolled).toEqual([])
  })

  it('a hash that names no topic scrolls nowhere and does not fail', async () => {
    renderApp('/help#no-such-topic')

    await screen.findByRole('heading', { name: 'Help' })
    expect(scrolled).toEqual([])
  })
})
