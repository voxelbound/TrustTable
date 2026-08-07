import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PlaceholderRoute } from './PlaceholderRoute'

function renderWithProviders() {
  const queryClient = new QueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <PlaceholderRoute />
    </QueryClientProvider>,
  )
}

describe('PlaceholderRoute', () => {
  it('renders the placeholder heading and form', async () => {
    renderWithProviders()

    expect(
      await screen.findByRole('heading', { name: 'TrustTable' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('form', { name: 'placeholder form' }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Placeholder field')).toBeInTheDocument()
  })

  it('resolves the TanStack Query placeholder status', async () => {
    renderWithProviders()

    expect(
      await screen.findByText('Repository foundation is running.'),
    ).toBeInTheDocument()
  })
})
