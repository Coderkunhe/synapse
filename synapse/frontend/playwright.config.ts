import { defineConfig } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const configDir = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND_PORT = 5173
const BACKEND_PORT = 8000
const CI = !!process.env.CI

export default defineConfig({
  testDir: './e2e',
  // Real-time/state assertions → serial is more stable than parallel.
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: 'list',
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: 'on-first-retry',
  },
  webServer: [
    {
      command: `.venv/bin/uvicorn src.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: path.resolve(configDir, '..'),
      url: `http://localhost:${BACKEND_PORT}/health`,
      reuseExistingServer: !CI,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      cwd: configDir,
      url: `http://localhost:${FRONTEND_PORT}`,
      reuseExistingServer: !CI,
      timeout: 60_000,
    },
  ],
})
