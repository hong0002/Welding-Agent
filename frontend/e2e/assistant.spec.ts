import { expect, test, type Page } from '@playwright/test';
import type { Job } from '../src/types';

async function scene(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('tab', { name: 'Assistant', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('agent-state')).toHaveText('READY');
  const response = page.waitForResponse((r) => r.url().endsWith('/api/scenes/upload'));
  await page.getByRole('button', { name: '샘플 이미지로 시작' }).click();
  const job: Job = await (await response).json();
  await expect(page.getByTestId('drawing-surface')).toBeVisible();
  return job.id;
}

async function draw(page: Page, from: number, to: number, y: number) {
  const surface = page.getByTestId('drawing-surface');
  await surface.scrollIntoViewIfNeeded();
  const box = (await surface.boundingBox())!;
  await page.mouse.move(box.x + box.width * from, box.y + box.height * y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * to, box.y + box.height * y, { steps: 16 });
  await page.mouse.up();
  await page.mouse.move(1, 1);
}

async function send(page: Page, message: string) {
  const replies = page.locator('.agent-message.assistant');
  const before = await replies.count();
  const stream = page.waitForResponse((r) => r.url().endsWith('/api/agent/chat/stream'));
  await page.getByLabel('Assistant 메시지', { exact: true }).fill(message);
  await page.getByLabel('Assistant 메시지', { exact: true }).press('Enter');
  const response = await stream;
  expect(response.ok()).toBeTruthy();
  // Chromium may retain the SSE network entry after fetch consumed it; assert visible completion.
  await expect(replies).toHaveCount(before + 1);
  await expect(page.getByLabel('Assistant 메시지', { exact: true })).toBeEnabled();
}

async function alpha(page: Page, job: Job, point: { x: number; y: number }) {
  return page.getByTestId('drawing-surface').evaluate((host, input) => {
    const canvas = Array.from(host.querySelectorAll('canvas')).at(-1)!;
    const x = Math.round(input.point.x / input.width * canvas.width);
    const y = Math.round(input.point.y / input.height * canvas.height);
    return Array.from(canvas.getContext('2d')!.getImageData(x - 2, y - 2, 5, 5).data).filter((_, i) => i % 4 === 3);
  }, { point, width: job.scene.width, height: job.scene.height });
}

test('AI mask appears, eraser edits stay binary, manual intent never resegments, and redraw intent waits', async ({ page, request }) => {
  const id = await scene(page);
  await send(page, '용접할 부분 자동으로 찾아서 왼쪽에서 오른쪽으로 용접해');
  await expect(page.getByTestId('mask-source')).toHaveText('AI · VLM Segment');
  await expect(page.getByLabel('Agent 작업 진행')).toContainText('2 regions');
  const ai: Job = await (await request.get(`/api/weld/${id}`)).json();
  expect(ai.mask?.mask_source).toBe('vlm_segment');
  expect(ai.mask?.regions).toHaveLength(2);
  // Mask alpha is separate from the image/path layers, and background remains transparent.
  await expect.poll(() => page.getByTestId('drawing-surface').evaluate((host) => {
    const canvas = host.querySelectorAll('canvas')[1];
    return canvas.getContext('2d')!.getImageData(Math.round(canvas.width * .25), Math.round(canvas.height * .3), 1, 1).data[3];
  })).toBe(255);
  await page.getByRole('button', { name: '지우개', exact: true }).click();
  const surface = page.getByTestId('drawing-surface');
  const box = (await surface.boundingBox())!;
  await page.mouse.move(box.x + box.width * .30, box.y + box.height * .26);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * .30, box.y + box.height * .34, { steps: 12 });
  await page.mouse.up(); await page.mouse.move(1, 1);
  await expect(page.getByTestId('mask-source')).toHaveText('Manual edited');
  await send(page, '내가 표시한 영역을 왼쪽에서 오른쪽으로 용접해');
  const edited: Job = await (await request.get(`/api/weld/${id}`)).json();
  expect(edited.mask?.mask_source).toBe('manual_edited');
  expect(edited.mask?.edited_from_mask_id).toBe(ai.mask?.id);
  expect(edited.mask?.regions).toHaveLength(3);
  expect(edited.final_trajectory?.segments).toHaveLength(3);
  expect(edited.final_trajectory?.generator).toContain('dummy');
  const pixels = await page.evaluate(async (url) => {
    const bitmap = await createImageBitmap(await (await fetch(url)).blob());
    const canvas = document.createElement('canvas'); canvas.width = bitmap.width; canvas.height = bitmap.height;
    const ctx = canvas.getContext('2d')!; ctx.drawImage(bitmap, 0, 0); bitmap.close();
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    const at = (x: number, y: number) => data[4 * (Math.round(canvas.height * y) * canvas.width + Math.round(canvas.width * x))];
    return { values: [...new Set(Array.from(data).filter((_, i) => i % 4 === 0))].sort(),
      erased: at(.30, .30), retained: at(.25, .30), other: at(.70, .70), background: at(.50, .50) };
  }, edited.mask!.image_url);
  expect(pixels).toEqual({ values: [0, 255], erased: 0, retained: 255, other: 255, background: 0 });
  await send(page, '두 번째 영역은 제외해줘');
  const skipped: Job = await (await request.get(`/api/weld/${id}`)).json();
  expect(skipped.final_trajectory?.segments.map((s) => s.region_id)).toEqual([0, 2]);
  expect(skipped.mask?.id).toBe(edited.mask?.id);
  await send(page, '자동으로 찾은 게 이상해. 내가 다시 표시할게');
  const waiting: Job = await (await request.get(`/api/weld/${id}`)).json();
  expect(waiting.history).toEqual(skipped.history);
  expect(waiting.mask?.id).toBe(edited.mask?.id);
  await page.screenshot({ path: 'test-results/ai-mask-edited.png', fullPage: true });
});

