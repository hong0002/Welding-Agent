import {test,expect,type Page,type APIRequestContext} from '@playwright/test';
import {preferredCurrentOutput,sourcePointCount} from '../src/simulatorSelection';
import type {OutputRow} from '../src/components/OutputBrowser';

const points=Array.from({length:9},(_,i)=>[i,i*.5,i*.2]);
const absolute='source_robot_frame_unaligned_with_isaac';
const relative='gpt_start_relative_visualization_mm';
const artifact='65822d00-a386-403e-b003-de0abfcb520e';
const states={OUTPUT_RENDERABLE:true,OUTPUT_VALIDATED:false,OUTPUT_APPROVED:false,ROBOT_PLAYBACK_READY:false};
const output=(sample:string,label:string,stage='gpt_stage',stage_index=0,coordinate_frame=relative):OutputRow=>({
  id:artifact,stage,stage_index:stage==='gpt_stage'?stage_index:undefined,label,stale:false,sample_id:sample,
  dimensions:3,coordinate_frame,units:'mm',runs:[points],states});

async function setup(page:Page,request:APIRequestContext,rows:(sample:string,jobId:string)=>OutputRow[]){
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  job.state='MASK_READY';job.mask.approved=false;job.mask.approved_at=null;job.vla_prediction=null;
  const base=await(await request.get('/api/simulator/status')).json();
  const status={...base,backend:'dataset_stp',current_preview:{...base.current_preview,
    backend:'dataset_final',simulator_version:'dataset_final',configured:true,source_point_count:null,
    robot_configuration:{configured:true,configuration_errors:[],configuration_codes:[]},state:'STOPPED',latest:null}};
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route(`**/api/weld/${job.id}`,r=>r.fulfill({json:job}));
  await page.route('**/api/simulator/status',r=>r.fulfill({json:status}));
  await page.route('**/api/weld/*/model-outputs',r=>r.fulfill({json:{job_id:job.id,outputs:rows(job.scene.sample_id,job.id)}}));
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('MASK_READY');
  await page.locator('#tab-simulator').click();
  return {job,before,status};
}

test('STOPPED final config + unapproved absolute GPT 9 points enables STRICT without cached readiness',async({page,request})=>{
  const {job,before,status}=await setup(page,request,sample=>[output(sample,'GPT Final','gpt_stage',2,absolute)]);
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  await expect(page.getByTestId('simulator-backend')).toHaveText('Simulator Backend: simulator_final');
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Source Points: 9');
  await expect(page.getByTestId('robot-preview-mode')).toContainText('STRICT');
  await expect(page.getByTestId('robot-preview-unavailable')).toHaveCount(0);
  await page.getByTestId('current-vla-preview').scrollIntoViewIfNeeded();
  await page.screenshot({path:'test-results/robot-preview-binding-enabled.png',fullPage:true,animations:'disabled'});
  let calls=0;
  await page.route('**/api/simulator/robot-preview',r=>{
    calls++;expect(r.request().postDataJSON()).toEqual({job_id:job.id,artifact_id:artifact,output_kind:'gpt_stage',stage_index:2});
    return r.fulfill({status:202,json:{...status,robot_view:{mode:'STRICT'}}});
  });
  await page.getByTestId('current-vla-preview').click();await expect.poll(()=>calls).toBe(1);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});

test('empty Final auto-selects latest current Corners; relative/raw selection sends exact DEMO source',async({page,request})=>{
  let candidates:OutputRow[]=[];
  const {job,before,status}=await setup(page,request,sample=>{
    candidates=[{...output(sample,'GPT Final','final'),runs:[]},output(sample,'GPT Corners','gpt_stage',0),
      output(sample,'GPT Corners','gpt_stage',1),output(sample,'GPT Raw Partial','gpt_stage',3),output(sample,'Guided VLA','prediction'),
      {...output(sample,'Foreign GPT Final','gpt_stage',4),job_id:'other-job'},
      {...output(sample,'Stale GPT Final','gpt_stage',5),stale:true}];return candidates;
  });
  const bound=candidates.map(r=>({...r,job_id:r.job_id??job.id}));
  expect(preferredCurrentOutput(bound,job.id,job.scene.sample_id)?.stage_index).toBe(1);
  await expect(page.getByLabel('Simulator result source')).toHaveValue(`gpt_stage:${artifact}:1`);
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  await expect(page.getByTestId('robot-preview-mode')).toContainText('DEMO');
  // Malformed points do not inflate the selected source count.
  expect(sourcePointCount({...candidates[3],runs:[[...points,[NaN,0,0],[1,2]]]})).toBe(9);
  await page.getByLabel('Simulator result source').selectOption(`gpt_stage:${artifact}:3`);
  let calls=0;
  await page.route('**/api/simulator/robot-preview',r=>{
    calls++;expect(r.request().postDataJSON()).toEqual({job_id:job.id,artifact_id:artifact,output_kind:'gpt_stage',stage_index:3});
    return r.fulfill({status:202,json:{...status,robot_view:{mode:'DEMO',robot_demo_only:true,physical_execution:false}}});
  });
  await page.getByTestId('current-vla-preview').click();await expect.poll(()=>calls).toBe(1);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});

test('geometry fetched from bound display URL is auto-selected before Robot activation',async({page,request})=>{
  await page.route('**/api/weld/*/final-trajectory/*/display',r=>r.fulfill({json:{artifact_id:artifact,runs:[points]}}));
  await setup(page,request,(sample,jobId)=>[{...output(sample,'GPT Final','final',0,absolute),runs:[],
    display_url:`/api/weld/${jobId}/final-trajectory/${artifact}/display`}]);
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Source Points: 9');
});

test('no current XYZ: stale/foreign outputs are not auto-selected and the reason is geometry, not assets',async({page,request})=>{
  const {job}=await setup(page,request,sample=>[
    {...output(sample,'Old GPT Final','final'),stale:true},
    {...output('B_PR_03_9999','Foreign Sample','gpt_stage',1)},
    {...output(sample,'Foreign Job','gpt_stage',2),job_id:'other-job'}]);
  await expect(page.getByLabel('Simulator result source')).toHaveValue('');
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  await expect(page.getByTestId('robot-preview-unavailable')).toHaveText('3D 예측 결과를 선택하세요.');
  await expect(page.getByTestId('simulator-output-browser')).not.toContainText('launcher/assets');
  await page.getByLabel('Simulator result source').selectOption(`gpt_stage:${artifact}:2`);
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  expect(preferredCurrentOutput([{...output(job.scene.sample_id,'GPT Final','final'),job_id:job.id}],job.id,job.scene.sample_id)?.id).toBe(artifact);
});
