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
      // P100-B178 (PFL-273): slowapi 对 /login 限流 5/min（生产 DoS 控制）。全量
      // e2e 套件每个 spec 登录一次（beforeAll + afterAll）会超过 5 次触发 429。
      // 镜像 tests/conftest.py 的做法提限 login —— 速率限制不是 e2e 的测试目标。
      command: `RATE_LIMIT_LOGIN=999999/minute .venv/bin/uvicorn src.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
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
