import {expect,test} from '@playwright/test';

test('relative staged output, common state viewer, geometry allowed and robot blocked',async({page})=>{
  const artifact='1281ceea-654e-4d31-b32a-c217f299932f';let generated=false;let geometryCalls=0;
  const raw=(jobId:string)=>({artifact_id:artifact,attempt_id:artifact,source:'vlm_final_gpt',provider:'gpt',displayable:true,point_count:3,
    coordinate_frame:'gpt_start_relative_visualization_mm',coordinate_mode:'relative_visualization',units:'mm',validation_status:'FAIL',
    simulator_eligible:false,display_url:`/api/weld/${jobId}/final-trajectory/${artifact}/display`});
  await page.route('**/api/models/status',async route=>{const r=await route.fetch(),v=await r.json();v.vla={backend:'gpt',ready:true,configured:true,state:'READY'};await route.fulfill({json:v});});
  await page.route(/\/api\/weld\/[a-f0-9-]+$/,async route=>{const r=await route.fetch(),v=await r.json();if(generated)v.raw_final_prediction=raw(v.id);await route.fulfill({json:v});});
  await page.route('**/api/weld/*/final-trajectory',async route=>{
    const r=await page.request.get(route.request().url().replace('/final-trajectory',''));const v=await r.json();generated=true;v.raw_final_prediction=raw(v.id);await route.fulfill({json:v});
  });
  await page.route('**/final-trajectory/*/display',route=>route.fulfill({json:{artifact_id:artifact,coordinate_frame:'gpt_start_relative_visualization_mm',units:'mm',
    runs:[[[0,0,0],[1,1,1],[2,1,3]]],stages:[{stage:'GPT Rough',coordinate_frame:'gpt_start_relative_visualization_mm',units:'mm',runs:[[[0,0,0],[1,1,1],[2,1,3]]]},{stage:'GPT Corners',coordinate_frame:'gpt_start_relative_visualization_mm',units:'mm',runs:[]}]}}));
  await page.route('**/api/weld/*/model-outputs',route=>{
    const job=route.request().url().split('/').at(-2)!;
    return route.fulfill({json:{job_id:job,outputs:generated?[{id:artifact,stage:'final',label:'GPT Rough',stale:false,current_overlay_allowed:true,
      states:{OUTPUT_EXISTS:true,OUTPUT_RENDERABLE:true,OUTPUT_VALIDATED:false,OUTPUT_APPROVED:false,SIMULATION_DISPLAYABLE:true,ROBOT_PLAYBACK_READY:false},
      display_url:`/api/weld/${job}/final-trajectory/${artifact}/display`}]:[]}});
  });
  await page.route('**/api/simulator/path-preview',async route=>{geometryCalls++;expect(route.request().postDataJSON()).toHaveProperty('job_id');const r=await page.request.get('/api/simulator/status');await route.fulfill({json:{...await r.json(),path_view:{viewer_mode:'RELATIVE_FRAME'}}});});
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await page.getByTestId('native-segment').click();await page.getByTestId('confirm-mask').click();
  await page.getByText('수동 지시 / 디버그',{exact:true}).click();await page.getByRole('button',{name:'지시 분석',exact:true}).click();
  await page.getByRole('tab',{name:'경로 계획',exact:true}).click();await page.getByRole('button',{name:'용접 경로 생성',exact:true}).click();await page.getByTestId('run-guided-vla').click();
  await expect(page.getByTestId('final-raw-output')).toContainText('RELATIVE VISUALIZATION');
  await expect(page.getByTestId('final-raw-output').locator('polyline')).toHaveCount(1);
  await page.getByLabel('GPT output stage').selectOption('GPT Corners');await expect(page.getByTestId('final-raw-output')).toContainText('렌더링 가능한 XYZ 결과 없음');
  await page.getByLabel('GPT output stage').selectOption('GPT Rough');await expect(page.getByTestId('final-raw-output').locator('polyline')).toHaveCount(1);
  await page.getByTestId('output-browser').locator('summary').click();await page.getByLabel('Model output source').selectOption(`final:${artifact}`);
  await expect(page.getByTestId('output-browser')).toContainText('SIMULATION_DISPLAYABLE');await expect(page.getByRole('img',{name:'Model raw geometry viewer'})).toBeVisible();
  await page.getByRole('tab',{name:'시뮬레이션',exact:true}).click();await expect(page.getByTestId('current-vla-path-preview')).toBeEnabled();await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  await expect(page.getByTestId('current-vla-gate')).toContainText('geometry available');
  await expect(page.getByTestId('current-vla-gate')).toContainText('원본 3 XYZ 보존');
  await page.getByTestId('current-vla-path-preview').click();await expect.poll(()=>geometryCalls).toBe(1);
  await expect(page.getByTestId('path-viewer-mode')).toContainText('RELATIVE_FRAME');
});
