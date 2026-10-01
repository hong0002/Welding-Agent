import {expect,test} from '@playwright/test';

test('9 views → actual Canvas mask approval → Rough3D → Guided VLA_READY, simulator blocked',async({page,request})=>{
  const replay=process.env.WELD_TEST_REAL_ARTIFACT_REPLAY==='1';
  const sample=replay?'B_PR_03_0001':'SAMPLE_1';
  const simulatorActions:string[]=[];
  const pageErrors:string[]=[];
  let currentConfig:'ready'|'old'='ready';
  page.on('pageerror',err=>pageErrors.push(err.message));
  page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/api/simulator/'))simulatorActions.push(r.url());});
  // Current preview remains usable even when all existing replay settings are absent.
  await page.route('**/api/simulator/status',async route=>{
    const snapshot=await(await request.get('/api/simulator/status')).json();
    if(currentConfig==='old'){
      delete snapshot.current_preview.configured;
      delete snapshot.current_preview.configuration_errors;
      delete snapshot.current_preview.configuration_codes;
    }
    await route.fulfill({json:{...snapshot,configured:false,can_start:false,can_run_sample:false,
      existing_replay:{configured:false,errors:['WELD_SIM_SAMPLE_ID missing','WELD_SIM_DATA_ROOT missing','WELD_SIM_PREDICTION_ROOT missing']}}});
  });
  await page.goto('/');
  await page.getByLabel('Dataset sample ID').fill(sample);
  const loaded=page.waitForResponse('**/api/scenes/sample');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  expect((await(await loaded).json()).scene.sample_id).toBe(sample);
  const views=['B','F','L','R','S1','S2','S3','S4','T'];
  await expect(page.getByRole('tablist',{name:'Scene views'}).getByRole('tab')).toHaveCount(9);
  for(const view of views)await expect(page.getByTestId(`view-${view}`)).toBeVisible();
  await page.getByTestId('view-R').click();
  await expect(page.getByTestId('view-R')).toHaveAttribute('aria-selected','true');
  await expect(page.locator('.canvas-topline')).toContainText(`${sample} · R`);
  let replayInstructions:{segment:string;rough:string}|null=null;
  if(replay){
    replayInstructions=await(await request.get('/api/test/replay-instructions')).json();
    await page.getByText('수동 지시 / 디버그',{exact:true}).click();
    await page.locator('#instruction').fill(replayInstructions!.segment);
  }
  await page.getByTestId('native-segment').click();
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  await expect(page.getByTestId('view-F')).toHaveAttribute('aria-selected','true');
  for(const view of ['F','R','S4'])await expect(page.getByTestId(`view-${view}`)).toContainText('MASK');
  await expect.poll(()=>page.getByTestId('drawing-surface').evaluate(el=>{
    const canvas=el.querySelectorAll('canvas')[1];
    return Array.from(canvas.getContext('2d')!.getImageData(0,0,canvas.width,canvas.height).data).some((v,i)=>i%4===3&&v>0);
  })).toBeTruthy();
  await page.getByTestId('confirm-mask').click();
  await expect(page.getByTestId('view-F')).toContainText('APPROVED');
  await expect(page.getByTestId('view-R')).not.toContainText('APPROVED');
  if(replay)await page.locator('#instruction').fill(replayInstructions!.rough);
  else await page.getByText('수동 지시 / 디버그',{exact:true}).click();
  await page.getByRole('button',{name:'지시 분석',exact:true}).click();
  await expect(page.getByTestId('parsed-instruction')).toContainText('left_to_right');
  await page.getByRole('tab',{name:'경로 계획',exact:true}).click();
  await expect(page.getByLabel('Rough mode')).toHaveValue('native_3d');
  await page.getByRole('button',{name:'용접 경로 생성',exact:true}).click();
  await expect(page.getByTestId('rough3d-summary')).toContainText('2D guidance ready · 9 pts');
  await expect(page.getByTestId('workflow-state')).toHaveText('ROUGH_PATH_READY');
  await page.getByTestId('run-guided-vla').click();
  await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');
  await expect(page.getByTestId('vla-summary')).toContainText('9 points');
  await expect(page.getByTestId('run-guided-vla')).toBeDisabled();
  if(replay){
    await page.getByText('Native reference 3D 보기',{exact:true}).click();
    await expect.poll(()=>page.locator('.reference-preview').evaluate((img:HTMLImageElement)=>img.naturalWidth)).toBeGreaterThan(0);
    await page.screenshot({path:'test-results/module-integration-bpr-guidance.png',fullPage:true,animations:'disabled'});
  }
  await page.locator('#tab-simulator').click();
  await expect(page.getByTestId('current-vla-gate').getByText('VLA Prediction Ready',{exact:true})).toBeVisible();
  await expect(page.getByTestId('current-vla-gate')).toContainText('Simulator Fixture Pending');
  await expect(page.getByTestId('current-vla-sim')).toBeDisabled();
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  await expect(page.getByTestId('current-vla-path-preview')).toBeEnabled();
  await expect(page.getByTestId('current-preview-configuration')).toContainText('준비됨');
  await expect(page.getByRole('button',{name:'시뮬레이터 시작',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'기존 용접 샘플 실행',exact:true})).toBeDisabled();
  currentConfig='old';
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  await expect(page.getByText('Backend를 재시작한 후 Current Preview 설정을 확인하세요.',{exact:true})).toBeVisible();
  currentConfig='ready';
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  expect(simulatorActions).toEqual([]);
  expect(pageErrors).toEqual([]);
  await page.screenshot({path:`test-results/module-integration-${replay?'bpr-replay':'desktop'}.png`,fullPage:true,animations:'disabled'});
  // Offline route fixture: the actual new button sends current job ID only.
  let previewBody:unknown;
  await page.route('**/api/simulator/preview-current-vla',async route=>{
    previewBody=route.request().postDataJSON();
    const snapshot=await(await request.get('/api/simulator/status')).json();
    await route.fulfill({status:202,json:{...snapshot,current_preview:{configured:true,configuration_errors:[],configuration_codes:[],state:'STARTING',can_stop:true,pid:123,
      error:null,latest:{job_id:(previewBody as {job_id:string}).job_id,artifact_id:'fixture-current',package_id:'fixture-package',
      sample_id:sample,point_count:9,status:'QUEUED',kind:'robot',robot_motion:false,error:null}}}});
  });
  await page.getByTestId('current-vla-preview').click();
  expect(Object.keys(previewBody as object)).toEqual(['job_id']);
  expect((previewBody as {job_id:string}).job_id).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.getByTestId('current-preview-status')).toContainText('STARTING');
});

