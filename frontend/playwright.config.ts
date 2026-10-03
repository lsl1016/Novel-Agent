import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'

const systemChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

export default defineConfig({
  testDir: './tests',
  testMatch: '*.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: 'http://127.0.0.1:8093',
    launchOptions: {
      executablePath: process.env.CHROME_PATH || (existsSync(systemChrome) ? systemChrome : undefined),
    },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'python3 tests/serve.py',
    url: 'http://127.0.0.1:8093/api/v1/home',
    reuseExistingServer: false,
    timeout: 20000,
  },
})
