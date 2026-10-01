import { expect, test } from '@playwright/test';

test('native AI mask is visible but requires human approval; eraser submits manual_edited', async ({ page, request }) => {
  // Fixed offline status avoids a polling route.fetch response racing page teardown.
  const body = await (await request.get('/api/models/status')).json();
  body.segment.backend = body.rough.backend = 'native';
  await page.route('**/api/models/status', async (route) => {
    await route.fulfill({ json: body });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '샘플 이미지로 시작' }).click();
  await page.getByText('수동 지시 / 디버그', { exact: false }).click();
  await page.locator('#instruction').fill('native-fixture 왼쪽에서 오른쪽으로 용접해');
  const segmented = page.waitForResponse('**/api/masks/automatic');
  await page.getByTestId('native-segment').click();
  const job = await (await segmented).json();
  expect(job.mask.approved).toBe(false);
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  await expect(page.getByRole('button', { name: '지시 분석', exact: true })).toBeDisabled();
  await expect.poll(() => page.getByTestId('drawing-surface').evaluate((el) => {
    const canvas = el.querySelectorAll('canvas')[1];
    return Array.from(canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data)
      .some((value, index) => index % 4 === 3 && value > 0);
  })).toBeTruthy();
  const approved = page.waitForResponse('**/api/masks/approve');
  await page.getByTestId('confirm-mask').click();
  const confirmed = await (await approved).json();
  expect(confirmed.mask.id).toBe(job.mask.id);
  expect(confirmed.mask.approved).toBe(true);
  expect(confirmed.mask.mask_source).toBe('vlm_segment');
  await page.getByRole('button', { name: '지우개', exact: true }).click();
  await page.getByLabel('Brush size').fill('40');
  const surface = page.getByTestId('drawing-surface');
  const box = (await surface.boundingBox())!;
  await page.mouse.move(box.x + box.width * .2, box.y + box.height * .3);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * .22, box.y + box.height * .3, { steps: 3 });
  await page.mouse.up();
  const edited = page.waitForResponse('**/api/masks/manual');
  await page.getByTestId('confirm-mask').click();
  const current = await (await edited).json();
  expect(current.mask.mask_source).toBe('manual_edited');
  expect(current.mask.edited_from_mask_id).toBe(job.mask.id);
  expect(current.mask.selected_pixels).toBeLessThan(job.mask.selected_pixels);
  expect(current.rough_trajectory).toBeNull();
});