test('per-view unsaved edits survive switching and block planning until confirmation',async({page})=>{
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await page.getByTestId('native-segment').click();
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  await page.getByTestId('confirm-mask').click();
  await page.getByTestId('view-R').click();
  await page.getByRole('button',{name:'지우개',exact:true}).click();
  const box=(await page.getByTestId('drawing-surface').boundingBox())!;
  await page.mouse.move(box.x+box.width*.1,box.y+box.height*.2);await page.mouse.down();
  await page.mouse.move(box.x+box.width*.13,box.y+box.height*.2,{steps:3});await page.mouse.up();
  await expect(page.getByTestId('mask-source')).toHaveText('Manual edited');
  await page.getByTestId('view-F').click();
  await page.getByText('수동 지시 / 디버그',{exact:true}).click();
  await expect(page.getByRole('button',{name:'지시 분석',exact:true})).toBeDisabled();
  await page.getByTestId('view-R').click();
  await expect(page.getByTestId('mask-source')).toHaveText('Manual edited');
  const edited=page.waitForResponse('**/api/masks/manual');await page.getByTestId('confirm-mask').click();
  const job=await(await edited).json();
  expect(job.scene.views.R.mask.mask_source).toBe('manual_edited');
  expect(job.scene.views.F.mask.mask_source).toBe('vlm_segment');
  expect(job.scene.views.S4.mask.approved).toBe(false);
});
