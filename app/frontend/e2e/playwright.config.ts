import os from 'node:os'
import path from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const outputDir = process.env.BOARD_E2E_OUTPUT_DIR
  ?? path.join(os.tmpdir(), 'career-board-e2e-playwright')

export default defineConfig({
  testDir: '.',
  testMatch: 'agent-fill.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  reporter: [['list']],
  outputDir,
  use: {
    baseURL: 'http://127.0.0.1:8000',
    headless: true,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
