import {expect,test,type Page} from '@playwright/test';
import {parseDecision,preflightDecision} from '../src/agentDecision';

async function send(page:Page,message:string){
  const before=await page.locator('.agent-message.assistant').count();
  await page.getByLabel('Assistant 메시지',{exact:true}).fill(message);
  await page.getByLabel('Assistant 메시지',{exact:true}).press('Enter');
  await expect(page.locator('.agent-message.assistant')).toHaveCount(before+1);
  await expect(page.getByLabel('Assistant 메시지',{exact:true})).toBeEnabled();
}

test('safe summary follows mask → human approval → guidance → semantic VLA once, then reuse and preview guidance',async({page,request})=>{
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const simulator:string[]=[];
  page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/api/simulator/'))simulator.push(r.url());});
  await page.goto('/');
  await expect(page.getByTestId('agent-state')).toHaveText('READY');
  await send(page,'SAMPLE_1 불러와');
  await send(page,'마스크 다시 만들어줘. 조금 더 전체 영역으로 해줘');
  const card=page.getByTestId('agent-decision-summary');
  await expect(card).toHaveCount(1);
  await expect(card).toContainText('용접 마스크 재검출');
  await expect(card).toContainText('F 마스크를 검토');
  await card.getByText('선택 이유와 준비 상태',{exact:true}).click();
  await expect(card.getByTestId('decision-reason-code')).toHaveText('USER_REQUESTED_MASK_REDETECTION');
  // Unapproved F: frontend preflight shows a structured block, sends no tool.
  await page.getByLabel('Assistant 메시지',{exact:true}).fill('VLA로 실제 궤적 생성해줘');
  await page.getByLabel('Assistant 메시지',{exact:true}).press('Enter');
  await expect(card).toHaveAttribute('data-status','blocked');
  await expect(page.getByRole('alert')).toContainText('F 마스크');
  await page.getByTestId('confirm-mask').click();
  await send(page,'왼쪽에서 오른쪽으로 경로 만들어줘');
  await expect(card).toHaveAttribute('data-status','completed');
  await expect(card).toContainText('Trajectory3');
  await expect(card).toContainText('Guided VLA 생성을 요청');
  await send(page,'VLA로 실제 궤적 생성해줘');
  await expect(page.getByTestId('workflow-state')).toHaveText('VLA_READY');
  await expect(card).toHaveAttribute('data-status','completed');
  await expect(card).toContainText('최종 3D VLA');
  await card.locator('details').evaluate(el=>(el as HTMLDetailsElement).open=true);
  await expect(card).toContainText('9 views · 9 points');
  await expect(card).not.toContainText(/points_xyz|cot_ko|raw_prompt|sk-/);
  await send(page,'최종 3D 경로 예측해줘');
  await expect(card.getByTestId('decision-reason-code')).toHaveText('GUIDED_VLA_ALREADY_READY');
  await send(page,'VLA 결과를 보여줘');
  await expect(card.getByTestId('decision-reason-code')).toHaveText('READ_ONLY_REQUEST');
  await send(page,'Robot Preview 실행해줘');
  await expect(card).toContainText('Simulator 패널에서 별도 실행');
  await expect(card.getByTestId('decision-reason-code')).toHaveText('SIMULATOR_PREVIEW_INTENT');
  await send(page,'실제 경로 해줘');
  await expect(card).toHaveAttribute('data-status','clarification');
  await expect(card).toHaveCount(1);
  const after=await(await request.get('/api/test/native-call-counts')).json();
  expect(after.segment-before.segment).toBe(1);expect(after.rough3d-before.rough3d).toBe(1);
  expect(after.guided_vla-before.guided_vla).toBe(1);expect(after.guided_health-before.guided_health).toBe(1);
  expect(simulator).toEqual([]);
  await page.screenshot({path:'test-results/agent-decision-summary.png',fullPage:true});
  await page.getByRole('button',{name:'새 대화',exact:true}).click();
  await expect(card).toHaveCount(0);
});

