import {expect,test} from '@playwright/test';

test('chat scene → configured Segment2 mask → human F approval → Trajectory3 → offline Guided VLA_READY',async({page,request})=>{
  const mutations:string[]=[];
  page.on('request',r=>{if(r.method()==='POST')mutations.push(new URL(r.url()).pathname);});
  await page.goto('/');
  await expect(page.getByTestId('agent-state')).toHaveText('READY');
  const composer=page.getByLabel('Assistant 메시지',{exact:true});
  async function send(message:string){
    const before=await page.locator('.agent-message.assistant').count();
    await composer.fill(message);await composer.press('Enter');
    await expect(page.locator('.agent-message.assistant')).toHaveCount(before+1);
    await expect(composer).toBeEnabled();
  }
  await send('SAMPLE_1 불러와');
  await expect(page.getByRole('tablist',{name:'Scene views'}).getByRole('tab')).toHaveCount(9);
  await page.getByTestId('view-R').click();
  await send('마스크 씌워줘');
  await expect(page.getByTestId('view-F')).toHaveAttribute('aria-selected','true');
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  for(const view of ['F','R','S4'])await expect(page.getByTestId(`view-${view}`)).toContainText('MASK');
  for(const view of ['B','L','S1','S2','S3','T'])await expect(page.getByTestId(`view-${view}`)).not.toContainText('MASK');
  await expect(page.getByRole('log',{name:'Assistant 대화'})).toContainText('마스크 확정 · F');
  await expect.poll(()=>page.getByTestId('drawing-surface').evaluate(el=>{
    const canvas=el.querySelectorAll('canvas')[1];
    return Array.from(canvas.getContext('2d')!.getImageData(0,0,canvas.width,canvas.height).data).some((v,i)=>i%4===3&&v>0);
  })).toBeTruthy();
  await request.post('/api/test/semantic-action',{data:{action:'ROUGH_TRAJECTORY_GENERATE'}});
  await send('왼쪽에서 오른쪽으로 용접해');
  await expect(page.getByTestId('agent-reason-code')).toHaveText('MASK_APPROVAL_REQUIRED');
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
  await page.getByTestId('confirm-mask').click();
  await expect(page.getByTestId('view-F')).toContainText('APPROVED');
  await send('왼쪽에서 오른쪽으로 용접해');
  await expect(page.getByTestId('workflow-state')).toHaveText('ROUGH_PATH_READY');
  await page.getByRole('tab',{name:'경로 계획',exact:true}).click();
  await expect(page.getByTestId('rough3d-summary')).toContainText('2D guidance ready · 9 pts');
  await page.getByTestId('run-guided-vla').click();
  await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');
  await page.getByRole('tab',{name:'Assistant',exact:true}).click();
  await send('마스크 다시 찾아줘');
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  await expect(page.getByTestId('workflow-state')).toHaveText('MASK_READY');
  expect(mutations.filter(p=>p.startsWith('/api/simulator/'))).toEqual([]);
  await page.screenshot({path:'test-results/native-stack-agent-mask.png',fullPage:true});
});
