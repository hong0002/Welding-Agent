import {expect,test} from '@playwright/test';
import {randomUUID} from 'node:crypto';

test('explicit descriptor refresh uses current job and clears readiness without model dispatch',async({page,request})=>{
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  const base=await(await request.get('/api/simulator/status')).json();
  const status:any={...base,can_stop:false,backend:'dataset_stp',current_preview:{...base.current_preview,
    configured:true,can_stop:false,state:'FAILED',error:'C:\\private token=secret123',latest:{
      job_id:job.id,artifact_id:job.vla_prediction.artifact_id,package_id:randomUUID(),sample_id:job.scene.sample_id,
      session_id:randomUUID(),request_id:randomUUID(),kind:'robot',point_count:9,status:'FAILED',
      reason_code:'OWNED_CODE_FINGERPRINT_MISSING',robot_motion:false,error:null}}};
  let refreshed=false;
  const posts:string[]=[];
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route('**/api/simulator/status',r=>r.fulfill({json:status}));
  await page.route('**/api/simulator/current-vla/capabilities?*',r=>r.fulfill({json:{backend:'dataset_stp',sample_id:job.scene.sample_id,
    path_preview_ready:true,robot_preview_ready:refreshed,robot_preflight_available:true,configuration_codes:[],warnings:[]}}));
  await page.route('**/api/simulator/current-vla/preview-descriptor-refresh',r=>{
    expect(r.request().method()).toBe('POST');expect(r.request().postDataJSON()).toEqual({job_id:job.id});
    refreshed=true;status.current_preview.state='STOPPED';status.current_preview.error=null;status.current_preview.latest=null;
    return r.fulfill({json:{status:'PREVIEW_DESCRIPTOR_REFRESHED',native_recomputed:false,isaac_launched:false}});
  });
  page.on('request',r=>{if(r.method()==='POST'&&!r.url().endsWith('/agent/sessions'))posts.push(r.url());});
  await page.goto('/');await page.getByRole('tab',{name:'시뮬레이션',exact:true}).click();
  const panel=page.locator('.simulator-panel');
  await expect(panel.getByRole('alert')).toContainText('descriptor를 갱신');
  await expect(panel).not.toContainText('secret123');await expect(panel).not.toContainText('C:\\private');
  await expect(page.getByTestId('current-vla-preview')).toBeDisabled();
  await page.getByText('Preview descriptor 관리',{exact:true}).click();
  await page.getByTestId('preview-descriptor-refresh').click();
  await expect(page.getByTestId('current-vla-preview')).toBeEnabled();
  await expect(panel.getByRole('alert')).toHaveCount(0);
  expect(posts).toHaveLength(1);expect(posts[0]).toContain('/api/simulator/current-vla/preview-descriptor-refresh');
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
});
