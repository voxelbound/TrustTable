import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { HelpRoute } from './HelpRoute'

function renderHelp() {
  render(
    <MemoryRouter initialEntries={['/help']}>
      <HelpRoute />
    </MemoryRouter>,
  )
}

describe('HelpRoute', () => {
  it('UX-07: explains findings versus observations', () => {
    renderHelp()

    const section = screen
      .getByRole('heading', { name: 'Findings and observations' })
      .closest('section') as HTMLElement
    expect(
      within(section).getByText(/A finding is a data-quality/),
    ).toBeVisible()
    expect(
      within(section).getByText(/never changes the trust assessment/),
    ).toBeVisible()
  })

  it('UX-07: states that the trust assessment is not AI and does not prove correctness', () => {
    renderHelp()

    const section = screen
      .getByRole('heading', { name: 'The trust assessment' })
      .closest('section') as HTMLElement
    expect(within(section).getByText(/not by AI/)).toBeVisible()
    expect(
      within(section).getByText(/does not prove that the data is correct/),
    ).toBeVisible()
  })

  it('UX-07: describes the five provenance labels and says a source is not a statement of correctness', () => {
    renderHelp()

    const section = screen
      .getByRole('heading', { name: 'Where a statement comes from' })
      .closest('section') as HTMLElement
    for (const label of [
      /^Calculated:/,
      /^Deterministic fallback:/,
      /^AI interpretation:/,
      /^Confirmed by user and Corrected by user:/,
    ]) {
      expect(within(section).getByText(label)).toBeVisible()
    }
    expect(
      within(section).getByText(/It is a suggestion, not a verified fact/),
    ).toBeVisible()
    expect(
      within(section).getByText(/does not say that the statement is right/),
    ).toBeVisible()
  })

  it('UX-07: describes sampled and full without claiming a sample covers every row', () => {
    renderHelp()

    const section = screen
      .getByRole('heading', { name: 'Sampled and full' })
      .closest('section') as HTMLElement
    expect(
      within(section).getByText(/describes only the rows it covered/),
    ).toBeVisible()
  })

  it('UX-07: says AI is optional and separate, and that rules are not applied elsewhere or editable here', () => {
    renderHelp()

    expect(screen.getByText(/AI is optional and separate/)).toBeVisible()
    expect(
      screen.getByText(
        /does not apply them to later files or to other datasets/,
      ),
    ).toBeVisible()
    expect(screen.getByText(/cannot be created or edited here/)).toBeVisible()
  })

  it('UX-07: makes no claim the product cannot support', () => {
    renderHelp()

    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(
      /\b(guarantee|guaranteed|verified by AI|always correct)\b/i,
    )
  })

  it('offers an in-page link to every topic', () => {
    renderHelp()

    const nav = screen.getByRole('navigation', { name: 'Help topics' })
    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '#findings-and-observations',
      '#trust-assessment',
      '#provenance',
      '#sampled-and-full',
      '#ai',
      '#rules',
    ])
  })
})
