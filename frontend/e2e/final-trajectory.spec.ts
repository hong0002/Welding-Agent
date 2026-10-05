import {expect,test,type Page} from '@playwright/test';

async function plan(page:Page){
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await page.getByTestId('native-segment').click();await page.getByTestId('confirm-mask').click();
  await page.getByText('수동 지시 / 디버그',{exact:true}).click();
  await page.getByRole('button',{name:'지시 분석',exact:true}).click();
  await page.getByRole('tab',{name:'경로 계획',exact:true}).click();
  await page.getByRole('button',{name:'용접 경로 생성',exact:true}).click();
}

test('GPT source, generic relative POST, raw projection and current Simulator source label',async({page})=>{
  const artifact='a74979e5-bb74-45d3-83af-5cf8f1e27c14';let calls=0;let selectedBackend='gpt';
  await page.route('**/api/models/status',async route=>{
    const r=await route.fetch(),v=await r.json();v.vla={backend:selectedBackend,configured:true,ready:true,state:'READY',code:null,reference_mode:'native'};
    await route.fulfill({json:v});
  });
  await page.route('**/api/weld/*/final-trajectory',async route=>{
    calls++;expect(route.request().method()).toBe('POST');expect(route.request().postDataJSON()).toEqual({});
    const url=route.request().url().replace('/final-trajectory','');const r=await page.request.get(url);const job=await r.json();
    job.state='VLA_READY';job.vla_prediction={artifact_id:artifact,attempt_id:artifact,sample_id:job.scene.sample_id,split:'train',source:'vlm_final_gpt',provider:'gpt',
      point_count:33,model:'gpt-6-luna',coordinate_frame:'source_robot_frame_unaligned_with_isaac',ade_mm:.3,fde_mm:.3,mask_views:['F'],physical_robot_executable:false};
    job.raw_final_prediction={artifact_id:artifact,attempt_id:artifact,source:'vlm_final_gpt',provider:'gpt',displayable:true,point_count:33,omitted_point_count:0,
      coordinate_frame:'source_robot_frame_unaligned_with_isaac',units:'mm',validation_status:'PASS',simulator_eligible:true,display_url:`/api/weld/${job.id}/final-trajectory/${artifact}/display`};
    await route.fulfill({json:job});
  });
  await page.route('**/final-trajectory/*/display',route=>route.fulfill({json:{artifact_id:artifact,coordinate_frame:'source_robot_frame_unaligned_with_isaac',units:'mm',
    runs:[Array.from({length:33},(_,i)=>[i,i/2,1])]}}));
  await plan(page);
  await expect(page.getByTestId('run-guided-vla')).toContainText('GPT Trajectory 실행');
  await page.getByTestId('run-guided-vla').click();
  await expect(page.getByTestId('vla-summary')).toContainText('GPT Trajectory · Final 3D Trajectory');
  await expect(page.getByTestId('final-raw-output').getByRole('img')).toBeVisible();
  await page.getByLabel('Final XYZ projection').selectOption('XZ');
  await expect(page.getByRole('img',{name:'Raw GPT XYZ XZ projection'})).toBeVisible();
  await expect(page.getByTestId('run-guided-vla')).toBeDisabled();expect(calls).toBe(1);
  // A changed runtime selection changes the action label, not an immutable old result's source.
  selectedBackend='guided';
  await expect(page.getByTestId('run-guided-vla')).toContainText('Guided VLA 실행',{timeout:15_000});
  await expect(page.getByTestId('vla-summary')).toContainText('GPT Trajectory · Final 3D Trajectory');
  expect(calls).toBe(1);
  await page.getByRole('tab',{name:'시뮬레이션',exact:true}).click();
  await expect(page.getByTestId('current-vla-gate')).toContainText('GPT Trajectory · Final 3D Trajectory');
});

test('validation failure refreshes raw output, preserves finite runs and blocks Simulator',async({page})=>{
  const artifact='0511fb08-a42a-4352-895e-528ae3ba0fd9';let failed=false;
  await page.route(/\/api\/weld\/[a-f0-9-]+$/,async route=>{
    const r=await route.fetch(),job=await r.json();
    if(failed)job.raw_final_prediction={artifact_id:artifact,attempt_id:artifact,source:'vlm_final_gpt',provider:'gpt',displayable:true,point_count:4,omitted_point_count:1,
      coordinate_frame:'camera_unknown',units:'mm',validation_status:'FAIL',simulator_eligible:false,display_url:`/api/weld/${job.id}/final-trajectory/${artifact}/display`};
    await route.fulfill({json:job});
  });
  await page.route('**/api/weld/*/final-trajectory',route=>{failed=true;return route.fulfill({status:503,json:{code:'GPT_TRAJECTORY_OUTPUT_INVALID',detail:'GPT 원본 결과는 보존했습니다. Simulator 차단.'}});});
  await page.route('**/final-trajectory/*/display',route=>route.fulfill({json:{artifact_id:artifact,coordinate_frame:'camera_unknown',units:'mm',runs:[[[0,0,0],[1,1,0]],[[4,4,0],[5,4,1]]]}}));
  await plan(page);await page.getByTestId('run-guided-vla').click();
  await expect(page.getByTestId('final-raw-output')).toContainText('FAIL');
  await expect(page.getByTestId('final-raw-output')).toContainText('표시 전용 · Simulator 차단');
  await expect(page.getByTestId('final-raw-output').locator('polyline')).toHaveCount(2);
  await page.getByRole('tab',{name:'시뮬레이션',exact:true}).click();
  await expect(page.getByTestId('current-vla-path-preview')).toBeDisabled();
});
