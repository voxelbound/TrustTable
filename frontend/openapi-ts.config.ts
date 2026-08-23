/**
 * `@hey-api/openapi-ts` configuration (FND-05).
 *
 * Generates the committed TypeScript API client under `src/api/` from the
 * backend's OpenAPI schema. The schema is produced directly by
 * `backend/src/trusttable_backend/export_openapi.py` — no live server, no
 * database, no network required — so this file is the single source of
 * truth invoked by `npm run generate:api-types` and by the CI `contract`
 * job's drift check.
 */
import { execFileSync } from 'node:child_process'

import { defineConfig } from '@hey-api/openapi-ts'

export default defineConfig(() => {
  const schemaJson = execFileSync(
    'uv',
    ['run', 'python', '-m', 'trusttable_backend.export_openapi'],
    { cwd: '../backend', encoding: 'utf-8' },
  )

  return {
    input: JSON.parse(schemaJson) as Record<string, unknown>,
    output: 'src/api',
    plugins: [
      '@hey-api/typescript',
      '@hey-api/sdk',
      {
        name: '@hey-api/client-fetch',
        // Relative base URL only: Nginx proxies `/api/v1` to the backend
        // in every deployed environment (docs/architecture.md); no
        // host/port is ever hard-coded here.
        baseUrl: '/api/v1',
      },
    ],
  } as const
})