test('A + B: Enter auto-syncs mask, tools update canvas, same-session follow-up excludes region 1', async ({ page, request }) => {
  const errors: string[] = [], mutations: string[] = [], sessions: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (r) => {
    if (r.method() === 'POST') mutations.push(new URL(r.url()).pathname);
    if (r.url().endsWith('/api/agent/chat/stream')) sessions.push(r.postDataJSON().session_id);
  });
  const id = await scene(page);
  await draw(page, .16, .42, .3); await draw(page, .62, .84, .7);
  const composer = page.getByLabel('Assistant 메시지', { exact: true });
  await composer.fill('표시한 부분을'); await composer.press('Shift+Enter');
  await expect(composer).toHaveValue('표시한 부분을\n');
  expect(sessions).toHaveLength(0);
  await send(page, '표시한 부분을 왼쪽에서 오른쪽으로 용접해');
  await expect(page.getByTestId('workflow-state')).toHaveText('VALIDATED');
  await expect(page.getByRole('tab', { name: 'Assistant', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('log', { name: 'Assistant 대화' })).toContainText('용접 경로를 생성했습니다.');
  await expect(page.getByLabel('Agent 작업 진행')).toContainText('Preview validation 통과');
  await expect(page.getByTestId('confirm-mask')).toBeDisabled();
  const first: Job = await (await request.get(`/api/weld/${id}`)).json();
  expect(first.instruction?.parser).toBe('GPT-Agent');
  expect(first.final_trajectory?.segments).toHaveLength(2);
  const firstEnd = first.final_trajectory!.segments[0].points.at(-1)!;
  const secondPoint = first.final_trajectory!.segments[1].points[20];
  await expect.poll(async () => (await alpha(page, first, firstEnd)).some((a) => a > 0)).toBeTruthy();
  expect((await alpha(page, first, { x: 640, y: 360 })).every((a) => a === 0)).toBeTruthy();
  expect(mutations.indexOf('/api/masks/manual')).toBeLessThan(mutations.indexOf('/api/agent/chat/stream'));
  expect(mutations).not.toContain('/api/instructions/parse');
  expect(mutations).not.toContain('/api/weld/plan');
  expect(mutations.filter((path) => path.includes('/api/simulator/'))).toEqual([]);
  await send(page, '두 번째 영역은 제외해줘');
  const second: Job = await (await request.get(`/api/weld/${id}`)).json();
  expect(second.instruction?.structured.skip_regions).toEqual([1]);
  expect(second.final_trajectory?.segments.map((s) => s.region_id)).toEqual([0]);
  expect(sessions).toHaveLength(2); expect(sessions[0]).toBe(sessions[1]);
  expect(mutations.filter((p) => p === '/api/masks/manual')).toHaveLength(1);
  await expect.poll(async () => (await alpha(page, second, secondPoint)).every((a) => a === 0)).toBeTruthy();
  await page.screenshot({ path: 'test-results/assistant-desktop.png', fullPage: true });
  await page.reload();
  await expect(page.getByRole('log', { name: 'Assistant 대화' })).toContainText('두 번째 영역은 제외해줘');
  expect(errors).toEqual([]);
});

test('C + D: current preview is blocked; explicit existing VLA sample starts and waits for READY', async ({ page, request }) => {
  await request.post('/api/simulator/stop', { data: {} }); // test-only simulator fixture
  await page.goto('/');
  await expect(page.getByTestId('agent-state')).toHaveText('READY');
  await send(page, '지금 만든 경로 시뮬레이션해');
  await expect(page.getByRole('log', { name: 'Assistant 대화' })).toContainText('아직 연결되지 않았습니다');
  expect((await (await request.get('/api/simulator/status')).json()).state).toBe('STOPPED');
  await send(page, '시뮬레이터 시작하고 기존 VLA 샘플 실행해');
  await expect(page.getByLabel('Agent 작업 진행')).toContainText('Simulator 준비');
  await expect(page.getByLabel('Agent 작업 진행')).toContainText('기존 VLA 샘플 재생');
  expect((await (await request.get('/api/simulator/status')).json()).state).toBe('RUNNING_SAMPLE');
  await expect(page.getByRole('log', { name: 'Assistant 대화' })).toContainText('재생을 요청했습니다');
  await page.getByRole('tab', { name: '시뮬레이션', exact: true }).click();
  await expect(page.getByRole('button', { name: '시뮬레이터 중지', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '시뮬레이터 중지', exact: true }).click();
  await expect(page.getByTestId('simulator-state')).toHaveText('STOPPED');
});

test('agent failure is visible and missing configuration preserves manual Path workflow', async ({ page }) => {
  await page.route('**/api/agent/chat/stream', (route) => route.fulfill({ status: 503, json: { code:'model_unavailable',detail: '테스트: 모델을 사용할 수 없습니다.' } }));
  await page.goto('/');
  await expect(page.getByTestId('agent-state')).toHaveText('READY');
  await page.getByLabel('Assistant 메시지', { exact: true }).fill('경로 만들어줘');
  await page.getByLabel('Assistant 메시지', { exact: true }).press('Enter');
  await expect(page.getByRole('alert')).toContainText('모델을 사용할 수 없습니다.');
  await expect(page.getByTestId('agent-state')).toHaveText('ERROR');
  await page.route('**/api/agent/status', (route) => route.fulfill({ json: {
    enabled: true, api_key_configured: false, sdk_available: true, model: 'gpt-5.6', state: 'NOT CONFIGURED',
  } }));
  await page.reload();
  await expect(page.getByTestId('agent-state')).toHaveText('NOT CONFIGURED');
  await expect(page.getByLabel('Assistant 메시지', { exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '샘플 이미지로 시작' }).click();
  await expect(page.getByTestId('drawing-surface')).toBeVisible();
  await draw(page, .2, .8, .5);
  await page.getByTestId('confirm-mask').click();
  await page.getByText('수동 지시 / 디버그', { exact: true }).click();
  await page.getByRole('button', { name: '지시 분석', exact: true }).click();
  await page.getByRole('tab', { name: '경로 계획', exact: true }).click();
  await page.getByRole('button', { name: '용접 경로 생성', exact: true }).click();
  await expect(page.getByTestId('validation-result')).toContainText('통과');
});

test('390px Assistant layout, empty mask guidance, repeated Enter and erased mask protection', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const mutations: string[] = [];
  page.on('request', (r) => { if (r.method() === 'POST') mutations.push(new URL(r.url()).pathname); });
  await scene(page);
  await send(page, '경로 만들어줘');
  await expect(page.getByRole('log', { name: 'Assistant 대화' })).toContainText('마스크를 먼저 준비해주세요');
  expect(mutations).not.toContain('/api/masks/manual');
  await draw(page, .2, .8, .5);
  const composer = page.getByLabel('Assistant 메시지', { exact: true });
  await composer.fill('왼쪽에서 오른쪽으로 만들어줘');
  await composer.press('Enter'); await page.keyboard.press('Enter');
  await expect(page.getByTestId('workflow-state')).toHaveText('VALIDATED');
  await expect(composer).toBeEnabled();
  expect(mutations.filter((p) => p === '/api/agent/chat/stream')).toHaveLength(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: 'test-results/assistant-mobile.png', fullPage: true });
  await page.getByRole('button', { name: '전체 지우기', exact: true }).click();
  await composer.fill('다시 해줘'); await composer.press('Enter');
  await expect(page.getByRole('alert')).toContainText('마스크가 비어 있습니다');
  expect(mutations.filter((p) => p === '/api/agent/chat/stream')).toHaveLength(2);
});