test('unsaved view mask blocks VLA with no stream or mask auto-sync; native rejection has safe summary',async({page,request})=>{
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
  await page.goto('/');await expect(page.getByTestId('agent-state')).toHaveText('READY');
  await send(page,'SAMPLE_1 불러와');await send(page,'마스크 씌워줘');
  await page.getByTestId('confirm-mask').click();
  await page.getByTestId('view-R').click();
  const canvas=page.getByTestId('drawing-surface');await canvas.scrollIntoViewIfNeeded();
  const box=(await canvas.boundingBox())!;
  await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5);await page.mouse.down();
  await page.mouse.move(box.x+box.width*.6,box.y+box.height*.5,{steps:5});await page.mouse.up();
  await page.getByTestId('view-F').click();
  const calls:string[]=[];
  page.on('request',r=>{if(r.method()==='POST')calls.push(new URL(r.url()).pathname);});
  const before=await(await request.get('/api/test/native-call-counts')).json();
  await page.getByLabel('Assistant 메시지').fill('최종 XYZ 경로 만들어줘');
  await page.getByLabel('Assistant 메시지').press('Enter');
  await expect(page.getByTestId('agent-reason-code')).toHaveText('MASK_DRAFT_UNSAVED');
  await expect(page.getByTestId('agent-decision-summary')).toHaveAttribute('data-status','blocked');
  expect(calls).toEqual([]);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(before);
  // A frontend-only preflight has no backend job UUID. Selecting another job
  // must still clear that previous block instead of leaving a stale card.
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await expect(page.getByTestId('agent-decision-summary')).toHaveCount(0);
  // Reload discards only the unsaved draft, retaining exact approved backend F.
  await page.reload();await expect(page.getByTestId('agent-state')).toHaveText('READY');
  await expect(page.getByTestId('view-F')).toContainText('APPROVED');
  await page.route('**/api/agent/chat/stream',route=>route.fulfill({status:422,json:{code:'NATIVE_OUTPUT_HARD_INVALID',detail:'현재 입력 연결을 확인할 수 없습니다.'}}));
  await page.getByLabel('Assistant 메시지').fill('실제 3D 궤적 생성해줘');
  await page.getByLabel('Assistant 메시지').press('Enter');
  await expect(page.getByTestId('agent-reason-code')).toHaveText('NATIVE_OUTPUT_HARD_INVALID');
  const card=page.getByTestId('agent-decision-summary');
  await expect(card).toHaveAttribute('data-status','blocked');
  await expect(card).toContainText('현재 승인 마스크와 지시');
});

test('summary transport rejects raw text and updates one card without duplicating delta history',async({page})=>{
  const safe={...preflightDecision('MASK_APPROVAL_REQUIRED'),intent:'guided_vla_execution',selected_action:'guided_vla',
    reason_code:'USER_REQUESTED_GUIDED_VLA_EXECUTION',status:'planned',next_step:'simulator_panel'};
  expect(parseDecision({...safe,raw_prompt:'PRIVATE_REASONING'})).toBeNull();
  expect(parseDecision({...safe,current_step:'C:/secret/sk-test-token'})).toBeNull();
  await page.addInitScript(()=>{
    const original=window.fetch.bind(window);
    window.fetch=async(input,init)=>{
      if(String(input)!=='/api/agent/chat/stream')return original(input,init);
      const encoder=new TextEncoder();
      let controller:ReadableStreamDefaultController<Uint8Array>;
      const body=new ReadableStream<Uint8Array>({start(c){controller=c;}});
      Object.assign(window,{emitDecisionTest:(event:string,data:unknown)=>controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)),
        closeDecisionTest:()=>controller.close()});
      return new Response(body,{status:200,headers:{'Content-Type':'text/event-stream'}});
    };
  });
  await page.goto('/');await expect(page.getByTestId('agent-state')).toHaveText('READY');
  await page.getByLabel('Assistant 메시지').fill('VLA 실행해줘');await page.getByLabel('Assistant 메시지').press('Enter');
  await expect.poll(()=>page.evaluate(()=>typeof (window as unknown as {emitDecisionTest:unknown}).emitDecisionTest)).toBe('function');
  const emit=async(event:string,data:unknown)=>page.evaluate(({event,data})=>{
    (window as unknown as {emitDecisionTest:(event:string,data:unknown)=>void}).emitDecisionTest(event,data);
  },{event,data});
  const card=page.getByTestId('agent-decision-summary');
  await emit('decision_summary',safe);await expect(card).toHaveAttribute('data-status','planned');
  await emit('decision_summary',{...safe,status:'running',current_step:'guided_vla'});await expect(card).toHaveAttribute('data-status','running');
  await emit('decision_summary',{...safe,status:'blocked',raw_prompt:'PRIVATE_REASONING sk-token C:/private'});
  await expect(card).toHaveAttribute('data-status','running');
  await emit('assistant_delta',{text:'예측 '});await emit('assistant_delta',{text:'완료'});
  await emit('decision_summary',{...safe,status:'completed',current_step:'result',point_count:9});
  await emit('done',{ok:true,session_id:'fake',job_id:null});
  await page.evaluate(()=>(window as unknown as {closeDecisionTest:()=>void}).closeDecisionTest());
  await expect(card).toHaveAttribute('data-status','completed');await expect(card).toHaveCount(1);
  await expect(page.locator('.agent-message.assistant')).toHaveCount(1);
  await expect(page.locator('.agent-message.assistant')).toHaveText('ASSISTANT예측 완료');
  await expect(card).not.toContainText(/PRIVATE_REASONING|sk-token|C:\/private/);
});
