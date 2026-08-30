import { setupServer } from 'msw/node'
import { handlers } from './handlers'

/** Node MSW server for Vitest (`UI-01`, `WP-025`'s first real use of the
 * already-installed `msw` dev dependency, `FND-01`). Wired into the
 * Vitest lifecycle in `test/setup.ts`. */
export const server = setupServer(...handlers)
