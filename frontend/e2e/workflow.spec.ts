import { expect, test, type Page } from '@playwright/test';
import type { Job } from '../src/types';

async function sample(page: Page) {
  await page.goto('/');
  await page.getByText('수동 지시 / 디버그', { exact: true }).click();
  await expect(page.getByText('Backend connected', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '샘플 이미지로 시작' }).click();
  await expect(page.getByTestId('drawing-surface')).toBeVisible();
}

async function stroke(page: Page, from = 0.15, to = 0.85, y = 0.49) {
  const box = await page.getByTestId('drawing-surface').boundingBox();
  if (!box) throw new Error('Drawing surface is missing');
  await page.mouse.move(box.x + box.width * from, box.y + box.height * y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * to, box.y + box.height * y, { steps: 25 });
  await page.mouse.up();
}

test('browser upload → full-resolution mask → parse → validated preview', async ({ page, request }) => {
  const pageErrors: string[] = [];
  const simulatorActions: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/api/simulator/')) simulatorActions.push(request.url());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await sample(page);
  // Use the browser's generated image as a file input upload as well.
  const png = await page.getByTestId('drawing-surface').screenshot();
  await page.getByLabel('RGB 이미지 업로드').setInputFiles({ name: 'uploaded-scene.png', mimeType: 'image/png', buffer: png });
  await expect(page.getByText('uploaded-scene.png', { exact: true })).toBeVisible();
  await expect(page.getByTestId('drawing-surface')).toBeVisible();
  await stroke(page);
  const maskResponse = page.waitForResponse((response) => response.url().endsWith('/api/masks/manual'));
  await page.getByTestId('confirm-mask').click();
  const masked = await (await maskResponse).json();
  expect(masked.mask.width).toBe(masked.scene.width);
  expect(masked.mask.height).toBe(masked.scene.height);
  expect(masked.mask.selected_pixels).toBeGreaterThan(0);
  expect(masked.mask.mask_source).toBe('manual');
  expect((await request.get(masked.mask.image_url)).ok()).toBeTruthy();
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('button', { name: '지시 분석' }).click();
  await expect(page.getByTestId('parsed-instruction')).toContainText('left_to_right');
  const planResponse = page.waitForResponse((response) => response.url().endsWith('/api/weld/plan'));
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await page.getByRole('button', { name: '용접 경로 생성' }).click();
  const plan = await (await planResponse).json();
  expect(plan.state).toBe('VALIDATED');
  expect(plan.final_trajectory.coordinate_space).toBe('image_pixel');
  expect(plan.final_trajectory.is_robot_executable).toBe(false);
  expect(plan.final_trajectory.segments[0].points.at(-1).x).toBeGreaterThan(plan.final_trajectory.segments[0].points[0].x);
  await expect(page.getByTestId('validation-result')).toContainText('통과');
  await expect(page.getByTestId('workflow-state')).toHaveText('VALIDATED');
  expect(simulatorActions).toEqual([]);
  await page.screenshot({ path: 'test-results/workflow-desktop.png', fullPage: true, animations: 'disabled' });
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Preview JSON 저장' }).click();
  expect((await download).suggestedFilename()).toContain('preview-');
  // Editing language hides a previously successful validation until reparsed.
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('button', { name: '오른쪽 → 왼쪽' }).click();
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await expect(page.getByRole('button', { name: '용접 경로 생성' })).toBeDisabled();
  await expect(page.getByTestId('validation-result')).toContainText('대기');
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('button', { name: '지시 분석' }).click();
  await expect(page.getByTestId('parsed-instruction')).toContainText('right_to_left');
  const reverseResponse = page.waitForResponse((response) => response.url().endsWith('/api/weld/plan'));
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await page.getByRole('button', { name: '용접 경로 생성' }).click();
  const reversed = await (await reverseResponse).json();
  expect(reversed.final_trajectory.segments[0].points[0].x).toBeGreaterThan(reversed.final_trajectory.segments[0].points.at(-1).x);
  expect(pageErrors).toEqual([]);
});

test('eraser, undo, clear, opacity, and mask edits remain consistent', async ({ page }) => {
  await sample(page);
  await stroke(page);
  const confirm = async () => {
    const response = page.waitForResponse((r) => r.url().endsWith('/api/masks/manual'));
    await page.getByTestId('confirm-mask').click();
    return (await response).json();
  };
  const original = await confirm();
  expect(original.scene.width).toBe(1280);
  expect(original.mask.width).toBe(1280);
  expect(original.mask.height).toBe(720);
  await page.getByRole('button', { name: '지우개', exact: true }).click();
  await stroke(page, 0.4, 0.6);
  const erased = await confirm();
  expect(erased.mask.selected_pixels).toBeLessThan(original.mask.selected_pixels);
  await page.getByRole('button', { name: '실행 취소', exact: true }).click();
  await page.getByLabel('Mask opacity').fill('0.1');
  const undone = await confirm();
  expect(undone.mask.selected_pixels).toBe(original.mask.selected_pixels);
  await page.getByRole('button', { name: '전체 지우기', exact: true }).click();
  await expect(page.getByTestId('confirm-mask')).toBeDisabled();
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await expect(page.getByRole('button', { name: '지시 분석' })).toBeDisabled();
  await page.getByRole('button', { name: '실행 취소', exact: true }).click();
  const restored = await confirm();
  expect(restored.mask.selected_pixels).toBe(original.mask.selected_pixels);
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('button', { name: '지시 분석' }).click();
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await expect(page.getByRole('button', { name: '용접 경로 생성' })).toBeEnabled();
  await page.getByRole('button', { name: '브러시', exact: true }).click();
  await stroke(page, 0.2, 0.3, 0.3);
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await expect(page.getByRole('button', { name: '용접 경로 생성' })).toBeDisabled();
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await expect(page.getByRole('button', { name: '지시 분석' })).toBeDisabled();
});

