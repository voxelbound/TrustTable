import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { setAdvancedMode } from '../../lib/advancedMode'
import { makeAdvancedSettings, makeSettingItem } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { SettingsRoute } from './SettingsRoute'

const SETTINGS = 'http://localhost/api/v1/settings'
const ADVANCED = 'http://localhost/api/v1/settings/advanced'
const ONE = 'http://localhost/api/v1/settings/:key'

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/settings']}>
        <SettingsRoute />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function serveSettings(item = makeSettingItem()) {
  server.use(http.get(SETTINGS, () => HttpResponse.json({ settings: [item] })))
}

/** The "Now: On/Off · source" line of the AI assistance setting. */
function nowLine(): HTMLElement {
  return screen.getByText(/Now:/).closest('p') as HTMLElement
}

function envelope(code: string, message: string, details = {}) {
  return { error: { code, message, details, request_id: 'req-1' } }
}

describe('SettingsRoute', () => {
  it('UX-09: points to the Local AI screen from the AI assistance setting', async () => {
    serveSettings()
    renderSettings()

    const section = (
      await screen.findByRole('heading', { name: 'AI assistance' })
    ).closest('section') as HTMLElement
    expect(
      within(section).getByRole('link', { name: 'Local AI' }),
    ).toHaveAttribute('href', '/local-ai')
  })

  it('UX-08b: explains AI assistance and shows the built-in default with its source', async () => {
    serveSettings()
    renderSettings()

    const section = (
      await screen.findByRole('heading', { name: 'AI assistance' })
    ).closest('section') as HTMLElement
    expect(within(section).getByText('What it controls')).toBeVisible()
    expect(within(section).getByText('Why you might change it')).toBeVisible()
    expect(within(section).getByText('What changes')).toBeVisible()
    expect(
      within(section).getByText(/When it is off, nothing is sent/),
    ).toBeVisible()
    expect(section).toHaveTextContent('Now: Off')
    expect(section).toHaveTextContent('The built-in default')
    expect(
      within(section).getByRole('checkbox', { name: 'Use AI assistance' }),
    ).not.toBeChecked()
    // Nothing is stored, so there is nothing to reset.
    expect(
      within(section).queryByRole('button', { name: /Reset/ }),
    ).not.toBeInTheDocument()
  })

  it('UX-08b: writes the new value with the version it was showing and shows what the server returned', async () => {
    const user = userEvent.setup()
    serveSettings(makeSettingItem({ version: 4 }))
    let body: unknown = null
    server.use(
      http.put(ONE, async ({ request, params }) => {
        body = { key: params.key, ...((await request.json()) as object) }
        return HttpResponse.json(
          makeSettingItem({ value: true, source: 'stored', version: 5 }),
        )
      }),
    )
    renderSettings()

    await user.click(
      await screen.findByRole('checkbox', { name: 'Use AI assistance' }),
    )

    expect(body).toEqual({
      key: 'ai_assistance',
      value: true,
      expected_version: 4,
    })
    await waitFor(() => expect(nowLine()).toHaveTextContent('Now: On'))
    expect(
      screen.getByText(/Saved in TrustTable for this installation/),
    ).toBeVisible()
    expect(
      screen.getByRole('checkbox', { name: 'Use AI assistance' }),
    ).toBeChecked()
    expect(
      screen.getByRole('button', { name: 'Reset to default (off)' }),
    ).toBeVisible()
  })

  it('UX-08b: a stale version changes nothing, says so and shows the value the server holds now', async () => {
    const user = userEvent.setup()
    let reads = 0
    server.use(
      http.get(SETTINGS, () => {
        reads += 1
        return HttpResponse.json({
          settings: [
            reads === 1
              ? makeSettingItem({ version: 2 })
              : makeSettingItem({ value: true, source: 'stored', version: 3 }),
          ],
        })
      }),
      http.put(ONE, () =>
        HttpResponse.json(
          envelope('SETTING_VERSION_CONFLICT', 'Stale.', {
            current_version: 3,
          }),
          { status: 409 },
        ),
      ),
    )
    renderSettings()

    await user.click(
      await screen.findByRole('checkbox', { name: 'Use AI assistance' }),
    )

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The setting was not changed')
    expect(alert).toHaveTextContent(
      'changed somewhere else, so nothing was changed',
    )
    // The screen now shows what the server holds, not what was asked for.
    await waitFor(() => expect(nowLine()).toHaveTextContent('Now: On'))
    expect(
      screen.getByRole('checkbox', { name: 'Use AI assistance' }),
    ).toBeChecked()
  })

  it('UX-08b: resets a stored value with the version and shows the default again', async () => {
    const user = userEvent.setup()
    serveSettings(
      makeSettingItem({ value: true, source: 'stored', version: 6 }),
    )
    let url: URL | null = null
    server.use(
      http.delete(ONE, ({ request }) => {
        url = new URL(request.url)
        return HttpResponse.json(makeSettingItem({ version: 7 }))
      }),
    )
    renderSettings()

    await user.click(
      await screen.findByRole('button', { name: 'Reset to default (off)' }),
    )

    expect(url).not.toBeNull()
    expect((url as unknown as URL).searchParams.get('expected_version')).toBe(
      '6',
    )
    await waitFor(() => expect(nowLine()).toHaveTextContent('Now: Off'))
    expect(nowLine()).toHaveTextContent('The built-in default')
    expect(
      screen.queryByRole('button', { name: /Reset/ }),
    ).not.toBeInTheDocument()
  })

  it('UX-08b: a setting managed by the installation is read-only, with the server reason and no control', async () => {
    serveSettings(
      makeSettingItem({
        value: true,
        source: 'deployment',
        managed_by_installation: true,
        note: 'Managed by your installation: LLM_PROVIDER is set.',
      }),
    )
    renderSettings()

    const section = (
      await screen.findByRole('heading', { name: 'AI assistance' })
    ).closest('section') as HTMLElement
    expect(section).toHaveTextContent('Now: On')
    expect(section).toHaveTextContent('Set by your installation')
    expect(
      within(section).getByText(
        'Managed by your installation: LLM_PROVIDER is set.',
      ),
    ).toBeVisible()
    expect(
      within(section).getByText(/cannot be changed from this screen/),
    ).toBeVisible()
    expect(within(section).queryByRole('checkbox')).not.toBeInTheDocument()
    expect(within(section).queryByRole('button')).not.toBeInTheDocument()
  })

  it('UX-08b: a managed refusal on write changes nothing and says so', async () => {
    const user = userEvent.setup()
    serveSettings()
    server.use(
      http.put(ONE, () =>
        HttpResponse.json(
          envelope('SETTING_MANAGED_BY_INSTALLATION', 'Managed.'),
          { status: 409 },
        ),
      ),
    )
    renderSettings()

    await user.click(
      await screen.findByRole('checkbox', { name: 'Use AI assistance' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Your installation manages this setting, so nothing was changed',
    )
    expect(
      screen.getByRole('checkbox', { name: 'Use AI assistance' }),
    ).not.toBeChecked()
  })

  it('UX-08b: any other failed write says nothing was changed and never shows the requested value', async () => {
    const user = userEvent.setup()
    serveSettings()
    server.use(
      http.put(ONE, () =>
        HttpResponse.json(envelope('INTERNAL_ERROR', 'The store is busy.'), {
          status: 500,
        }),
      ),
    )
    renderSettings()

    await user.click(
      await screen.findByRole('checkbox', { name: 'Use AI assistance' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The store is busy. Nothing was changed.',
    )
    expect(nowLine()).toHaveTextContent('Now: Off')
  })

  it('UX-08b: shows the server note when on with no usable local runtime, as the server states it', async () => {
    serveSettings(
      makeSettingItem({
        value: true,
        source: 'stored',
        version: 1,
        note: 'AI assistance is on but unavailable: no runtime is set up.',
      }),
    )
    renderSettings()

    expect(
      await screen.findByText(
        'AI assistance is on but unavailable: no runtime is set up.',
      ),
    ).toBeVisible()
  })

  it('UX-08b: says so when the settings cannot be loaded', async () => {
    server.use(
      http.get(SETTINGS, () =>
        HttpResponse.json(envelope('INTERNAL_ERROR', 'Down.'), { status: 500 }),
      ),
    )
    renderSettings()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load the settings',
    )
    expect(
      screen.queryByRole('checkbox', { name: 'Use AI assistance' }),
    ).not.toBeInTheDocument()
  })

  it('UX-08b: Normal mode never requests or shows the runtime and model', async () => {
    let requested = 0
    serveSettings()
    server.use(
      http.get(ADVANCED, () => {
        requested += 1
        return HttpResponse.json(makeAdvancedSettings())
      }),
    )
    renderSettings()
    await screen.findByRole('heading', { name: 'AI assistance' })

    expect(requested).toBe(0)
    expect(
      screen.getByRole('checkbox', { name: /Show technical detail/ }),
    ).not.toBeChecked()
    expect(screen.queryByText(/Runtime and model/)).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/localhost:8081|qwen-test/)
  })

  it('UX-08b: Advanced mode requests and shows the runtime and model as text, and turning it off hides them again', async () => {
    const user = userEvent.setup()
    serveSettings()
    server.use(
      http.get(ADVANCED, () =>
        HttpResponse.json(
          makeAdvancedSettings({
            model_identifier: '<img src=x onerror=alert(1)>',
          }),
        ),
      ),
    )
    renderSettings()

    await user.click(
      await screen.findByRole('checkbox', { name: /Show technical detail/ }),
    )

    const section = (
      await screen.findByRole('heading', { name: /Runtime and model/ })
    ).closest('section') as HTMLElement
    expect(
      await within(section).findByText('http://localhost:8081'),
    ).toBeVisible()
    expect(
      within(section).getByText('<img src=x onerror=alert(1)>'),
    ).toBeVisible()
    expect(section.querySelector('img')).toBeNull()
    expect(
      within(section).getByText('Example values sent to a model'),
    ).toBeVisible()
    expect(window.localStorage.getItem('trusttable.advanced-mode')).toBe('true')

    await user.click(
      screen.getByRole('checkbox', { name: /Show technical detail/ }),
    )

    expect(screen.queryByText(/Runtime and model/)).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/localhost:8081/)
    expect(window.localStorage.getItem('trusttable.advanced-mode')).toBe(
      'false',
    )
  })

  it('UX-08b: when storage can be read but not written, the Advanced switch still shows and applies the chosen mode', async () => {
    const user = userEvent.setup()
    serveSettings()
    server.use(
      http.get(ADVANCED, () => HttpResponse.json(makeAdvancedSettings())),
    )
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota', 'QuotaExceededError')
    })
    renderSettings()

    const toggle = await screen.findByRole('checkbox', {
      name: /Show technical detail/,
    })
    await user.click(toggle)

    expect(toggle).toBeChecked()
    expect(
      await screen.findByRole('heading', { name: /Runtime and model/ }),
    ).toBeVisible()

    await user.click(toggle)

    expect(toggle).not.toBeChecked()
    expect(screen.queryByText(/Runtime and model/)).not.toBeInTheDocument()
    vi.restoreAllMocks()
  })

  it('UX-08b: a stored Advanced choice applies on the next visit', async () => {
    setAdvancedMode(true)
    serveSettings()
    server.use(
      http.get(ADVANCED, () => HttpResponse.json(makeAdvancedSettings())),
    )
    renderSettings()

    expect(
      await screen.findByRole('checkbox', { name: /Show technical detail/ }),
    ).toBeChecked()
    expect(await screen.findByText('qwen-test.gguf')).toBeVisible()
  })

  it('UX-08b: states that Advanced mode is a display choice and not a security control', async () => {
    serveSettings()
    renderSettings()

    expect(
      await screen.findByText(/it is not a security control/),
    ).toBeVisible()
    expect(screen.getByText(/kept in this browser only/)).toBeVisible()
  })

  it('UX-08b: a failed runtime request is stated and does not hide the settings', async () => {
    setAdvancedMode(true)
    serveSettings()
    server.use(
      http.get(ADVANCED, () =>
        HttpResponse.json(envelope('INTERNAL_ERROR', 'No.'), { status: 500 }),
      ),
    )
    renderSettings()

    expect(
      await screen.findByText('Could not load the runtime and model'),
    ).toBeVisible()
    expect(
      screen.getByRole('checkbox', { name: 'Use AI assistance' }),
    ).toBeVisible()
  })
})
