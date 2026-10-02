import {expect,test,type Page} from '@playwright/test';

async function prepare(page:Page){
  await page.goto('/');
  await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await page.getByTestId('native-segment').click();
  await expect(page.getByTestId('yolo-active-count')).toHaveText('1');
}

async function boxes(page:Page){
  return page.getByTestId('drawing-surface').evaluate(()=>{
    const stage=(window as any).Konva.stages.find((s:any)=>s.container().closest('[data-testid="drawing-surface"]'));
    return stage.find('.yolo-bbox').map((n:any)=>({x:n.x(),y:n.y(),w:n.width(),h:n.height(),stroke:n.stroke(),
      screen:n.getClientRect({skipStroke:true}),scale:stage.scaleX(),listening:n.getLayer().listening()}));
  });
}

test('YOLO toggle, per-view boxes/labels, fit resize, thumbnail and Inspector match source pixels',async({page})=>{
  await prepare(page);
  const toggle=page.getByLabel('YOLO Objects',{exact:true});
  await expect(toggle).toBeChecked();
  await expect(page.getByTestId('yolo-count-F')).toHaveText('YOLO 1');
  await expect(page.getByTestId('yolo-count-R')).toHaveText('YOLO 2');
  await expect(page.getByTestId('yolo-summary')).toContainText('Class 0 0.93');
  await expect.poll(()=>boxes(page)).toMatchObject([{x:12,y:15,w:28,h:30,stroke:'#58baff',listening:false}]);
  await toggle.uncheck();
  await expect.poll(()=>boxes(page)).toEqual([]);
  await toggle.check();
  await expect.poll(()=>boxes(page)).toHaveLength(1);
  await page.getByTestId('view-R').click();
  await expect(page.getByTestId('yolo-active-count')).toHaveText('2');
  await expect.poll(()=>boxes(page)).toMatchObject([{x:52,y:22,w:32,h:38},{x:4,y:4,w:12,h:10}]);
  await expect(page.getByTestId('yolo-summary')).toContainText('View R · 2');
  await page.getByTestId('view-S1').click();
  await expect.poll(()=>boxes(page)).toEqual([]);
  await expect(page.getByTestId('yolo-active-count')).toHaveText('0');
  await page.getByTestId('view-F').click();
  const before=(await boxes(page))[0];
  await page.setViewportSize({width:1050,height:900});
  await expect.poll(async()=>(await boxes(page))[0]?.scale).not.toBe(before.scale);
  const b=(await boxes(page))[0];
  expect(b.x).toBe(12);expect(b.y).toBe(15);
  expect(b.screen.x).toBeCloseTo(12*b.scale);expect(b.screen.y).toBeCloseTo(15*b.scale);
  expect(b.screen.width).toBeCloseTo(28*b.scale);
  await expect.poll(()=>page.getByTestId('drawing-surface').evaluate(el=>{
    const c=el.querySelectorAll('canvas')[1];
    return c&&Array.from(c.getContext('2d')!.getImageData(0,0,c.width,c.height).data).some((v,i)=>i%4===3&&v>0);
  })).toBeTruthy();
  await page.getByLabel('VLM Weld Mask',{exact:true}).uncheck();
  await expect.poll(()=>boxes(page)).toHaveLength(1);
  await page.getByLabel('VLM Weld Mask',{exact:true}).check();
});

