import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AppShell } from './AppShell'

function renderShell(
  props: { datasetName?: string; statusText?: string } = {},
) {
  render(
    <MemoryRouter>
      <AppShell {...props}>
        <p>Page content</p>
      </AppShell>
    </MemoryRouter>,
  )
}

describe('AppShell navigation', () => {
  it('offers Home and shows Compare datasets as disabled and planned', () => {
    renderShell()

    const nav = screen.getByRole('navigation', { name: 'Workspace' })
    expect(within(nav).getByRole('link', { name: 'Home' })).toHaveAttribute(
      'href',
      '/',
    )
    const compare = within(nav).getByText('Compare datasets').closest('li')
    expect(compare).toHaveAttribute('aria-disabled', 'true')
    expect(compare).toHaveTextContent('Planned')
    // A disabled, planned entry is not a link or a button anyone can activate.
    expect(
      within(nav).queryByRole('link', { name: /Compare/ }),
    ).not.toBeInTheDocument()
    expect(within(nav).queryByRole('button')).not.toBeInTheDocument()
  })

  it('does not present capabilities that are not built', () => {
    renderShell()

    const nav = screen.getByRole('navigation', { name: 'Workspace' })
    for (const unbuilt of ['Analyses', 'Settings', 'Help']) {
      expect(within(nav).queryByText(unbuilt)).not.toBeInTheDocument()
    }
  })

  it('still shows the dataset name and status on an analysis route', () => {
    renderShell({ datasetName: 'sales.csv', statusText: 'Completed' })

    expect(screen.getByText('sales.csv')).toBeInTheDocument()
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText('Page content')).toBeInTheDocument()
  })
})
