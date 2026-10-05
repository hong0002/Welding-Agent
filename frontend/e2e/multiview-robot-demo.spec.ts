import {test,expect} from '@playwright/test';
import {parseDecision,preflightDecision} from '../src/agentDecision';

for(const views of [['R'],['F','R','S4']])test(`GPT input views visible: ${views.join('+')}`,async({page,request})=>{
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  job.vla_prediction=null;job.state='MASK_READY';job.mask.approved=false;
  const artifact='65822d00-a386-403e-b003-de0abfcb520e';
  job.raw_final_prediction={artifact_id:artifact,attempt_id:artifact,source:'vlm_final_gpt',provider:'gpt',
    displayable:true,point_count:3,units:'mm',coordinate_frame:'source_robot_start_relative_mm',validation_status:'FAIL',
    simulator_eligible:false,mask_views:views,mask_provenance:Object.fromEntries(views.map(v=>[v,['UNAPPROVED']])),
    display_url:`/api/weld/${job.id}/final-trajectory/${artifact}/display`};
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route(`**/api/weld/${job.id}`,r=>r.fulfill({json:job}));
  await page.route('**/api/weld/*/final-trajectory/*/display',r=>r.fulfill({json:{artifact_id:artifact,units:'mm',coordinate_frame:'source_robot_start_relative_mm',runs:[[[0,0,0],[1,1,0],[2,0,0]]]}}));
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('MASK_READY');await page.locator('#tab-path').click();
  await expect(page.getByTestId('final-mask-conditioning')).toHaveText(`Mask conditioning: ${views.join(' + ')}`);
  await expect(page.getByTestId('final-raw-output')).toContainText('UNAPPROVED');
  const safe={...preflightDecision('MASK_APPROVAL_REQUIRED'),final_predictor:'gpt',mask_conditioning_views:views};
  expect(parseDecision(safe)?.mask_conditioning_views).toEqual(views);
  expect(parseDecision({...safe,mask_conditioning_views:['C:/private']})).toBeNull();
});

test('absolute unapproved GPT selects strict without cached robot readiness',async({page,request})=>{
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();job.vla_prediction=null;job.state='MASK_READY';job.mask.approved=false;
  const artifact='65822d00-a386-403e-b003-de0abfcb520e';
  const row={id:artifact,stage:'final',label:'GPT Absolute',dimensions:3,stale:false,sample_id:job.scene.sample_id,
    units:'mm',coordinate_frame:'source_robot_frame_unaligned_with_isaac',runs:[[[10,20,30],[11,21,31]]],
    states:{OUTPUT_RENDERABLE:true,OUTPUT_VALIDATED:false,OUTPUT_APPROVED:false,ROBOT_PLAYBACK_READY:false}};
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route(`**/api/weld/${job.id}`,r=>r.fulfill({json:job}));
  await page.route('**/api/weld/*/model-outputs',r=>r.fulfill({json:{job_id:job.id,outputs:[row]}}));
  await page.route('**/api/simulator/status',async r=>{
    const status=await(await request.get('/api/simulator/status')).json();
    await r.fulfill({json:{...status,backend:'dataset_stp',current_preview:{...status.current_preview,backend:'dataset_stp'}}});
  });
  let calls=0;
  await page.route('**/api/simulator/robot-preview',async r=>{
    calls++;expect(r.request().postDataJSON()).toEqual({job_id:job.id,artifact_id:artifact,output_kind:'final'});
    const status=await(await request.get('/api/simulator/status')).json();
    await r.fulfill({status:202,json:{...status,robot_view:{mode:'STRICT'}}});
  });
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('MASK_READY');await page.locator('#tab-simulator').click();
  await expect(page.getByTestId('robot-preview-mode')).toContainText('STRICT ROBOT PREVIEW');
  await expect(page.getByTestId('simulator-cad-source')).toContainText('Exact Sample OBJ');
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Prediction Source: GPT Absolute');
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Playback: CURRENT ABSOLUTE PREDICTION');
  await expect(page.getByTestId('simulator-cad-source')).toContainText('Scene: CURRENT SAMPLE · STP');
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Source Points: 2');
  await page.getByRole('button',{name:'로봇 시뮬레이션 보기',exact:false}).click();await expect.poll(()=>calls).toBe(1);
  await expect(page.getByTestId('current-vla-sim')).toBeDisabled();
});

test('raw relative unapproved XYZ allows robot demo action; only simulation request',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();job.vla_prediction=null;job.state='MASK_READY';job.mask.approved=false;
  const artifact='65822d00-a386-403e-b003-de0abfcb520e';
  const row={id:artifact,stage:'final',label:'GPT Raw Relative',dimensions:3,stale:false,sample_id:job.scene.sample_id,
    units:'mm',coordinate_frame:'source_robot_start_relative_mm',runs:[[[0,0,0],[1,1,1],[2,0,1]]],
    states:{OUTPUT_RENDERABLE:true,OUTPUT_VALIDATED:false,OUTPUT_APPROVED:false,ROBOT_PLAYBACK_READY:false}};
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route(`**/api/weld/${job.id}`,r=>r.fulfill({json:job}));
  await page.route('**/api/weld/*/model-outputs',r=>r.fulfill({json:{job_id:job.id,outputs:[row]}}));
  let calls=0;
  await page.route('**/api/simulator/robot-preview',async r=>{
    calls++;expect(r.request().method()).toBe('POST');expect(r.request().postDataJSON()).toEqual({job_id:job.id,artifact_id:artifact,output_kind:'final'});
    const status=await(await request.get('/api/simulator/status')).json();
    await r.fulfill({status:202,json:{...status,robot_view:{mode:'DEMO',robot_demo_only:true,physical_execution:false}}});
  });
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('MASK_READY');await page.locator('#tab-simulator').click();
  const button=page.getByRole('button',{name:'로봇 시뮬레이션 보기',exact:false});await expect(button).toBeEnabled();
  await expect(page.getByTestId('robot-preview-mode')).toContainText('DEMO ROBOT PREVIEW');await button.click();await expect.poll(()=>calls).toBe(1);
  await expect(page.getByTestId('prediction-source-identity')).toContainText('TRANSFORMED FROM CURRENT PREDICTION');
  await expect(page.getByTestId('prediction-source-identity')).toContainText('GT PATH: NOT USED FOR ROBOT PLAYBACK');
  await expect(page.getByTestId('simulator-output-browser').getByTestId('original-prediction-label')).toContainText('Original Prediction');
  await expect(page.getByTestId('current-vla-sim')).toBeDisabled();
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});