test('small screen supports drawing and validation without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await sample(page);
  await stroke(page);
  await page.getByTestId('confirm-mask').click();
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await expect(page.getByRole('button', { name: '지시 분석' })).toBeEnabled();
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('button', { name: '지시 분석' }).click();
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await expect(page.getByRole('button', { name: '용접 경로 생성' })).toBeEnabled();
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await page.getByRole('button', { name: '용접 경로 생성' }).click();
  await expect(page.getByTestId('workflow-state')).toHaveText('VALIDATED');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/workflow-mobile.png', fullPage: true, animations: 'disabled' });
});

test('disconnected regions render independent paths with no pixels across the gap', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await sample(page);
  await stroke(page, 0.18, 0.42, 0.30);
  await stroke(page, 0.62, 0.84, 0.72);
  await page.getByTestId('confirm-mask').click();
  await expect(page.getByTestId('region-count')).toHaveText('Regions: 2');
  await expect(page.getByRole('checkbox', { name: 'Region 0 포함' })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Region 1 포함' })).toBeChecked();
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('button', { name: '지시 분석' }).click();
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await expect(page.getByRole('button', { name: '용접 경로 생성' })).toBeEnabled();
  const response = page.waitForResponse((r) => r.url().endsWith('/api/weld/plan'));
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await page.getByRole('button', { name: '용접 경로 생성' }).click();
  const job: Job = await (await response).json();
  expect(job.final_trajectory?.segments).toHaveLength(2);
  expect(job.rough_trajectory?.segments).toHaveLength(2);
  await expect(page.getByTestId('workflow-state')).toHaveText('VALIDATED');
  await expect(page.getByText('ROUGH POINTS', { exact: true }).locator('..')).toContainText('64');
  await expect(page.getByText('FINAL POINTS', { exact: true }).locator('..')).toContainText('96');
  await page.mouse.move(1, 1); // Hide the brush cursor before reading visible path pixels.
  const firstEnd = job.final_trajectory!.segments[0].points.at(-1)!;
  const secondStart = job.final_trajectory!.segments[1].points[0];
  const gap = { x: (firstEnd.x + secondStart.x) / 2, y: (firstEnd.y + secondStart.y) / 2 };
  const pathAlpha = (point: { x: number; y: number }) => page.getByTestId('drawing-surface').evaluate((host, input) => {
    const canvas = Array.from(host.querySelectorAll('canvas')).at(-1)!;
    const x = Math.round(input.point.x / input.width * canvas.width);
    const y = Math.round(input.point.y / input.height * canvas.height);
    const data = canvas.getContext('2d')!.getImageData(x - 2, y - 2, 5, 5).data;
    return Array.from(data).filter((_, index) => index % 4 === 3);
  }, { point, width: job.scene.width, height: job.scene.height });
  expect((await pathAlpha(gap)).every((alpha) => alpha === 0)).toBeTruthy();
  expect((await pathAlpha(firstEnd)).some((alpha) => alpha > 0)).toBeTruthy();
  await page.screenshot({ path: 'test-results/multi-region-desktop.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('checkbox', { name: 'Rough path', exact: true }).uncheck();
  await page.getByRole('checkbox', { name: 'Final VLA preview', exact: true }).uncheck();
  await expect.poll(async () => (await pathAlpha(firstEnd)).every((alpha) => alpha === 0)).toBeTruthy();
  expect(errors).toEqual([]);
});

test('region checkboxes exclude one of three regions and invalidate stale previews', async ({ page }) => {
  await sample(page);
  await stroke(page, 0.15, 0.35, 0.30);
  await stroke(page, 0.45, 0.60, 0.49);
  await stroke(page, 0.70, 0.85, 0.72);
  await page.getByTestId('confirm-mask').click();
  await expect(page.getByTestId('region-count')).toHaveText('Regions: 3');
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Region 1 포함' }).uncheck();
  const parsedResponse = page.waitForResponse((r) => r.url().endsWith('/api/instructions/parse'));
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('button', { name: '지시 분석' }).click();
  const parsed: Job = await (await parsedResponse).json();
  expect(parsed.instruction?.structured.skip_regions).toEqual([1]);
  expect(parsed.instruction?.structured.region_order).toEqual([0, 2]);
  const response = page.waitForResponse((r) => r.url().endsWith('/api/weld/plan'));
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await page.getByRole('button', { name: '용접 경로 생성' }).click();
  const job: Job = await (await response).json();
  expect(job.final_trajectory?.segments.map((segment) => segment.region_id)).toEqual([0, 2]);
  await expect(page.getByTestId('workflow-state')).toHaveText('VALIDATED');
  await page.screenshot({ path: 'test-results/multi-region-skip.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Region 0 포함' }).uncheck();
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await expect(page.getByRole('button', { name: '용접 경로 생성' })).toBeDisabled();
  await expect(page.getByTestId('validation-result')).toContainText('대기');
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Region 2 포함' }).uncheck();
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await expect(page.getByRole('button', { name: '지시 분석' })).toBeDisabled();
  await expect(page.getByText('최소 한 영역을 선택하세요.')).toBeVisible();
});
