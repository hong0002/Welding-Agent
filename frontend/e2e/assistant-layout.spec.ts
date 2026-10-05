import {expect,test,type Page} from '@playwright/test';

async function prepare(page:Page){
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await page.getByTestId('native-segment').click();
}

test('model details default collapsed, compact approval and YOLO summary; all controls remain accessible',async({page})=>{
  await page.setViewportSize({width:1440,height:900});await prepare(page);
  const details=page.getByTestId('model-details'),chat=page.getByRole('log',{name:'Assistant 대화'});
  await expect(details).not.toHaveAttribute('open','');
  await expect(page.getByTestId('model-status-summary')).toContainText('Approval required');
  await expect(page.getByTestId('yolo-status-summary')).toContainText('F · 1 objects');
  await expect(page.getByTestId('edit-raw-mask')).not.toBeVisible();
  await page.getByTestId('confirm-mask').click();
  await expect(page.getByTestId('model-status-summary')).toContainText('PASS · APPROVED');
  const closed=(await chat.boundingBox())!.height;
  await details.locator('summary').click();
  await expect(details).toHaveAttribute('open','');
  await expect(page.getByRole('button',{name:'모델 출력 보기',exact:true})).toBeVisible();
  await page.getByTestId('yolo-summary').scrollIntoViewIfNeeded();
  await expect(page.getByTestId('yolo-summary')).toContainText('Class 0 0.93');
  await details.locator('summary').click();
  await expect(details).not.toHaveAttribute('open','');
  expect(closed).toBeGreaterThan(160);
  await expect(page.getByLabel('Assistant 메시지')).toBeVisible();
  await page.screenshot({path:'test-results/assistant-compact.png',fullPage:true});
});

test('FAIL/RAW warning remains visible when collapsed and never forces reopening',async({page,request})=>{
  await request.post('/api/test/native-output-mode',{data:{mode:'pass',segment_mode:'invalid'}});
  await prepare(page);
  const details=page.getByTestId('model-details');
  await expect(details).not.toHaveAttribute('open','');
  await expect(page.getByTestId('model-status-summary')).toContainText('VALIDATION FAILED');
  await details.locator('summary').click();await expect(page.getByTestId('edit-raw-mask')).toBeVisible();
  await details.locator('summary').click();
  await page.getByTestId('view-R').click();
  await expect(details).not.toHaveAttribute('open','');
  await expect(page.getByLabel('Assistant 메시지')).toBeVisible();
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
});

for(const size of [{width:1366,height:768},{width:390,height:844}])test(`assistant input stays reachable ${size.width}x${size.height}`,async({page})=>{
  await page.setViewportSize(size);await page.goto('/');
  const input=page.getByLabel('Assistant 메시지');await input.scrollIntoViewIfNeeded();
  await expect(input).toBeInViewport();await expect(page.getByRole('button',{name:'메시지 전송'})).toBeVisible();
  const dimensions=await page.evaluate(()=>({width:document.documentElement.scrollWidth}));
  expect(dimensions.width).toBeLessThanOrEqual(size.width);
  await expect(page.getByTestId('yolo-status-summary')).toContainText('unavailable');
});
