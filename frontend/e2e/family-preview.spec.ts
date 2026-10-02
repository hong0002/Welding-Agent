import {expect,test} from '@playwright/test';

test('B_PP current artifact enables only Path Preview and shows safe errors without model calls',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  await page.route('**/api/agent/sessions/*/history',route=>route.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  const posts:{url:string;body:unknown}[]=[];
  page.on('request',r=>{if(r.method()==='POST')posts.push({url:r.url(),body:r.postDataJSON()});});
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');
  await page.locator('#tab-simulator').click();
  await expect(page.getByTestId('current-preview-support')).toContainText('Path Preview Ready');
  await expect(page.getByTestId('current-preview-support')).toContainText('Robot Preview Pending');
  await expect(page.getByTestId('current-vla-path-preview')).toBeEnabled();
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  await expect(page.getByTestId('current-vla-sim')).toBeDisabled();
  await expect(page.getByTestId('current-vla-gate')).toContainText('B_PP_03_0001');
  let body:unknown;
  await page.route('**/api/simulator/preview-current-vla/path',route=>{
    body=route.request().postDataJSON();
    return route.fulfill({status:409,json:{code:'PREVIEW_H5_MISMATCH',detail:'Current sample GT/frame does not match H5.'}});
  });
  await page.getByTestId('current-vla-path-preview').click();
  await expect(page.getByRole('tabpanel',{name:'시뮬레이션'}).getByRole('alert')).toContainText('PREVIEW_H5_MISMATCH');
  expect(body).toEqual({job_id:job.id});
  expect(posts.filter(p=>/preview-current-vla/.test(p.url))).toHaveLength(1);
  expect(posts.some(p=>/segment|guided-vla|weld\/plan|run-sample|simulator\/start/.test(p.url))).toBe(false);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});

test('dataset v2 separates source/playback counts and explicit offline preflight',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  const base=await(await request.get('/api/simulator/status')).json();
  const status={...base,backend:'dataset_v2',current_preview:{...base.current_preview,backend:'dataset_v2',configured:true,
    robot_configuration:{configured:true,configuration_errors:[],configuration_codes:[]},state:'STOPPED'}};
  const support={sample_id:job.scene.sample_id,family:'B_PP',point_count:9,source_point_count:9,playback_point_count:null,
    backend:'dataset_v2',path_preview_ready:true,workpiece_preview_ready:true,robot_preview_ready:false,robot_preflight_available:true,
    fixture_ready:false,simulation_only:true,physical_robot_executable:false,validated_simulation:false,
    configuration_codes:[],warnings:[],robot_reason_code:'SIMULATOR2_ROBOT_PREFLIGHT_REQUIRED'};
  await page.route('**/api/agent/sessions/*/history',route=>route.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route('**/api/simulator/status',route=>route.fulfill({json:status}));
  await page.route('**/api/simulator/current-vla/capabilities?*',route=>route.fulfill({json:support}));
  let preflightBody:unknown;let previewBody:unknown;
  await page.route('**/api/simulator/current-vla/preview-preflight',route=>{
    preflightBody=route.request().postDataJSON();
    return route.fulfill({json:{...support,robot_preview_ready:true,playback_point_count:17,robot_reason_code:undefined}});
  });
  await page.route('**/api/simulator/preview-current-vla',route=>{previewBody=route.request().postDataJSON();return route.fulfill({status:202,json:status});});
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');
  await page.locator('#tab-simulator').click();
  await expect(page.getByTestId('simulator-backend')).toContainText('Dataset Simulator v2');
  await expect(page.getByTestId('source-playback-count')).toContainText('9 points');
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  await page.getByTestId('simulator2-preflight').click();
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  await expect(page.getByTestId('source-playback-count')).toContainText('17 points · Simulator playback interpolation');
  await page.getByTestId('current-vla-preview').click();
  await expect.poll(()=>previewBody).toEqual({job_id:job.id});
  expect(preflightBody).toEqual({job_id:job.id});
  await expect(page.getByTestId('current-vla-sim')).toBeDisabled();
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});

test('dataset v2 capture warnings display separately from successful playback',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  const base=await(await request.get('/api/simulator/status')).json();
  const status={...base,current_preview:{...base.current_preview,backend:'dataset_v2',state:'READY',error:null,can_stop:true,
    latest:{backend:'dataset_v2',status:'SUCCEEDED',job_id:job.id,artifact_id:job.vla_prediction.artifact_id,
      package_id:'offline',sample_id:job.scene.sample_id,point_count:9,source_point_count:9,playback_point_count:17,
      kind:'robot',robot_motion:true,exact_xyz_preserved:true,error:null,playback_status:'SUCCEEDED',capture_status:'PARTIAL_FAILED',
      reason_code:'SIMULATOR2_CAPTURE_WARNING',capture_warning_codes:['CAPTURE_FILE_MISSING_TIMEOUT','C:/private/secret-prompt']}}};
  await page.route('**/api/agent/sessions/*/history',route=>route.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route('**/api/simulator/status',route=>route.fulfill({json:status}));
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');
  await page.locator('#tab-simulator').click();
  await expect(page.getByTestId('current-preview-status')).toContainText('READY SUCCEEDED');
  const diag=page.getByTestId('current-preview-diagnostics');
  await expect(diag).toContainText('Playback: SUCCEEDED');
  await expect(diag).toContainText('Capture: PARTIAL_FAILED');
  await expect(diag).toContainText('CAPTURE_FILE_MISSING_TIMEOUT');
  await expect(diag).not.toContainText('private');
  await expect(page.getByTestId('current-vla-gate')).not.toContainText('SIMULATOR2_PLAYBACK_FAIL');
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});
