import { describe, expect, it } from 'vitest'

/**
 * Unsafe-HTML-rendering regression guard (SEC-01, scoped, WP-032).
 *
 * `docs/security-threat-model.md` §3.2 ("Content execution") requires
 * "never use unsafe HTML rendering" as a mitigation against uploaded
 * dataset content (untrusted: filenames, worksheet names, column names,
 * cell values, user descriptions) being interpreted as HTML/JavaScript.
 * Confirmed absent by direct grep before this package (2026-09-08); this
 * test makes that a durable, always-on regression guard rather than a
 * one-time manual check.
 *
 * Uses Vite's `import.meta.glob` (not Node's `fs`) so this file needs no
 * Node type dependency beyond what `vite/client` already provides.
 * Excludes the generated `src/api/` OpenAPI client (never hand-edited,
 * `FND-05`) and test files themselves.
 */

const sourceFiles = import.meta.glob(
  ['../../**/*.{ts,tsx}', '!../../api/**', '!../../**/*.test.{ts,tsx}'],
  { query: '?raw', import: 'default', eager: true },
) as Record<string, string>

const FORBIDDEN_SUBSTRING = 'dangerouslySetInnerHTML'

describe('no unsafe HTML rendering', () => {
  it('never uses dangerouslySetInnerHTML anywhere under src/ (excluding the generated api/ client)', () => {
    const paths = Object.keys(sourceFiles)
    expect(paths.length).toBeGreaterThan(0)

    const offenders = paths.filter((path) =>
      sourceFiles[path].includes(FORBIDDEN_SUBSTRING),
    )

    expect(offenders).toEqual([])
  })
})
