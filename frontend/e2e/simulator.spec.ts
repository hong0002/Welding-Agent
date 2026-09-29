import { expect, test } from '@playwright/test';
import type { SimulatorStatus } from '../src/types';

test('independent simulator buttons, readiness, results and API failure', async ({ page }) => {
  let status: SimulatorStatus = {
    state: 'STOPPED', configured: true, configuration_errors: [], sample_configuration_errors: [],
    error: null, can_start: true, can_run_sample: false, can_stop: false,
    simulator_pid: null, sample_pid: null, sample_id: 'L_PR_03_0001',
    sample_mode: 'existing_vla_prediction', latest_sample: null, preview_connected: false,
    robot_execution_enabled: false, readiness: 'current_process_stdout_ready_message', session_dir: null,
  };
  const actions: string[] = [];
  let rejectSample = false;
  await page.route('**/api/simulator/**', async (route) => {
    const action = new URL(route.request().url()).pathname.split('/').at(-1)!;
    if (route.request().method() === 'POST') {
      actions.push(action);
      expect(route.request().postDataJSON()).toEqual({});
      if (action === 'start') status = { ...status, state: 'STARTING', can_start: false, can_stop: true, simulator_pid: 1234 };
      if (action === 'run-sample') {
        if (rejectSample) return route.fulfill({ status: 409, json: { detail: 'Simulator must be READY' } });
        status = { ...status, state: 'RUNNING_SAMPLE', can_run_sample: false, latest_sample: {
          sample_id: status.sample_id!, status: 'PREPARING', request_id: null, started_at: '', finished_at: null,
          exit_code: null, error: null, artifacts: [],
        } };
      }
      if (action === 'stop') status = { ...status, state: 'STOPPED', can_start: true, can_stop: false, can_run_sample: false, simulator_pid: null };
    }
    return route.fulfill({ json: action === 'logs' ? { entries: [{ id: 1, at: '', source: 'bridge', text: 'Existing sample only' }] } : status });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: /Simulator/ }).click();
  const start = page.getByRole('button', { name: 'Start Simulator', exact: true });
  const run = page.getByRole('button', { name: 'Run Existing Welding Sample', exact: true });
  const stop = page.getByRole('button', { name: 'Stop Simulator', exact: true });
  await expect(start).toBeEnabled(); await expect(run).toBeDisabled(); await expect(stop).toBeDisabled();
  expect(actions).toEqual([]);
  await expect(page.getByText('현재 웹 preview trajectory와 아직 연결되지 않았습니다.', { exact: false })).toBeVisible();
  await expect(page.getByTestId('simulator-state')).toHaveClass(/tone-neutral/);
  await start.click();
  await expect(page.getByTestId('simulator-state')).toHaveText('STARTING');
  await expect(page.getByTestId('simulator-state')).toHaveClass(/tone-warning/);
  await expect(run).toBeDisabled(); await expect(start).toBeDisabled();
  status = { ...status, state: 'READY', can_run_sample: true };
  await expect(run).toBeEnabled();
  await expect(page.getByTestId('simulator-state')).toHaveClass(/tone-success/);
  await page.screenshot({ path: 'test-results/redesign-simulator-ready.png', fullPage: true, animations: 'disabled' });
  await run.click();
  await expect(page.getByTestId('simulator-state')).toHaveText('RUNNING_SAMPLE');
  await expect(page.getByTestId('simulator-state')).toHaveClass(/tone-active/);
  await expect(run).toBeDisabled(); await expect(page.getByTestId('simulator-latest')).toContainText('PREPARING');
  status = { ...status, state: 'READY', can_run_sample: true, latest_sample: { ...status.latest_sample!, status: 'SUCCEEDED' } };
  await expect(page.getByTestId('simulator-latest')).toContainText('SUCCEEDED');
  await expect(page.getByTestId('workflow-state')).toHaveText('EMPTY');
  await page.getByRole('button', { name: 'Console 열기', exact: true }).click();
  await expect(page.getByLabel('Simulator logs')).toContainText('Existing sample only');
  rejectSample = true;
  await run.click(); await expect(page.getByRole('alert')).toContainText('Simulator must be READY');
  await stop.click(); await expect(page.getByTestId('simulator-state')).toHaveText('STOPPED');
  await expect(run).toBeDisabled();
  expect(actions).toEqual(['start', 'run-sample', 'run-sample', 'stop']);
});

test('missing configuration is explained without launching a simulator', async ({ page }) => {
  await page.route('**/api/simulator/status', (route) => route.fulfill({ json: {
    state: 'STOPPED', configured: false, configuration_errors: ['Set WELD_SIM_PYTHON'],
    sample_configuration_errors: ['Set WELD_SIM_SAMPLE_ID'], can_start: false, can_stop: false, can_run_sample: false,
    sample_id: null, latest_sample: null,
  } }));
  await page.route('**/api/simulator/logs', (route) => route.fulfill({ json: { entries: [] } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('tab', { name: /Simulator/ }).click();
  await page.getByText('실행 환경 설정 필요').click();
  await expect(page.getByText('Set WELD_SIM_PYTHON', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start Simulator', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Run Existing Welding Sample', exact: true })).toBeDisabled();
  const widths = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(widths[0]).toBeLessThanOrEqual(widths[1]);
});
