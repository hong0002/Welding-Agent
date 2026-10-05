import {expect,test,type Page,type APIRequestContext} from '@playwright/test';
import {createHash,randomUUID} from 'node:crypto';
import {deflateSync} from 'node:zlib';

// Deterministic display fixture, never a real Isaac capture.
function fixturePNG(){
  const w=400,h=300,rows=Buffer.alloc(h*(w*3+1));
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const i=y*(w*3+1)+1+x*3;
    const plate=x>65&&x<335&&y>80&&y<235;
    const line=x>100&&x<300&&Math.abs(y-(195-(x-100)*.4))<3;
    rows[i]=line?255:plate?135:28;rows[i+1]=line?4:plate?145:42;rows[i+2]=line?7:plate?140:46;
  }
  const chunk=(name:string,data:Buffer)=>{
    const block=Buffer.concat([Buffer.from(name),data]);let crc=0xffffffff;
    for(const b of block){crc^=b;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}
    const result=Buffer.alloc(data.length+12);result.writeUInt32BE(data.length);block.copy(result,4);result.writeUInt32BE((crc^0xffffffff)>>>0,result.length-4);return result;
  };
  const header=Buffer.alloc(13);header.writeUInt32BE(w);header.writeUInt32BE(h,4);header[8]=8;header[9]=2;
  return Buffer.concat([Buffer.from('89504e470d0a1a0a','hex'),chunk('IHDR',header),chunk('IDAT',deflateSync(rows)),chunk('IEND',Buffer.alloc(0))]);
}
const png=fixturePNG(),digest=createHash('sha256').update(png).digest('hex');

async function setup(page:Page,request:APIRequestContext,kind:'path'|'robot',backend='dataset_stp'){
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  const base=await(await request.get('/api/simulator/status')).json();
  const session=randomUUID(),requestId=randomUUID();
  const status={...base,backend,can_stop:true,current_preview:{...base.current_preview,backend,
    configured:true,state:'READY',can_stop:true,configuration_codes:[],configuration_errors:[],
    latest:{backend,job_id:job.id,artifact_id:job.vla_prediction.artifact_id,package_id:randomUUID(),sample_id:job.scene.sample_id,
      request_id:requestId,session_id:session,point_count:9,source_point_count:9,playback_point_count:17,
      status:'SUCCEEDED',kind,robot_motion:kind==='robot',error:null,playback_status:'SUCCEEDED',capture_status:'SUCCEEDED'}}};
  const gallery={job_id:job.id,artifact_id:job.vla_prediction.artifact_id,session_id:session,request_id:requestId,
    kind,available:true,delivery:'latest_capture',reason_code:null as string|null,frames:(backend==='dataset_final'?['start','middle','end']:['P0','P4','P8','path_detail']).map(name=>({name,sha256:digest,width:400,height:300,
      captured_at:'2026-10-02T05:00:00Z',url:`/api/simulator/current-preview/frames/${session}/${requestId}/${name}/${digest}.png?job_id=${job.id}&artifact_id=${job.vla_prediction.artifact_id}`}))};
  const support={backend,sample_id:job.scene.sample_id,path_preview_ready:backend!=='dataset_final',robot_preview_ready:true,
    workpiece_preview_ready:true,source_point_count:9,playback_point_count:17,configuration_codes:[],warnings:[],orientation_source:'simulator_stp_policy'};
  const posts:string[]=[];
  page.on('request',r=>{if(r.method()==='POST'&&!r.url().includes('/api/agent/sessions'))posts.push(r.url());});
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route('**/api/simulator/status',r=>r.fulfill({json:status}));
  await page.route('**/api/simulator/current-vla/capabilities?*',r=>r.fulfill({json:support}));
  await page.route(`**/api/weld/${job.id}/model-outputs`,r=>r.fulfill({json:{job_id:job.id,outputs:[{
    id:job.vla_prediction.artifact_id,stage:'prediction',label:'Guided VLA',stale:false,
    sample_id:job.scene.sample_id,dimensions:3,coordinate_frame:'source_robot_frame_unaligned_with_isaac',units:'m',
    states:{OUTPUT_RENDERABLE:true,OUTPUT_VALIDATED:true},runs:[[[0,0,0],[.01,0,0],[.02,0,0]]]
  }]}}));
  await page.route('**/api/simulator/current-preview/frames?*',r=>r.fulfill({json:gallery}));
  await page.route('**/api/simulator/current-preview/frames/**/*.png?*',r=>r.fulfill({contentType:'image/png',body:png}));
  await page.route('**/api/simulator/stop',r=>{
    expect(r.request().postDataJSON()).toEqual({});status.can_stop=false;status.current_preview.state='STOPPED';status.current_preview.can_stop=false;
    return r.fulfill({json:status});
  });
  await page.goto('/');await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');
  await page.locator('#tab-simulator').click();
  return {status,gallery,posts,before,job};
}

