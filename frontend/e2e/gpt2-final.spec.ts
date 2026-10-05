import {test,expect,type Page,type APIRequestContext} from '@playwright/test';
import type {OutputRow} from '../src/components/OutputBrowser';
import {preferredCurrentOutput} from '../src/simulatorSelection';

const artifact='67f1eecd-8b82-420d-84b0-409f4795614e';
const legacy='6421fe04-8959-4b2e-87fb-48f1ad1a992a';
const xyz=Array.from({length:33},(_,i)=>[10+i/10,20+i/20,30+i/100]);
const absolute='source_robot_frame_unaligned_with_isaac';
const row=(sample:string,source:string,label:string,stage='final',frame=absolute):OutputRow=>({
  id:source==='vlm_final_gpt2'?artifact:legacy,source,label,stage,stage_index:stage==='gpt_stage'?1:undefined,
  dimensions:3,stale:false,sample_id:sample,units:'mm',coordinate_frame:frame,runs:[xyz],
  states:{OUTPUT_EXISTS:true,OUTPUT_RENDERABLE:true,OUTPUT_VALIDATED:stage==='final',CURRENT_RESULT:true}});

async function setup(page:Page,request:APIRequestContext,outputs:(sample:string)=>OutputRow[]){
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  job.state='MASK_READY';job.mask.approved=false;job.mask.approved_at=null;job.vla_prediction=null;
  const status=await(await request.get('/api/simulator/status')).json();
  status.current_preview={...status.current_preview,backend:'dataset_final',simulator_version:'dataset_final',configured:true,
    state:'STOPPED',source_point_count:null,latest:null,robot_configuration:{configured:true,configuration_errors:[],configuration_codes:[]}};
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route(`**/api/weld/${job.id}`,r=>r.fulfill({json:job}));
  await page.route('**/api/simulator/status',r=>r.fulfill({json:status}));
  await page.route('**/api/weld/*/model-outputs',r=>r.fulfill({json:{job_id:job.id,outputs:outputs(job.scene.sample_id)}}));
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('MASK_READY');
  await page.locator('#tab-simulator').click();
  return {job,status,before};
}

test('native GPT2 Final wins over raw/legacy, shows correct source, exact STRICT selection',async({page,request})=>{
  const {job,status,before}=await setup(page,request,sample=>[
    row(sample,'vlm_final_gpt2','GPT · Final'),row(sample,'vlm_final_gpt2','GPT2 · Corners','gpt_stage','source_robot_start_relative_mm'),
    row(sample,'vlm_final_gpt','GPT Raw Partial Corners','gpt_stage'),
    {...row(sample,'vlm_final_gpt','Old GPT Final'),stale:true},
    {...row('OTHER_SAMPLE','vlm_final_gpt2','Foreign Final'),id:'another-artifact'}]);
  await expect(page.getByLabel('Simulator result source')).toHaveValue(`final:${artifact}`);
  await expect(page.getByTestId('simulator-output-browser').getByTestId('selected-model-source')).toHaveText('Source: vlm_final_gpt2');
  await expect(page.getByTestId('robot-preview-mode')).toHaveText('STRICT ROBOT PREVIEW');
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Predictor: vlm_final_gpt2');
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Source Points: 33');
  await expect(page.getByTestId('prediction-source-identity')).toContainText('Playback: MODEL PREDICTION');
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  await page.screenshot({path:'test-results/gpt2-final-strict-offline.png',fullPage:true,animations:'disabled'});
  let calls=0;
  await page.route('**/api/simulator/robot-preview',r=>{
    calls++;expect(r.request().postDataJSON()).toEqual({job_id:job.id,artifact_id:artifact,output_kind:'final'});
    return r.fulfill({json:{...status,robot_view:{mode:'STRICT'}}});
  });
  await page.getByTestId('current-vla-preview').click();await expect.poll(()=>calls).toBe(1);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});

test('current native GPT2 intermediate outranks legacy; raw remains relative DEMO',async({page,request})=>{
  const {job,before}=await setup(page,request,sample=>[
    row(sample,'vlm_final_gpt','Legacy GPT Final'),
    row(sample,'vlm_final_gpt2','GPT2 · Corners','gpt_stage','source_robot_start_relative_mm')]);
  await expect(page.getByLabel('Simulator result source')).toHaveValue(`gpt_stage:${artifact}:1`);
  await expect(page.getByTestId('robot-preview-mode')).toContainText('DEMO');
  await expect(page.getByTestId('simulator-output-browser').getByTestId('selected-model-source')).toHaveText('Source: vlm_final_gpt2');
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  const rows=[{...row(job.scene.sample_id,'vlm_final_gpt2','GPT · Final'),job_id:job.id,stale:true},
    {...row(job.scene.sample_id,'vlm_final_gpt','Legacy GPT Final'),job_id:job.id}];
  expect(preferredCurrentOutput(rows,job.id,job.scene.sample_id)?.source).toBe('vlm_final_gpt');
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});

test('prediction-only Final with null metrics renders without fabricated evaluation',async({page,request})=>{
  const {job,before}=await setup(page,request,sample=>[row(sample,'vlm_final_gpt2','GPT · Final')]);
  job.vla_prediction={artifact_id:artifact,attempt_id:artifact,sample_id:job.scene.sample_id,split:job.scene.split,
    source:'vlm_final_gpt2',provider:'gpt',model:'gpt-6-luna',point_count:33,coordinate_frame:absolute,
    ade_mm:null,fde_mm:null,mask_views:['F','R','S4'],simulation_only:true,physical_robot_executable:false,simulator_ready:false};
  job.rough_mode='native_3d';
  await page.reload();
  await page.locator('#tab-path').click();
  await expect(page.getByTestId('vla-summary')).toContainText('Source: vlm_final_gpt2');
  await expect(page.getByTestId('prediction-only-evaluation')).toHaveText('Prediction only · GT 평가 미실행');
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});
