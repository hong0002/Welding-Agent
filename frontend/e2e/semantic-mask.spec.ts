import {expect,test,type Page} from '@playwright/test';

test.afterEach(async({request})=>{
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
});

async function send(page:Page,message:string){
  const before=await page.locator('.agent-message.assistant').count();
  await page.getByLabel('Assistant 메시지',{exact:true}).fill(message);
  await page.getByLabel('Assistant 메시지',{exact:true}).press('Enter');
  await expect(page.locator('.agent-message.assistant')).toHaveCount(before+1);
  await expect(page.getByLabel('Assistant 메시지',{exact:true})).toBeEnabled();
}

test('SDK edit then conditioned refinement refreshes Canvas as unapproved AI Refined from Manual',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  await request.post('/api/test/native-output-mode',{data:{mode:'pass',multi:true}});
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  const response=page.waitForResponse('**/api/masks/automatic');
  await page.getByTestId('native-segment').click();
  const initial=await(await response).json();
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  await request.post('/api/test/semantic-action',{data:{action:'MASK_EDIT'}});
  await send(page,'왼쪽은 이미 용접했어. 왼쪽 부분은 제거해줘');
  await expect(page.getByTestId('mask-source')).toHaveText('Manual edited');
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  await expect(page.getByTestId('agent-decision-summary')).toContainText('현재 마스크 영역 수정');
  const edited=await(await request.get(`/api/weld/${initial.id}`)).json();
  expect(edited.mask.approved).toBe(false);expect(edited.mask.edited_from_mask_id).toBe(initial.mask.id);
  expect(edited.mask.regions).toHaveLength(1);
  await expect.poll(()=>page.getByTestId('drawing-surface').evaluate(host=>{
    const canvas=host.querySelectorAll('canvas')[1];const c=canvas.getContext('2d')!;
    const alpha=(x:number)=>c.getImageData(Math.round(canvas.width*x),Math.round(canvas.height*.2),1,1).data[3];
    return [alpha(.25),alpha(.75)];
  })).toEqual([0,255]);
  const maskBefore=edited.mask.id;
  await request.post('/api/test/semantic-action',{data:{action:'MASK_REFINE'}});
  await send(page,'내가 수정한 마스크 기준으로 다시 보정해줘');
  await expect(page.getByTestId('mask-source')).toHaveText('AI Refined from Manual');
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  const refined=await(await request.get(`/api/weld/${initial.id}`)).json();
  expect(refined.mask.id).not.toBe(maskBefore);expect(refined.mask.edited_from_mask_id).toBe(maskBefore);
  expect(refined.mask.approved).toBe(false);expect(refined.mask.approved_at).toBe(null);
  expect(refined.mask.regions).toHaveLength(1);
  await expect(page.getByTestId('confirm-mask')).toBeEnabled();
  const counts=await(await request.get('/api/test/native-call-counts')).json();
  expect(counts).toMatchObject({...before,segment:before.segment+1,refine:before.refine+1});
});

test('refinement restoration failure preserves manual draft and raw output without redetection',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  await request.post('/api/test/native-output-mode',{data:{mode:'pass',multi:true}});
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  const response=page.waitForResponse('**/api/masks/automatic');
  await page.getByTestId('native-segment').click();const initial=await(await response).json();
  await request.post('/api/test/semantic-action',{data:{action:'MASK_EDIT'}});
  await send(page,'왼쪽은 제거해줘');
  const edited=await(await request.get(`/api/weld/${initial.id}`)).json();
  await request.post('/api/test/semantic-action',{data:{action:'MASK_REFINE',refinement_mode:'restore'}});
  await send(page,'현재 수정한 마스크 기준으로 보정해줘');
  await expect(page.getByTestId('agent-reason-code')).toHaveText('MASK_REFINEMENT_CONSTRAINT_VIOLATION');
  await expect(page.getByTestId('mask-source')).toHaveText('Manual edited');
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  const failed=await(await request.get(`/api/weld/${initial.id}`)).json();
  expect(failed.mask.id).toBe(edited.mask.id);expect(failed.raw_segment_output.validation.status).toBe('FAIL');
  expect(failed.raw_segment_output.model_output.mask_urls.F).toContain('/model-output/segment/F/image');
  expect(await(await request.get('/api/test/native-call-counts')).json()).toMatchObject({...before,segment:before.segment+1,refine:before.refine+1});
});

test('SDK Trajectory3 draws two independent native lines without a bridge or final call',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  await request.post('/api/test/native-output-mode',{data:{mode:'pass',multi:true}});
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await page.getByTestId('native-segment').click();await page.getByTestId('confirm-mask').click();
  await request.post('/api/test/semantic-action',{data:{action:'ROUGH_TRAJECTORY_GENERATE'}});
  await send(page,'이 두 영역의 가궤적 예측해줘');
  await expect(page.getByTestId('workflow-state')).toHaveText('ROUGH_PATH_READY');
  await expect(page.getByTestId('decision-region-count')).toContainText('2개 region · 2개 독립 segment');
  await expect(page.getByLabel('Agent 작업 진행')).toContainText('Trajectory3 가궤적');
  await expect.poll(()=>page.getByTestId('drawing-surface').evaluate(()=>{
    const stage=(window as any).Konva.stages.find((s:any)=>s.container().closest('[data-testid="drawing-surface"]'));
    return stage.find('.native-model-path').map((line:any)=>line.points());
  })).toEqual([[10,20,40,20],[60,20,90,20]]);
  const counts=await(await request.get('/api/test/native-call-counts')).json();
  expect(counts).toMatchObject({...before,segment:before.segment+1,rough3d:before.rough3d+1});
});