test('native final start, middle and end captures share the owned viewer and clear on stop',async({page,request})=>{
  const fixture=await setup(page,request,'robot','dataset_final');
  const viewer=page.getByTestId('simulator-viewport');
  await expect.poll(()=>viewer.locator('img').evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBe(400);
  await viewer.getByRole('button',{name:'중간',exact:true}).click();
  await expect(viewer.locator('img')).toHaveAttribute('src',/\/middle\//);
  await viewer.getByRole('button',{name:'완료',exact:true}).click();
  await expect(viewer.locator('img')).toHaveAttribute('src',/\/end\//);
  await expect(page.getByTestId('current-preview-diagnostics')).toContainText('Playback: SUCCEEDED');
  await page.getByTestId('current-preview-stop').click();
  await expect(viewer.locator('img')).toHaveCount(0);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(fixture.before);
});

for(const kind of ['path','robot'] as const)test(`${kind} current owned capture is embedded, expandable and cleared on stop`,async({page,request})=>{
  const fixture=await setup(page,request,kind);
  const viewer=page.getByTestId('simulator-viewport');
  await expect(viewer).toContainText(kind==='path'?'Path Preview':'STRICT ROBOT PREVIEW');
  await expect(viewer).toContainText('실시간 영상 아님');
  await expect.poll(()=>viewer.locator('img').evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBe(400);
  await viewer.getByRole('button',{name:'P4',exact:true}).click();
  await expect(viewer.locator('img')).toHaveAttribute('src',/\/P4\//);
  await viewer.getByRole('button',{name:'시뮬레이터 캡처 크게 보기'}).click();
  await expect(page.getByRole('dialog',{name:'시뮬레이터 캡처 확대'})).toBeVisible();
  await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);
  if(kind==='path')await expect(page.getByTestId('current-vla-preview')).toHaveClass(/primary/);
  else await expect(page.getByTestId('current-preview-stop')).toHaveClass(/primary/);
  await page.getByRole('navigation',{name:'Workflow progress'}).getByRole('button',{name:'Simulator',exact:true}).click();
  await page.screenshot({path:`test-results/preview-ux-${kind}.png`,fullPage:true,animations:'disabled'});
  await page.getByRole('button',{name:'시뮬레이터 화면으로 이동',exact:true}).click();
  await expect(viewer).toBeInViewport();
  await page.screenshot({path:`test-results/preview-ux-${kind}-capture.png`,fullPage:true,animations:'disabled'});
  await page.getByTestId('current-preview-stop').click();
  await expect(viewer.locator('img')).toHaveCount(0);
  await expect(viewer).toContainText('시작하면 현재 작업의 화면이 표시');
  expect(fixture.posts).toHaveLength(1);expect(fixture.posts[0]).toMatch(/\/simulator\/stop$/);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(fixture.before);
});

test('new request, another job and failed capture never leave an old image',async({page,request})=>{
  const fixture=await setup(page,request,'path');const viewer=page.getByTestId('simulator-viewport');
  await expect(viewer.locator('img')).toBeVisible();
  fixture.status.current_preview.latest.request_id=randomUUID();
  await expect(viewer.locator('img')).toHaveCount(0); // stale gallery response is ignored
  fixture.status.current_preview.latest.request_id=fixture.gallery.request_id;
  await expect(viewer.locator('img')).toBeVisible();
  fixture.status.current_preview.latest.job_id=randomUUID();
  await expect(viewer.locator('img')).toHaveCount(0);
  fixture.status.current_preview.latest.job_id=fixture.job.id;
  await expect(viewer.locator('img')).toBeVisible();
  await page.route('**/api/simulator/current-preview/frames?*',r=>r.fulfill({status:409,json:{code:'CURRENT_PREVIEW_ARTIFACT_INVALID',detail:'Current approval changed'}}));
  await expect(viewer.locator('img')).toHaveCount(0);
  expect(fixture.posts).toEqual([]);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(fixture.before);
});

test('capture unavailable preserves successful playback and rejects arbitrary frame URLs',async({page,request})=>{
  const fixture=await setup(page,request,'robot');const viewer=page.getByTestId('simulator-viewport');
  await expect(viewer.locator('img')).toBeVisible();
  fixture.gallery.frames=[];fixture.gallery.available=false;fixture.gallery.reason_code='CURRENT_PREVIEW_FRAME_UNAVAILABLE';
  await expect(viewer.locator('img')).toHaveCount(0);
  await expect(viewer).toContainText('캡처 화면을 읽을 수 없습니다');
  await expect(page.getByTestId('current-preview-diagnostics')).toContainText('Playback: SUCCEEDED');
  let leaked=false;
  await page.route('https://example.invalid/**',r=>{leaked=true;return r.abort();});
  const frame={name:'path_detail',sha256:digest,width:400,height:300,captured_at:'2026-10-02T05:00:00Z',url:'https://example.invalid/private.png'};
  fixture.gallery.frames=[frame];fixture.gallery.available=true;
  await expect(viewer.locator('img')).toHaveCount(0);
  // Wait for a completed next poll, not an arbitrary sleep.
  await page.waitForResponse(r=>r.url().includes('/current-preview/frames?'));
  expect(leaked).toBe(false);expect(fixture.posts).toEqual([]);
});
