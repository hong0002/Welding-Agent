import {test,expect} from '@playwright/test';

const saved='764d2732-16ba-40f7-aa09-fd34f78fc351';
const fresh='012b9462-529a-4d5c-99ab-382b4d8c0247';
const key='welding-agent-conversation';
const ready={enabled:true,api_key_configured:true,sdk_available:true,model:'offline',state:'READY'};

test('READY first, POST empty session then GET history at relative proxy paths',async({page})=>{
  const calls:{path:string;method:string;body:unknown}[]=[];
  await page.route('**/api/agent/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    calls.push({path,method:request.method(),body:request.postData()?request.postDataJSON():null});
    if(path.endsWith('/status'))return route.fulfill({json:ready});
    if(path.endsWith('/sessions'))return route.fulfill({status:201,json:{session_id:fresh}});
    if(path.endsWith('/history'))return route.fulfill({json:{session_id:fresh,active_job_id:null,messages:[],running:false}});
    throw new Error('Unexpected Agent request');
  });
  await page.goto('/');await expect(page.getByTestId('agent-state')).toHaveText('READY');
  await expect(page.getByLabel('Assistant 메시지',{exact:true})).toBeEnabled();
  expect(calls.find(c=>c.path.endsWith('/sessions'))).toEqual({path:'/api/agent/sessions',method:'POST',body:{}});
  const first=calls.findIndex(c=>c.path.endsWith('/sessions'));
  expect(calls.slice(0,first).every(c=>c.path.endsWith('/status'))).toBe(true);
  expect(calls[first+1]).toEqual({path:`/api/agent/sessions/${fresh}/history`,method:'GET',body:null});
  expect(calls.filter(c=>c.path.endsWith('/sessions'))).toHaveLength(1); // StrictMode must not double-create.
  expect(await page.evaluate(k=>localStorage.getItem(k),key)).toBe(fresh);
  expect(new URL(page.url()).port).toBe(new URL(test.info().project.use.baseURL!).port);
});

test('valid saved session reuses history and a missing workspace does not break chat',async({page})=>{
  await page.addInitScript(({key,saved})=>localStorage.setItem(key,saved),{key,saved});
  let created=0;
  await page.route('**/api/agent/status',route=>route.fulfill({json:ready}));
  await page.route('**/api/agent/sessions',route=>{created++;return route.fulfill({status:500,json:{}});});
  await page.route(`**/api/agent/sessions/${saved}/history`,route=>route.fulfill({json:{session_id:saved,
    active_job_id:fresh,messages:[{role:'assistant',text:'저장된 대화'}],running:false}}));
  await page.route(`**/api/weld/${fresh}`,route=>route.fulfill({status:404,json:{detail:'private path'}}));
  await page.goto('/');await expect(page.getByLabel('Assistant 메시지',{exact:true})).toBeEnabled();
  await expect(page.getByRole('log',{name:'Assistant 대화'})).toContainText('저장된 대화');
  await expect(page.locator('.agent-warning')).toContainText('이전 작업 화면');
  expect(created).toBe(0);await expect(page.locator('p.agent-error')).toHaveCount(0);
});

for(const status of [404,410])test(`stale ${status} creates exactly one new session`,async({page})=>{
  await page.addInitScript(({key,saved})=>localStorage.setItem(key,saved),{key,saved});
  let created=0;
  await page.route('**/api/agent/status',route=>route.fulfill({json:ready}));
  await page.route(`**/api/agent/sessions/${saved}/history`,route=>route.fulfill({status,json:{code:'session_not_found'}}));
  await page.route('**/api/agent/sessions',route=>{created++;expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({});return route.fulfill({status:201,json:{session_id:fresh}});});
  await page.route(`**/api/agent/sessions/${fresh}/history`,route=>route.fulfill({json:{session_id:fresh,active_job_id:null,messages:[],running:false}}));
  await page.goto('/');await expect(page.getByLabel('Assistant 메시지',{exact:true})).toBeEnabled();
  expect(created).toBe(1);expect(await page.evaluate(k=>localStorage.getItem(k),key)).toBe(fresh);
  await expect(page.locator('p.agent-error')).toHaveCount(0);
});

test('temporary history failure preserves the existing session instead of creating another',async({page})=>{
  await page.addInitScript(({key,saved})=>localStorage.setItem(key,saved),{key,saved});
  let created=0,recovered=false;
  await page.route('**/api/agent/status',route=>route.fulfill({json:ready}));
  await page.route('**/api/agent/sessions',route=>{created++;return route.fulfill({status:500,json:{}});});
  await page.route(`**/api/agent/sessions/${saved}/history`,route=>recovered?
    route.fulfill({json:{session_id:saved,active_job_id:null,messages:[],running:false}}):
    route.fulfill({status:500,json:{detail:'sk-secret-private D:/private/raw-prompt'}}));
  await page.goto('/');await expect(page.getByTestId('agent-reason-code')).toHaveText('AGENT_HISTORY_LOAD_FAILED');
  expect(created).toBe(0);expect(await page.evaluate(k=>localStorage.getItem(k),key)).toBe(saved);
  await expect(page.locator('p.agent-error')).not.toContainText('private');
  recovered=true;await page.getByTestId('agent-reconnect').click();
  await expect(page.getByLabel('Assistant 메시지',{exact:true})).toBeEnabled();expect(created).toBe(0);
});

test('disabled Agent does not create or load a session',async({page})=>{
  let other=0;
  await page.route('**/api/agent/**',route=>new URL(route.request().url()).pathname.endsWith('/status')?
    route.fulfill({json:{...ready,enabled:false,state:'DISABLED'}}):
    (other++,route.fulfill({status:500,json:{}})));
  await page.goto('/');await expect(page.getByTestId('agent-state')).toHaveText('DISABLED');
  await expect(page.getByLabel('Assistant 메시지',{exact:true})).toBeDisabled();
  await expect(page.locator('.agent-config-note')).toContainText('비활성화');expect(other).toBe(0);
});

for(const [status,code] of [[500,'AGENT_SESSION_CREATE_FAILED'],[403,'AGENT_SESSION_ORIGIN_REJECTED']] as const)
test(`READY session creation ${status} shows safe specific error and reconnects`,async({page})=>{
  let recovered=false;
  await page.route('**/api/agent/status',route=>route.fulfill({json:ready}));
  await page.route('**/api/agent/sessions',route=>recovered?route.fulfill({status:201,json:{session_id:fresh}}):
    route.fulfill({status,json:{code:'invalid_request',detail:'D:/private sk-private-12345678 raw prompt'}}));
  await page.route(`**/api/agent/sessions/${fresh}/history`,route=>route.fulfill({json:{session_id:fresh,active_job_id:null,messages:[],running:false}}));
  await page.goto('/');await expect(page.getByTestId('agent-reason-code')).toHaveText(code);
  await expect(page.getByLabel('Assistant 메시지',{exact:true})).toBeDisabled();
  await expect(page.locator('p.agent-error')).not.toContainText('private');
  await expect(page.locator('.agent-config-note')).not.toContainText('Agent 설정 후');
  recovered=true;await page.getByTestId('agent-reconnect').click();
  await expect(page.getByLabel('Assistant 메시지',{exact:true})).toBeEnabled();
});
