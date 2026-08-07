/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    // Playwright owns frontend/e2e/** (see playwright.config.ts); without
    // this exclude, Vitest's default discovery also matches *.spec.ts
    // there and tries to run Playwright's test() inside Vitest's runner.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
