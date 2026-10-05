import { expect, test } from '@playwright/test';

test('next actions and stepper navigate without planning or starting simulation automatically', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const mutations: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && !request.url().includes('/api/agent/')) mutations.push(new URL(request.url()).pathname);
  });
  await page.route('**/api/simulator/**', (route) => route.fulfill({ json: route.request().url().endsWith('/logs') ? { entries: [] } : {
    state: 'READY', configured: true, configuration_errors: [], sample_configuration_errors: [], error: null,
    can_start: false, can_stop: true, can_run_sample: true, sample_id: 'L_PR_03_0001', latest_sample: null,
    configuration_diagnostics: { isaac_launcher: 'D:/isaacsim/python.bat', prediction_format: 'legacy_npz', isaac_import_check: { status: 'passed', message: 'Fixture import result' } },
  } }));
  await page.goto('/');
  const stepper = page.getByRole('navigation', { name: 'Workflow progress' });
  // Pending step navigation is allowed, and keeps workflow EMPTY.
  await expect(stepper.getByRole('button', { name: 'Validate', exact: true })).toHaveCount(0);
  await stepper.getByRole('button', { name: '3D ready', exact: true }).click();
  await expect(page.getByRole('tab', { name: '경로 계획', exact: true })).toBeFocused();
  await expect(page.getByTestId('workflow-state')).toHaveText('EMPTY');
  await expect(page.getByRole('button', { name: '용접 경로 생성', exact: true })).toBeDisabled();
  expect(mutations).toEqual([]);
  await stepper.getByRole('button', { name: 'Scene', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Scene and mask workspace' })).toBeFocused();
  await page.getByRole('button', { name: '샘플 이미지로 시작' }).click();
  const surface = page.getByTestId('drawing-surface');
  await expect(surface).toBeVisible();
  const box = (await surface.boundingBox())!;
  await page.mouse.move(box.x + box.width * .18, box.y + box.height * .49);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * .82, box.y + box.height * .49, { steps: 20 });
  await page.mouse.up();
  await page.getByTestId('confirm-mask').click();
  await stepper.getByRole('button', { name: 'Instruction', exact: true }).click();
  await page.getByText('수동 지시 / 디버그', { exact: true }).click();
  await page.getByRole('button', { name: '지시 분석', exact: true }).click();
  const nextPath = page.getByRole('button', { name: '경로 계획으로 계속', exact: true });
  await expect(nextPath).toBeVisible();
  await page.mouse.move(1, 1);
  await page.screenshot({ path: 'test-results/ux-pass2-command.png', fullPage: true, animations: 'disabled' });
  const parsedMutations = [...mutations];
  await nextPath.click();
  await expect(page.getByRole('tab', { name: '경로 계획', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('workflow-state')).toHaveText('INSTRUCTION_READY');
  expect(mutations).toEqual(parsedMutations);
  await page.getByRole('button', { name: '용접 경로 생성', exact: true }).click();
  await expect(page.getByTestId('validation-result')).toContainText('통과');
  const nextSimulator = page.getByRole('button', { name: 'Simulator로 이동', exact: true });
  await expect(nextSimulator).toBeVisible();
  await page.screenshot({ path: 'test-results/ux-pass2-path.png', fullPage: true, animations: 'disabled' });
  const plannedMutations = [...mutations];
  await nextSimulator.click();
  await expect(page.getByRole('tab', { name: '시뮬레이션', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('simulator-state')).toHaveText('READY');
  await expect(page.getByRole('button', { name: '기존 용접 샘플 실행', exact: true })).toBeHidden();
  await expect(page.getByText('Fixture import result', { exact: true })).toBeHidden();
  await page.screenshot({ path: 'test-results/ux-pass2-simulator.png', fullPage: true, animations: 'disabled' });
  expect(mutations).toEqual(plannedMutations);
  for (const [step, tab] of [['Instruction', 'Assistant'], ['Rough', '경로 계획'], ['3D ready', '경로 계획'], ['Simulator', '시뮬레이션']]) {
    await stepper.getByRole('button', { name: step, exact: true }).click();
    await expect(page.getByRole('tab', { name: tab, exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(stepper.getByRole('button', { name: step, exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('workflow-state')).toHaveText('VALIDATED');
  }
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await expect(stepper.getByRole('button', { name: 'Instruction', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: '오른쪽 → 왼쪽', exact: true }).click();
  await expect(nextPath).toHaveCount(0);
  await stepper.getByRole('button', { name: 'Mask', exact: true }).click();
  await page.getByRole('button', { name: '지우개', exact: true }).click();
  await surface.click({ position: { x: box.width * .5, y: box.height * .49 } });
  await expect(page.getByTestId('mask-status')).toHaveText('변경됨');
  await expect(page.getByTestId('confirm-mask')).toHaveText('다시 확정');
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await expect(nextSimulator).toHaveCount(0);
  await expect(page.getByTestId('validation-result')).toContainText('대기');
  expect(mutations).toEqual(plannedMutations);
});
