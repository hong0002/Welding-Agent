import {expect,test,type Page} from '@playwright/test';

async function scene(page:Page){
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
}
async function plan(page:Page){
  await scene(page);await page.getByTestId('native-segment').click();
  await page.getByTestId('confirm-mask').click();
  await page.getByText('수동 지시 / 디버그',{exact:true}).click();
  await page.getByRole('button',{name:'지시 분석',exact:true}).click();
  await page.getByRole('tab',{name:'경로 계획',exact:true}).click();
  await page.getByRole('button',{name:'용접 경로 생성',exact:true}).click();
}
async function lines(page:Page){return page.getByTestId('drawing-surface').evaluate(()=>{
  const stage=(window as any).Konva.stages.find((s:any)=>s.container().closest('[data-testid="drawing-surface"]'));
  return stage.find('.native-model-path').map((l:any)=>({points:l.points(),dash:l.dash()}));
});}

test('hard acceptance failure still automatically shows native geometry and blocked VLA',async({page,request})=>{
  await request.post('/api/test/native-output-mode',{data:{mode:'hard'}});
  await plan(page);
  await expect(page.getByTestId('trajectory3-output-summary')).toContainText('OUTPUT_RAW_DISPLAYABLE');
  await expect(page.getByTestId('native-path-label')).toContainText('검증 미통과');
  await expect(page.getByTestId('run-guided-vla')).toBeDisabled();
  expect(await lines(page)).toHaveLength(1);
  await page.getByTestId('view-R').click();
  await page.getByTestId('show-native-output').click();
  await expect(page.getByTestId('view-F')).toHaveAttribute('aria-selected','true');
  // Changing the local instruction cannot hide generated geometry.
  await page.getByRole('tab',{name:'Assistant',exact:true}).click();
  await page.getByLabel('용접 방향을 입력하세요').fill('오른쪽에서 왼쪽으로 용접해');
  await expect(page.getByTestId('native-path-label')).toBeVisible();
  await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await expect(page.getByTestId('native-path-label')).toHaveCount(0);
  await expect(page.getByTestId('segment2-output-summary')).toHaveCount(0);
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
});

test('partial finite path renders separate dotted runs, no edges across invalid points',async({page,request})=>{
  await request.post('/api/test/native-output-mode',{data:{mode:'finite_partial'}});
  await plan(page);
  await expect(page.getByTestId('trajectory3-output-summary')).toContainText('7 / 9 finite points displayed');
  await expect(page.getByTestId('native-path-label')).toContainText('PARTIAL');
  const paths=await lines(page);
  expect(paths.map((p:any)=>p.points.length)).toEqual([4,4,6]);
  expect(paths.every((p:any)=>p.dash.length===2&&p.dash[0]<p.dash[1])).toBe(true);
  await expect(page.getByTestId('run-guided-vla')).toBeDisabled();
  await page.screenshot({path:'test-results/model-output-partial.png',fullPage:true});
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
});

test('foreign model output is diagnostic only, never overlays the current Canvas',async({page,request})=>{
  await request.post('/api/test/native-output-mode',{data:{mode:'foreign'}});
  await plan(page);
  await expect(page.getByTestId('foreign-model-output')).toBeVisible();
  await expect(page.getByTestId('native-path-label')).toHaveCount(0);
  expect(await lines(page)).toEqual([]);
  await expect(page.getByTestId('run-guided-vla')).toBeDisabled();
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
});

test('invalid Segment mask stays visible, can be explicitly reviewed and edited',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  await request.post('/api/test/native-output-mode',{data:{mode:'pass',segment_mode:'invalid'}});
  await scene(page);await page.getByTestId('native-segment').click();
  await expect(page.getByTestId('segment2-output-summary')).toContainText('OUTPUT_RAW_DISPLAYABLE');
  await expect(page.getByTestId('segment2-output-summary')).toContainText('BLOCKED');
  await expect(page.getByTestId('raw-mask-label')).toBeVisible();
  await expect(page.getByTestId('confirm-mask')).toBeDisabled();
  await page.getByTestId('model-details').locator('summary').click();
  await page.getByTestId('edit-raw-mask').click();
  await expect(page.getByTestId('confirm-mask')).toBeEnabled();
  const surface=await page.getByTestId('drawing-surface').boundingBox();
  if(!surface)throw new Error('Canvas not loaded');
  await page.mouse.move(surface.x+surface.width*.2,surface.y+surface.height*.2);
  await page.mouse.down();await page.mouse.move(surface.x+surface.width*.3,surface.y+surface.height*.2);await page.mouse.up();
  const saved=page.waitForResponse('**/api/masks/manual');
  await page.getByTestId('confirm-mask').click();
  const job=await(await saved).json();
  expect(job.mask.mask_source).toBe('manual_edited');expect(job.mask.approved).toBe(true);
  expect(job.rough3d).toBeNull();expect(job.vla_prediction).toBeNull();
  await expect(page.getByTestId('mask-status')).toHaveText('확정됨');
  const counts=await(await request.get('/api/test/native-call-counts')).json();
  expect(counts.guided_vla).toBe(before.guided_vla);
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
});
