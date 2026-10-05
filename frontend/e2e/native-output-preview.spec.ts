import {expect,test,type Page} from '@playwright/test';

async function prepare(page:Page){
  await page.goto('/');await page.getByLabel('Dataset sample ID').fill('SAMPLE_1');
  await page.getByRole('button',{name:'9 views 불러오기'}).click();
  await page.getByTestId('native-segment').click();
  await expect(page.getByTestId('mask-status')).toHaveText('승인 대기');
  await page.getByTestId('confirm-mask').click();
  await page.getByText('수동 지시 / 디버그',{exact:true}).click();
  await page.getByRole('button',{name:'지시 분석',exact:true}).click();
  await expect(page.getByTestId('parsed-instruction')).toContainText('left_to_right');
  await page.getByRole('tab',{name:'경로 계획',exact:true}).click();
}

test('soft validation FAIL preserves native Canvas points and blocks VLA',async({page,request})=>{
  await request.post('/api/test/native-output-mode',{data:{mode:'soft'}});
  const forbidden:string[]=[];
  page.on('request',r=>{if(r.method()==='POST'&&(/guided-vla|simulator\//.test(r.url())))forbidden.push(r.url());});
  await prepare(page);
  const result=page.waitForResponse('**/api/weld/plan');
  await page.getByRole('button',{name:'용접 경로 생성',exact:true}).click();
  const job=await(await result).json();
  expect(job.native_output.status).toBe('NATIVE_OUTPUT_READY_UNVALIDATED');
  const original=Array.from({length:9},(_,i)=>[10+i*10,70.25]);
  expect(job.native_output.candidate.segments[0].points_pixel).toEqual(original);
  expect(job.rough_trajectory).toBeNull();
  await expect(page.getByTestId('native-output-panel')).toContainText('경로 생성 완료 · 9 points');
  await expect(page.getByTestId('native-output-panel')).toContainText('검증 미통과');
  await expect(page.getByTestId('native-vla-policy')).toContainText('Blocked by validation');
  await expect(page.getByTestId('run-guided-vla')).toBeDisabled();
  await expect(page.getByTestId('show-native-output')).toBeVisible();
  await expect(page.getByLabel('Native model path',{exact:true})).toBeChecked();
  await expect(page.getByTestId('native-path-label')).toContainText('검증 미통과');
  const labelBox=(await page.getByTestId('native-path-label').boundingBox())!;
  const canvasBox=(await page.getByTestId('canvas-host').boundingBox())!;
  expect(labelBox.x).toBeGreaterThanOrEqual(canvasBox.x);
  expect(labelBox.y).toBeGreaterThanOrEqual(canvasBox.y);
  // Verify the actual Konva nodes, not an extra test representation of the path.
  const rendered=await page.getByTestId('drawing-surface').evaluate(()=>{
    // Read the application's actual Konva singleton and stage.
    const Konva=(window as any).Konva;
    const stage=Konva.stages.find((s:any)=>s.container().closest('[data-testid="drawing-surface"]'));
    return stage.find('.native-model-path').map((line:any)=>({points:line.points(),dash:line.dash(),stroke:line.stroke()}));
  });
  expect(rendered).toEqual([{points:original.flat(),dash:expect.any(Array),stroke:'#ff9c61'}]);
  expect(rendered[0].dash.length).toBe(2);
  await page.getByLabel('Native model path',{exact:true}).uncheck();
  await expect(page.getByTestId('native-path-label')).toHaveCount(0);
  await page.getByTestId('view-R').click();
  await page.getByTestId('show-native-output').click();
  await expect(page.getByTestId('view-F')).toHaveAttribute('aria-selected','true');
  await expect(page.getByTestId('native-path-label')).toBeVisible();
  await page.getByText('Native guidance 시각화 보기',{exact:true}).click();
  await expect.poll(()=>page.getByAltText('Native guidance 원본 artifact · 실행 불가').evaluate((img:HTMLImageElement)=>img.naturalWidth)).toBeGreaterThan(0);
  expect(forbidden).toEqual([]);
  await page.screenshot({path:'test-results/native-output-warning.png',fullPage:true});
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
});

test('partial artifacts display existing finite geometry without accepting a final path',async({page,request})=>{
  await request.post('/api/test/native-output-mode',{data:{mode:'partial'}});
  await prepare(page);
  await page.getByRole('button',{name:'용접 경로 생성',exact:true}).click();
  await expect(page.getByTestId('native-output-status')).toHaveText('PARTIAL_NATIVE_OUTPUT');
  await expect(page.getByTestId('native-output-panel')).toContainText('추가 확인을 요청');
  await expect(page.getByTestId('show-native-output')).toBeVisible();
  await expect(page.getByTestId('native-path-label')).toContainText('PARTIAL');
  await expect(page.getByTestId('run-guided-vla')).toBeDisabled();
  await page.getByText('Native artifact summary',{exact:true}).click();
  await expect(page.locator('.native-artifact-list')).toContainText('query_image_guidance_2d.json');
  await expect(page.locator('.native-artifact-list')).toContainText('clarification.json');
  await expect(page.locator('body')).not.toContainText('PRIVATE QUESTION');
  await request.post('/api/test/native-output-mode',{data:{mode:'pass'}});
});
