import { expect, test, type Page } from '@playwright/test';

async function stroke(page: Page, from: [number, number], to: [number, number], steps = 1) {
  const surface = page.getByTestId('drawing-surface');
  await surface.scrollIntoViewIfNeeded();
  const box = await surface.boundingBox();
  if (!box) throw new Error('Missing drawing surface');
  await page.mouse.move(box.x + box.width * from[0], box.y + box.height * from[1]);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * to[0], box.y + box.height * to[1], { steps });
  await page.mouse.up();
  await page.mouse.move(1, 1);
}

async function overlayAlpha(page: Page, x = 0.4, y = 0.49, width = 0.2, height = 0.02) {
  return page.getByTestId('drawing-surface').evaluate((host, area) => {
    const mask = host.querySelectorAll('canvas')[1];
    const data = mask.getContext('2d')!.getImageData(Math.round(mask.width * area.x), Math.round(mask.height * area.y), Math.max(1, Math.round(mask.width * area.width)), Math.max(1, Math.round(mask.height * area.height))).data;
    return [...new Set(Array.from(data).filter((_, index) => index % 4 === 3))];
  }, { x, y, width, height });
}

async function sample(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: '샘플 이미지로 시작' }).click();
  await expect(page.getByTestId('drawing-surface')).toBeVisible();
  await page.getByLabel('Brush size').fill('100');
  await stroke(page, [0.2, 0.5], [0.8, 0.5]);
}

test('one fast eraser stroke removes overlay alpha completely at display opacity 45%', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await sample(page);
  await expect.poll(async () => (await overlayAlpha(page)).some((value) => value > 0)).toBeTruthy();
  await page.getByRole('button', { name: '지우개', exact: true }).click();
  await page.getByLabel('Brush size').fill('40');
  await stroke(page, [0.35, 0.5], [0.65, 0.5]);
  await expect.poll(() => overlayAlpha(page)).toEqual([0]);
  await page.screenshot({ path: 'test-results/ux-pass2-eraser.png', fullPage: true, animations: 'disabled' });
});

// Inspect the actual multipart PNG emitted by the UI, before backend normalization.
async function exportPixels(page: Page) {
  // Chrome's protocol can omit multipart file bytes from postDataBuffer().
  // Observe (without changing) the FormData Blob at the browser fetch boundary.
  await page.evaluate(() => {
    const captured = window as Window & { __testExportedMask?: Blob };
    const originalFetch = window.fetch;
    window.fetch = (input, init) => {
      if (String(input).endsWith('/api/masks/manual') && init?.body instanceof FormData) {
        const file = init.body.get('file');
        if (file instanceof Blob) captured.__testExportedMask = file;
        window.fetch = originalFetch;
      }
      return originalFetch(input, init);
    };
  });
  const received = page.waitForResponse((response) => response.url().endsWith('/api/masks/manual'));
  await page.getByTestId('confirm-mask').click();
  expect((await received).ok()).toBeTruthy();
  return page.evaluate(async () => {
    const captured = window as Window & { __testExportedMask?: Blob };
    const file = captured.__testExportedMask;
    delete captured.__testExportedMask;
    if (!file) throw new Error('No exported PNG observed at fetch');
    const png = await file.arrayBuffer();
    const image = await createImageBitmap(file);
    const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
    const ctx = canvas.getContext('2d')!; ctx.drawImage(image, 0, 0); image.close();
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    const digest = async (data: ArrayBuffer) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data))).map((n) => n.toString(16).padStart(2, '0')).join('');
    let nonBinary = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (![0, 255].includes(pixels[i]) || pixels[i + 1] !== pixels[i] || pixels[i + 2] !== pixels[i] || pixels[i + 3] !== 255) nonBinary++;
    }
    const pixel = (x: number, y: number) => pixels[(Math.round(y) * canvas.width + Math.round(x)) * 4];
    const corridor = new Set<number>();
    for (let y = canvas.height / 2 - 15; y <= canvas.height / 2 + 15; y++) {
      for (let x = canvas.width * .37; x <= canvas.width * .63; x++) corridor.add(pixel(x, y));
    }
    return {
      width: canvas.width, height: canvas.height, nonBinary, pngHash: await digest(png),
      pixelHash: await digest(pixels.buffer), corridor: [...corridor],
      center: pixel(canvas.width / 2, canvas.height / 2),
      unErased: pixel(canvas.width * .25, canvas.height / 2),
      shoulder: pixel(canvas.width / 2, canvas.height / 2 + 35),
      roundCap: pixel(canvas.width * .35 - 12, canvas.height / 2),
    };
  });
}

