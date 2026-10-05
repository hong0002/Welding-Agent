import {test,expect} from '@playwright/test';

test('new GPT default wins; stage selection bound; saved playback cannot launch',async({page,request})=>{
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  const id='65822d00-a386-403e-b003-de0abfcb520e';
  const base={dimensions:3,sample_id:job.scene.sample_id,stale:false,units:'mm',
    coordinate_frame:'source_robot_frame_unaligned_with_isaac',runs:[[[10,20,30],[11,21,31]]],states:{OUTPUT_RENDERABLE:true}};
  const rows=[{...base,id,stage:'final',label:'GPT Final'},
    {...base,id,stage:'gpt_stage',stage_index:0,label:'GPT Rough'},
    {...base,id:job.vla_prediction.artifact_id,stage:'prediction',label:'Guided VLA'},
    {...base,id:'93d6d30c-0e70-4693-bcc9-c796664ca955',stage:'playback',label:'Saved playback',stale:true}];
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route('**/api/weld/*/model-outputs',r=>r.fulfill({json:{job_id:job.id,outputs:rows}}));
  const status=await(await request.get('/api/simulator/status')).json();
  await page.route('**/api/simulator/status',r=>r.fulfill({json:status}));
  let calls=0;
  await page.route('**/api/simulator/robot-preview',async r=>{
    calls++;expect(r.request().postDataJSON()).toEqual({job_id:job.id,artifact_id:id,output_kind:'gpt_stage',stage_index:0});
    await r.fulfill({status:202,json:{...status,robot_view:{mode:'STRICT'}}});
  });
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');
  await page.locator('#tab-simulator').click();
  await expect(page.getByLabel('Simulator result source')).toHaveValue('final:'+id);
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Prediction Source: GPT Final');
  await page.getByLabel('Simulator result source').selectOption('gpt_stage:'+id+':0');
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Prediction Source: GPT Rough');
  await page.getByTestId('current-vla-preview').click();await expect.poll(()=>calls).toBe(1);
  await page.getByLabel('Simulator result source').selectOption('playback:93d6d30c-0e70-4693-bcc9-c796664ca955');
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  await expect(page.getByRole('img',{name:'Model raw geometry viewer'})).toBeVisible();
});