test('2D guidance and manual edits retain display-only YOLO; redetection refreshes and new scene clears',async({page,request})=>{
  await prepare(page);
  await page.getByTestId('confirm-mask').click();
  await page.getByText('수동 지시 / 디버그',{exact:true}).click();
  await page.getByRole('button',{name:'지시 분석',exact:true}).click();
  await page.getByRole('tab',{name:'경로 계획',exact:true}).click();
  await page.getByRole('button',{name:'용접 경로 생성',exact:true}).click();
  await expect(page.getByTestId('workflow-state')).toHaveText('ROUGH_PATH_READY');
  await expect.poll(()=>boxes(page)).toHaveLength(1);
  await expect.poll(()=>page.getByTestId('drawing-surface').evaluate(()=>{
    const s=(window as any).Konva.stages.find((s:any)=>s.container().closest('[data-testid="drawing-surface"]'));
    return s.find('Line').some((n:any)=>n.stroke()==='#ffc866');
  })).toBeTruthy();
  const mutations:string[]=[];
  page.on('request',r=>{if(r.method()==='POST')mutations.push(new URL(r.url()).pathname);});
  await page.getByLabel('YOLO Objects',{exact:true}).uncheck();
  await page.getByLabel('YOLO Objects',{exact:true}).check();
  expect(mutations).toEqual([]);
  // A brush edit changes only local mask provenance, never re-infers YOLO.
  const surface=(await page.getByTestId('drawing-surface').boundingBox())!;
  await page.mouse.click(surface.x+surface.width*.2,surface.y+surface.height*.2);
  await expect(page.getByTestId('mask-source')).toHaveText('Manual edited');
  await expect(page.getByTestId('yolo-summary')).toContainText('Mask source: manual_edited');
  await expect.poll(()=>boxes(page)).toHaveLength(1);
  let release!:()=>void;
  const gate=new Promise<void>(r=>{release=r;});
  await page.route('**/api/masks/automatic',async route=>{await gate;await route.continue();});
  await page.getByTestId('native-segment').click();
  await expect.poll(()=>boxes(page)).toEqual([]);
  release();
  await expect(page.getByTestId('yolo-active-count')).toHaveText('1');
  await expect.poll(()=>boxes(page)).toHaveLength(1);
  const jobLoaded=page.waitForResponse('**/api/scenes/sample');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await jobLoaded;
  await expect.poll(()=>boxes(page)).toEqual([]);
  await expect(page.getByTestId('yolo-count-F')).toHaveCount(0);
  await expect(page.getByTestId('yolo-summary')).toContainText('YOLO 결과 없음');
  const calls=await(await request.get('/api/test/native-call-counts')).json();
  expect(calls.segment).toBeGreaterThanOrEqual(2);
  expect(mutations.filter(p=>/guided-vla|simulator\//.test(p))).toEqual([]);
});

test('existing approved mask reuse keeps YOLO; loading a different sample hides the old layer',async({page})=>{
  await prepare(page);
  await page.getByTestId('confirm-mask').click();
  const composer=page.getByLabel('Assistant 메시지',{exact:true});
  const before=await page.locator('.agent-message.assistant').count();
  await composer.fill('마스크 씌워줘');await composer.press('Enter');
  await expect(page.locator('.agent-message.assistant')).toHaveCount(before+1);
  await expect(composer).toBeEnabled();
  await expect.poll(()=>boxes(page)).toHaveLength(1);
  await page.route('**/api/scenes/sample',async route=>{
    const response=await route.fetch({postData:JSON.stringify({sample_id:'SAMPLE_1'})});const job=await response.json();
    job.scene.sample_id='OTHER_SAMPLE';
    await route.fulfill({json:job});
  });
  await page.getByLabel('Dataset sample ID').fill('OTHER_SAMPLE');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await expect(page.getByLabel('Dataset sample ID')).toHaveValue('OTHER_SAMPLE');
  await expect.poll(()=>boxes(page)).toEqual([]);
  await expect(page.getByTestId('yolo-count-F')).toHaveCount(0);
});

test('malformed or missing display output is nonfatal; a late old-session response stays hidden',async({page})=>{
  await page.route('**/api/weld/*/yolo',route=>route.fulfill({json:{bad:'PRIVATE_PATH SECRET'}}));
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await page.getByTestId('native-segment').click();
  await expect(page.getByTestId('yolo-summary')).toContainText('YOLO_ARTIFACT_MALFORMED');
  await expect.poll(()=>boxes(page)).toEqual([]);
  await page.getByTestId('confirm-mask').click();
  await expect(page.getByTestId('mask-status')).toHaveText('확정됨');
  await expect(page.locator('body')).not.toContainText('PRIVATE_PATH');
  await page.unroute('**/api/weld/*/yolo');
  let release!:()=>void;
  const gate=new Promise<void>(r=>{release=r;});
  await page.route('**/api/weld/*/yolo',async route=>{
    const r=await route.fetch();await gate;await route.fulfill({response:r});
  });
  await page.getByTestId('native-segment').click();
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  release();
  await expect.poll(()=>boxes(page)).toEqual([]);
  await expect(page.getByTestId('yolo-active-count')).toHaveText('0');
});

test('existing B_PR real artifact replay renders all nine bound views without inference',async({page,request})=>{
  const replay=await(await request.get('/api/test/yolo-replay')).json();
  test.skip(!replay.available,'Explicit local stored Segment2 artifact absent');
  const callsBefore=await(await request.get('/api/test/native-call-counts')).json();
  await page.route('**/api/agent/sessions/*/history',route=>route.fulfill({json:{
    session_id:new URL(route.request().url()).pathname.split('/').at(-2),active_job_id:replay.job_id,messages:[],running:false}}));
  await page.goto('/');
  await expect(page.getByTestId('yolo-active-count')).toHaveText('1');
  const response=await request.get(`/api/weld/${replay.job_id}/yolo`);
  const overlay=await response.json();
  expect(response.status()).toBe(200);expect(overlay.available).toBe(true);
  expect(overlay.sample_id).toBe('B_PR_03_0001');
  for(const view of ['B','F','L','R','S1','S2','S3','S4','T']){
    await page.getByTestId(`view-${view}`).click();
    const d=overlay.views[view].detections[0].bbox;
    await expect.poll(()=>boxes(page)).toMatchObject([{x:d.x_min,y:d.y_min,w:d.x_max-d.x_min,h:d.y_max-d.y_min}]);
    await expect(page.getByTestId(`yolo-count-${view}`)).toHaveText('YOLO 1');
  }
  await page.getByTestId('view-F').click();
  await page.screenshot({path:'test-results/yolo-real-artifact.png',fullPage:true});
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(callsBefore);
});
