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

for(const retrievalMode of ['segment2_adapter','none'] as const){
test(`GPT ${retrievalMode}: generic POST, raw projection and immutable retrieval label`,async({page})=>{
  const artifact='a74979e5-bb74-45d3-83af-5cf8f1e27c14';let calls=0;let selectedBackend='gpt';
  await page.route('**/api/models/status',async route=>{
    const r=await route.fetch(),v=await r.json();v.vla={backend:selectedBackend,configured:true,ready:true,state:'READY',code:null,reference_mode:'native',retrieval_mode:retrievalMode};
    await route.fulfill({json:v});
  });
  await page.route('**/api/weld/*/final-trajectory',async route=>{
    calls++;expect(route.request().method()).toBe('POST');expect(route.request().postDataJSON()).toEqual({});
    const url=route.request().url().replace('/final-trajectory','');const r=await page.request.get(url);const job=await r.json();
    job.state='VLA_READY';job.vla_prediction={artifact_id:artifact,attempt_id:artifact,sample_id:job.scene.sample_id,split:'train',source:'vlm_final_gpt',provider:'gpt',
      point_count:33,model:'gpt-6-luna',retrieval_mode:retrievalMode,coordinate_frame:'source_robot_frame_unaligned_with_isaac',ade_mm:.3,fde_mm:.3,mask_views:['F'],physical_robot_executable:false};
    job.raw_final_prediction={artifact_id:artifact,attempt_id:artifact,source:'vlm_final_gpt',provider:'gpt',displayable:true,point_count:33,omitted_point_count:0,
      retrieval_mode:retrievalMode,coordinate_frame:'source_robot_frame_unaligned_with_isaac',units:'mm',validation_status:'PASS',simulator_eligible:true,display_url:`/api/weld/${job.id}/final-trajectory/${artifact}/display`};
    await route.fulfill({json:job});
  });
  await page.route('**/final-trajectory/*/display',route=>route.fulfill({json:{artifact_id:artifact,coordinate_frame:'source_robot_frame_unaligned_with_isaac',units:'mm',
    runs:[Array.from({length:33},(_,i)=>[i,i/2,1])]}}));
  await plan(page);
  await expect(page.getByTestId('run-guided-vla')).toContainText('GPT 최종 3D 궤적 예측');
  await expect(page.getByTestId('final-predictor-source')).toHaveText('Predictor: vlm_final_gpt');
  await expect(page.getByLabel('Model status')).toContainText('GPT Final');
  await page.getByTestId('run-guided-vla').click();
  await expect(page.getByTestId('vla-summary')).toContainText('GPT Trajectory · Final 3D Trajectory');
  await expect(page.getByTestId('final-raw-output').getByRole('img')).toBeVisible();
  await expect(page.getByTestId('result-retrieval-mode')).toContainText(retrievalMode==='none'?'Retrieval: None':'Retrieval: Segment2 Adapter');
  if(retrievalMode==='none')await expect(page.getByTestId('result-retrieval-mode')).toContainText('예측 정확도 미검증');
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
}

test('validation failure preserves finite runs and Path access, blocks Robot only',async({page})=>{
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
  await expect(page.getByTestId('final-raw-output')).toContainText('Robot: BLOCKED');
  await expect(page.getByTestId('final-raw-output').locator('polyline')).toHaveCount(2);
  await page.getByRole('tab',{name:'시뮬레이션',exact:true}).click();
  await expect(page.getByTestId('current-vla-path-preview')).toBeEnabled();
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
});

test('invalid H5 known start has a safe reason and preserves approved Rough state',async({page})=>{
  let calls=0;
  await page.route('**/api/weld/*/final-trajectory',route=>{
    calls++;
    return route.fulfill({status:503,json:{code:'GPT_TRAJECTORY_KNOWN_START_INVALID',detail:'현재 샘플 H5의 시작 XYZ가 유효하지 않습니다. 모델을 실행하지 않았습니다.'}});
  });
  await plan(page);await page.getByTestId('run-guided-vla').click();
  await expect(page.getByText('현재 샘플 H5의 시작 XYZ가 유효하지 않습니다. 모델을 실행하지 않았습니다.',{exact:false})).toBeVisible();
  expect(calls).toBe(1);
  await expect(page.getByTestId('final-raw-output')).toHaveCount(0);
  await expect(page.getByTestId('confirm-mask')).toBeDisabled();
});
