import {expect,test} from '@playwright/test';

test('STP native layout uses exact OBJ and separates Path/Robot readiness and UUID-only actions',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  const base=await(await request.get('/api/simulator/status')).json();
  await page.route('**/api/agent/sessions/*/history',route=>route.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  const status={...base,backend:'dataset_stp',current_preview:{...base.current_preview,backend:'dataset_stp',configured:true,
    configuration_codes:[],configuration_errors:[],state:'STOPPED',robot_configuration:{configured:true,configuration_codes:[],configuration_errors:[]}}};
  let support={backend:'dataset_stp',sample_id:job.scene.sample_id,family:'B_PP',point_count:9,source_point_count:9,
    playback_point_count:17,cad_source:'OBJ',native_layout:'stp_reference_layout',environment_source:'stp_reference_layout',
    path_preview_ready:true,robot_preview_ready:false,workpiece_preview_ready:true,robot_preflight_available:true,
    configuration_codes:[],warnings:['SIMULATOR_STP_UNVALIDATED_SCENE']};
  const posts:{url:string;body:unknown}[]=[];
  await page.route('**/api/simulator/status',route=>route.fulfill({json:status}));
  await page.route('**/api/simulator/current-vla/capabilities?*',route=>route.fulfill({json:support}));
  await page.route('**/api/simulator/current-vla/preview-preflight',route=>{
    posts.push({url:route.request().url(),body:route.request().postDataJSON()});
    support={...support,robot_preview_ready:true};return route.fulfill({json:support});
  });
  await page.route('**/api/simulator/preview-current-vla**',route=>{
    posts.push({url:route.request().url(),body:route.request().postDataJSON()});return route.fulfill({status:202,json:status});
  });
  await page.route('**/api/simulator/path-preview',route=>{
    posts.push({url:route.request().url(),body:route.request().postDataJSON()});return route.fulfill({status:202,json:{...status,path_view:{viewer_mode:'REGISTERED_SCENE'}}});
  });
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');
  await page.locator('#tab-simulator').click();
  await expect(page.getByTestId('simulator-order')).toContainText('1. 경로 보기 → 2. 로봇 준비 확인');
  await expect(page.getByRole('navigation',{name:'Workflow progress'}).getByRole('button',{name:'Validate',exact:true})).toHaveCount(0);
  await expect(page.getByTestId('legacy-replay')).toHaveCount(0);
  await expect(page.getByTestId('current-vla-path-preview')).toHaveClass(/primary/);
  await expect(page.getByTestId('simulator-backend')).toContainText('Dataset Simulator STP');
  await expect(page.getByTestId('simulator-cad-source')).toContainText('Layout: STP Reference Environment');
  await expect(page.getByTestId('simulator-cad-source')).toContainText('Workpiece CAD: Exact Sample OBJ');
  await expect(page.getByTestId('simulator-cad-source')).not.toContainText('STEP');
  await expect(page.getByTestId('current-preview-support')).toContainText('Path Preview Ready');
  await expect(page.getByTestId('current-preview-support')).toContainText('Robot Preview Pending');
  await expect(page.getByTestId('source-playback-count')).toContainText('9 points');
  await expect(page.getByTestId('source-playback-count')).toContainText('17 points');
  await expect(page.getByTestId('current-vla-path-preview')).toBeEnabled();
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  await page.getByTestId('current-vla-path-preview').click();
  await expect.poll(()=>posts.length).toBe(1);
  await page.getByTestId('simulator2-preflight').click();
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  await page.getByTestId('current-vla-preview').click();
  await expect.poll(()=>posts.length).toBe(3);
  expect(posts[0].url).toMatch(/simulator\/path-preview$/);
  expect(posts[1].url).toMatch(/preview-preflight$/);
  expect(posts[2].url).toMatch(/preview-current-vla$/);
  for(const post of posts)expect(post.body).toEqual({job_id:job.id});
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});