test('binary export: brush, single erase, opacity 20/45/80, erase undo and clear undo', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await sample(page);
  const before = await exportPixels(page);
  expect(before).toMatchObject({ width: 1280, height: 720, nonBinary: 0, center: 255, corridor: [255], unErased: 255 });
  await page.getByRole('button', { name: '지우개', exact: true }).click();
  await page.getByLabel('Brush size').fill('40');
  await stroke(page, [.35, .5], [.65, .5]); // one mousemove between the two endpoints
  await expect(page.getByTestId('mask-status')).toHaveText('변경됨');
  await expect(page.getByText('마스크가 변경되었습니다', { exact: true })).toBeVisible();
  await expect(page.getByTestId('confirm-mask')).toHaveText('다시 확정');
  await expect.poll(() => overlayAlpha(page)).toEqual([0]);
  const erased = await exportPixels(page);
  expect(erased).toMatchObject({ nonBinary: 0, center: 0, corridor: [0], roundCap: 0, unErased: 255, shoulder: 255 });
  for (const opacity of ['0.2', '0.45', '0.8']) {
    await page.getByLabel('Mask opacity').fill(opacity);
    await expect(page.getByTestId('drawing-surface').locator('canvas').nth(1)).toHaveCSS('opacity', opacity);
    await expect(page.getByTestId('mask-status')).toHaveText('확정됨'); // display edits are not mask edits
    // Clear + Undo restores identical strokes and enables re-confirmation through the real UI.
    await page.getByRole('button', { name: '전체 지우기', exact: true }).click();
    await expect(page.getByTestId('confirm-mask')).toBeDisabled();
    await page.getByRole('button', { name: '실행 취소', exact: true }).click();
    const again = await exportPixels(page);
    expect(again.pngHash).toBe(erased.pngHash);
    expect(again.pixelHash).toBe(erased.pixelHash);
    expect(again.nonBinary).toBe(0);
    await expect.poll(() => overlayAlpha(page)).toEqual([0]);
  }
  await page.getByRole('button', { name: '실행 취소', exact: true }).click(); // undo the single eraser stroke
  const restored = await exportPixels(page);
  expect(restored.pngHash).toBe(before.pngHash);
  expect(restored.pixelHash).toBe(before.pixelHash);
  expect(restored.center).toBe(255);
  await expect.poll(() => overlayAlpha(page)).toEqual([255]);
});

test('display opacity does not change brush or eraser compositing, including single clicks', async ({ page }) => {
  await sample(page);
  for (const opacity of ['0.2', '0.45', '0.8']) {
    await page.getByLabel('Mask opacity').fill(opacity);
    await expect(page.getByTestId('drawing-surface').locator('canvas').nth(1)).toHaveCSS('opacity', opacity);
    await expect.poll(() => overlayAlpha(page)).toEqual([255]);
    await page.getByRole('button', { name: '지우개', exact: true }).click();
    await page.getByLabel('Brush size').fill('40');
    const box = (await page.getByTestId('drawing-surface').boundingBox())!;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.move(1, 1);
    await expect.poll(() => overlayAlpha(page, .497, .495, .006, .01)).toEqual([0]);
    await page.getByRole('button', { name: '실행 취소', exact: true }).click();
    await expect.poll(() => overlayAlpha(page)).toEqual([255]);
  }
});

test('upscaled viewport keeps source pixel coordinates and exports source resolution', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto('/');
  const png = await page.evaluate(async () => {
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 180;
    const ctx = canvas.getContext('2d')!; ctx.fillStyle = '#789'; ctx.fillRect(0, 0, 320, 180);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await page.getByLabel('RGB 이미지 업로드').setInputFiles({ name: 'small-scene.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64') });
  await expect(page.getByTestId('drawing-surface')).toBeVisible();
  const box = (await page.getByTestId('drawing-surface').boundingBox())!;
  const viewport = (await page.locator('.image-workspace').boundingBox())!;
  expect(box.width).toBeGreaterThan(320);
  expect(box.height / viewport.height).toBeGreaterThan(.8);
  expect(box.height / viewport.height).toBeLessThan(.93);
  expect(box.width / box.height).toBeCloseTo(320 / 180, 2);
  await page.getByLabel('Brush size').fill('28');
  await stroke(page, [.2, .5], [.8, .5]);
  const before = await exportPixels(page);
  expect(before).toMatchObject({ width: 320, height: 180, center: 255, unErased: 255, nonBinary: 0 });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '전체 지우기', exact: true }).click();
  await page.getByRole('button', { name: '실행 취소', exact: true }).click();
  const resized = await exportPixels(page);
  expect(resized.pngHash).toBe(before.pngHash);
  expect(resized.pixelHash).toBe(before.pixelHash);
});
