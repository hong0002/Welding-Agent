import {expect,test} from '@playwright/test';

test('stale foreign XYZ survives missing current result, IK and unavailable simulator',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  const artifact='5281ceea-654e-4d31-b32a-c217f299932f';
  job.vla_prediction=null;job.raw_final_prediction=null;job.state='INSTRUCTION_READY';
  job.latest_final_attempt={status:'FAILED',error_code:'GPT_TRAJECTORY_PROCESS_FAILED',new_output_available:false};
  const states={OUTPUT_EXISTS:true,OUTPUT_RENDERABLE:true,OUTPUT_VALIDATED:false,OUTPUT_APPROVED:false,CURRENT_RESULT:false,STALE_RESULT:true,SIMULATION_VISUALIZABLE:true,ROBOT_PLAYBACK_READY:false,PHYSICAL_EXECUTION_READY:false};
  const row={id:artifact,stage:'final',label:'GPT Previous Raw',stale:true,dimensions:3,sample_id:'FOREIGN_SAMPLE',current_overlay_allowed:false,
    runs:[[[0,0,0],[1,1,1]],[[2,2,2],[3,3,3]]],coordinate_frame:'unknown',units:'unknown',states,warnings:['IK_FAIL','UNVERIFIED_SOURCE_EVIDENCE']};
  const base=await(await request.get('/api/simulator/status')).json();
  const status={...base,current_preview:{...base.current_preview,configured:false,state:'STOPPED',configuration_codes:['CURRENT_PREVIEW_LAUNCHER_NOT_CONFIGURED']}};
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route(`**/api/weld/${job.id}`,r=>r.fulfill({json:job}));
  await page.route('**/api/weld/*/model-outputs',r=>r.fulfill({json:{job_id:job.id,outputs:[row]}}));
  await page.route('**/api/simulator/status',r=>r.fulfill({json:status}));
  let calls=0;
  await page.route('**/api/simulator/path-preview',r=>{calls++;expect(r.request().postDataJSON()).toEqual({job_id:job.id,artifact_id:artifact,output_kind:'final'});return r.fulfill({status:202,json:{...status,path_view:{viewer_mode:'WEB_SOURCE_FRAME',display:row,reason_code:'SIMULATOR_UNAVAILABLE_WEB_VIEW_AVAILABLE'}}});});
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('INSTRUCTION_READY');
  await page.locator('#tab-simulator').click();
  const viewer=page.getByTestId('simulator-output-browser');
  await expect(viewer.getByTestId('last-available-result')).toBeVisible();
  await expect(viewer.locator('polyline')).toHaveCount(2);
  await expect(viewer).toContainText('FOREIGN_SAMPLE');await expect(viewer).toContainText('STALE / PREVIOUS');
  await expect(page.getByTestId('current-vla-path-preview')).toBeEnabled();
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  await page.getByTestId('current-vla-path-preview').click();await expect.poll(()=>calls).toBe(1);
  await expect(page.getByTestId('path-viewer-mode')).toContainText('WEB_SOURCE_FRAME');
  await expect(viewer.locator('polyline')).toHaveCount(2);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});

test('rejected refinement, unapproved PNG and independent multi-region paths accessible',async({page,request})=>{
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  const states={OUTPUT_EXISTS:true,OUTPUT_RENDERABLE:true,OUTPUT_VALIDATED:false,OUTPUT_APPROVED:false,ROBOT_PLAYBACK_READY:false,PHYSICAL_EXECUTION_READY:false};
  const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jX1sAAAAASUVORK5CYII=';
  const rows=[{id:'raw-mask',stage:'segment',label:'AI Segment2 Raw',stale:false,states,mask_urls:{F:png}},
    {id:'refine',stage:'segment',label:'AI Refined from Manual',stale:true,states,mask_urls:{F:png},warnings:['REMOVED_REGION_RESTORED']},
    {id:'rough',stage:'trajectory',label:'Trajectory3 Raw',stale:false,states,segments:[{runs:[[[0,0],[1,1]],[[3,3],[4,4]]]},{runs:[[[10,10],[11,11]]]}]}];
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route('**/api/weld/*/model-outputs',r=>r.fulfill({json:{job_id:job.id,outputs:rows}}));
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');await page.locator('#tab-path').click();
  const viewer=page.getByTestId('output-browser');if(!await viewer.evaluate(e=>(e as HTMLDetailsElement).open))await viewer.locator('summary').click();
  await page.getByLabel('Model output source').selectOption('segment:raw-mask');await expect(viewer.locator('img')).toBeVisible();
  await page.getByLabel('Model output source').selectOption('segment:refine');await expect(viewer).toContainText('REMOVED_REGION_RESTORED');await expect(viewer.locator('img')).toBeVisible();
  await page.getByLabel('Model output source').selectOption('trajectory:rough');await expect(viewer.locator('polyline')).toHaveCount(3);
});
