import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { client } from '../api/client.gen'
import { server } from './msw/server'

// `globals: false` (vite.config.ts) means Vitest lifecycle hooks must be
// imported explicitly here, matching every test file's own convention.
beforeAll(() => {
  // `features/analysis/api.ts` corrects the generated client's
  // `baseUrl` to `''` at import time (see that file's own comment for
  // the discovered `FND-05` double-`/api/v1` prefix defect this works
  // around) — every generated SDK function's `url` already carries the
  // full `/api/v1/...` path. A bare relative URL only resolves inside a
  // real browser, which supplies `document.baseURI`; Node's `fetch`
  // (used here under Vitest's `jsdom` environment — jsdom itself does
  // not implement `fetch`) rejects it before MSW ever sees the request.
  // Tests only: point the shared client at an absolute origin (no
  // `/api/v1` suffix — `url` already has it) that MSW's Node
  // interceptor matches by default.
  client.setConfig({ baseUrl: 'http://localhost' })
  server.listen({ onUnhandledRequest: 'error' })
})
afterEach(() => {
  server.resetHandlers()
  // `globals: false` (vite.config.ts) means `@testing-library/react`'s
  // automatic per-test DOM cleanup (which relies on detecting a global
  // `afterEach`) never registers itself — without this, renders from
  // every test in a file accumulate in `document.body`, producing
  // false "multiple elements" failures and stale-button clicks in
  // later tests.
  cleanup()
})
afterAll(() => server.close())
