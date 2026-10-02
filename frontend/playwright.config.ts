import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const python = process.env.WELD_TEST_PYTHON || resolve(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
// Isolate fake servers when the user's normal dev server is already running.
const frontendPort=Number(process.env.WELD_TEST_FRONTEND_PORT||5174);
const backendPort=Number(process.env.WELD_TEST_BACKEND_PORT||8001);
const frontendURL=`http://127.0.0.1:${frontendPort}`;
const backendURL=`http://127.0.0.1:${backendPort}`;

export default defineConfig({
  testDir: './e2e',
  // A fresh directory avoids recursive cleanup of a prior run on this Windows host.
  outputDir: `test-results/runs/${Date.now()}`,
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  reporter: 'list',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: frontendURL,
    viewport: { width: 1440, height: 1080 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: process.env.WELD_TEST_BROWSER ? { executablePath: process.env.WELD_TEST_BROWSER } : {},
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn tests.agent_e2e_app:create_test_app --factory --host 127.0.0.1 --port ${backendPort}`,
      cwd: root,
      env: { WELD_STORAGE_DIR: resolve(root, `.cache/e2e-storage/${Date.now()}`), WELD_CORS_ORIGINS: frontendURL },
      url: `${backendURL}/api/health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `npm run dev -- --port ${frontendPort}`,
      env: { VITE_API_PROXY_TARGET: backendURL },
      url: frontendURL,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
