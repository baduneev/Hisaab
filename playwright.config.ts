import { defineConfig, devices } from '@playwright/test';
const hostedURL = process.env.HISAAB_WEB_URL;
export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1,
  use: { baseURL: hostedURL || 'http://127.0.0.1:5188', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: hostedURL ? undefined : { command: 'npm run dev', url: 'http://127.0.0.1:5188', reuseExistingServer: !process.env.CI },
});
