import { expect, test, type Page } from '@playwright/test';

async function drawRegion(page: Page, from: number, to: number, y: number) {
  const surface = page.getByTestId('drawing-surface');
  await surface.scrollIntoViewIfNeeded();
  const box = await surface.boundingBox();
  if (!box) throw new Error('Missing canvas');
  await page.mouse.move(box.x + box.width * from, box.y + box.height * y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * to, box.y + box.height * y, { steps: 20 });
  await page.mouse.up();
}

for (const size of [
  { width: 1920, height: 1080 }, { width: 1440, height: 900 },
  { width: 1366, height: 768 }, { width: 390, height: 844 },
]) {
  test(`operator workspace ${size.width}x${size.height}: regions, plan and responsive layout`, async ({ page }) => {
    await page.setViewportSize(size);
    const errors: string[] = [];
    const simulatorActions: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (request.method() === 'POST' && request.url().includes('/api/simulator/')) simulatorActions.push(request.url());
    });
    await page.goto('/');
    await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Console 열기', exact: true })).toHaveAttribute('aria-expanded', 'false');
    await page.getByRole('button', { name: '샘플 이미지로 시작' }).click();
    await expect(page.getByTestId('drawing-surface')).toBeVisible();
    await drawRegion(page, 0.16, 0.43, 0.40);
    await drawRegion(page, 0.60, 0.83, 0.62);
    await page.getByTestId('confirm-mask').click();
    await expect(page.getByTestId('region-count')).toHaveText('Regions: 2');
    await page.getByRole('checkbox', { name: 'Region 1 포함' }).uncheck();
    await page.getByRole('checkbox', { name: 'Region 1 포함' }).check();
    await page.getByRole('button', { name: '지시 분석', exact: true }).click();
    await page.getByText('Structured output', { exact: true }).click();
    await expect(page.getByTestId('parsed-instruction')).toBeVisible();
    if (size.width === 1920) await page.screenshot({ path: 'test-results/redesign-command.png', fullPage: true, animations: 'disabled' });
    await page.getByRole('button', { name: '경로 계획으로 계속' }).click();
    await expect(page.getByRole('tab', { name: '경로 계획', exact: true })).toHaveAttribute('aria-selected', 'true');
    await page.getByRole('button', { name: '용접 경로 생성', exact: true }).click();
    await expect(page.getByTestId('validation-result')).toContainText('통과');
    await expect(page.getByTestId('workflow-state')).toHaveText('VALIDATED');
    await page.mouse.move(1, 1);
    const dimensions = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }));
    expect(dimensions.width).toBeLessThanOrEqual(size.width);
    if (size.width > 1000) {
      expect(dimensions.height).toBeLessThanOrEqual(size.height);
      const canvas = await page.getByRole('region', { name: 'Scene and mask workspace' }).boundingBox();
      const inspector = await page.getByRole('complementary', { name: 'Workspace inspector' }).boundingBox();
      expect(canvas!.width / (canvas!.width + inspector!.width)).toBeGreaterThanOrEqual(0.68);
      expect(canvas!.width / (canvas!.width + inspector!.width)).toBeLessThanOrEqual(0.74);
      expect(Math.abs(canvas!.height - inspector!.height)).toBeLessThan(2);
    }
    await page.screenshot({ path: `test-results/redesign-${size.width}x${size.height}.png`, fullPage: true, animations: 'disabled' });
    if (size.width === 390) await page.screenshot({ path: 'test-results/redesign-mobile.png', fullPage: true, animations: 'disabled' });
    await page.getByRole('button', { name: 'Console 열기', exact: true }).click();
    await expect(page.getByLabel('Simulator logs')).toBeVisible();
    await page.getByRole('button', { name: 'Console 닫기', exact: true }).click();
    await expect(page.getByTestId('workflow-state')).toHaveText('VALIDATED');
    await page.getByRole('button', { name: 'Simulator로 이동', exact: true }).click();
    await expect(page.getByRole('tab', { name: '시뮬레이션', exact: true })).toBeFocused();
    await expect(page.getByTestId('simulator-state')).toBeVisible();
    await page.getByRole('tab', { name: 'Command', exact: true }).click();
    await expect(page.getByRole('checkbox', { name: 'Region 0 포함' })).toBeChecked();
    expect(simulatorActions).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('keyboard tabs and failed runtime console preserve independent preview state', async ({ page }) => {
  const actions: string[] = [];
  await page.route('**/api/simulator/**', async (route) => {
    if (route.request().method() === 'POST') actions.push(route.request().url());
    await route.fulfill({ json: route.request().url().endsWith('/logs') ? { entries: [{ id: 1, at: '', source: 'server', text: 'Fixture: queue readiness timed out' }] } : {
      state: 'FAILED', configured: true, configuration_errors: [], sample_configuration_errors: [],
      error: 'Fixture: queue readiness timed out', can_start: true, can_run_sample: false, can_stop: false,
      simulator_pid: null, sample_pid: null, sample_id: 'L_PR_03_0001', latest_sample: null,
      configuration_diagnostics: { isaac_launcher: 'D:/isaacsim/python.bat', prediction_format: 'legacy_npz', isaac_import_check: { status: 'passed', message: 'Fixture import-only result' } },
    } });
  });
  await page.goto('/');
  const command = page.getByRole('tab', { name: 'Command', exact: true });
  const path = page.getByRole('tab', { name: '경로 계획', exact: true });
  const simulator = page.getByRole('tab', { name: '시뮬레이션', exact: true });
  await command.focus();
  await page.keyboard.press('ArrowRight');
  await expect(path).toBeFocused();
  await expect(path).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('End');
  await expect(simulator).toBeFocused();
  await expect(page.getByTestId('simulator-state')).toHaveText('FAILED');
  await expect(page.getByTestId('simulator-state')).toHaveClass(/tone-danger/);
  await expect(page.getByRole('button', { name: 'Console 열기', exact: true })).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByText('실행 오류 · 로그 확인')).toBeVisible();
  await page.getByRole('button', { name: 'Console에서 로그 확인', exact: true }).click();
  await expect(page.getByLabel('Simulator logs')).toContainText('Fixture: queue readiness timed out');
  await page.screenshot({ path: 'test-results/redesign-simulator-failed.png', fullPage: true, animations: 'disabled' });
  await simulator.focus();
  await page.keyboard.press('Home');
  await expect(command).toBeFocused();
  await expect(page.getByTestId('workflow-state')).toHaveText('EMPTY');
  expect(actions).toEqual([]);
});
