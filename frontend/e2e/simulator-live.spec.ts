import {expect,test,type Page,type APIRequestContext} from '@playwright/test';
import {randomUUID} from 'node:crypto';

// An eight-pixel procedural JPEG fixture, never a real Isaac frame.
const jpeg=Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAGAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDi6KKK+ZP3E//Z','base64');
const multipart=Buffer.concat([Buffer.from(`--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${jpeg.length}\r\n\r\n`),jpeg,Buffer.from('\r\n--frame--\r\n')]);

async function setup(page:Page,request:APIRequestContext){
  const before=await(await request.get('/api/test/native-call-counts')).json();
  const job=await(await request.get('/api/test/bpp-preview-fixture')).json();
  const base=await(await request.get('/api/simulator/status')).json();
  const session=randomUUID(),requestId=randomUUID(),digest='a'.repeat(64);
  const status:any={...base,can_stop:true,backend:'dataset_stp',current_preview:{...base.current_preview,configured:true,state:'RUNNING_PREVIEW',can_stop:true,
    latest:{job_id:job.id,artifact_id:job.vla_prediction.artifact_id,package_id:randomUUID(),sample_id:job.scene.sample_id,
      request_id:requestId,session_id:session,point_count:9,status:'QUEUED',kind:'robot',robot_motion:false,error:null}}};
  const url=`/api/simulator/current-preview/live/${session}/${requestId}?job_id=${job.id}&artifact_id=${job.vla_prediction.artifact_id}`;
  const gallery:any={available:true,job_id:job.id,artifact_id:job.vla_prediction.artifact_id,session_id:session,request_id:requestId,kind:'robot',delivery:'latest_capture',reason_code:null,
    live:{available:true,state:'LIVE',fps:8,target_fps:8,url,warning:null},
    frames:['P0','P4','P8','path_detail'].map(name=>({name,sha256:digest,width:8,height:6,captured_at:new Date().toISOString(),
      url:`/api/simulator/current-preview/frames/${session}/${requestId}/${name}/${digest}.png?job_id=${job.id}&artifact_id=${job.vla_prediction.artifact_id}`}))};
  await page.route('**/api/agent/sessions/*/history',r=>r.fulfill({json:{session_id:'fixture',active_job_id:job.id,messages:[],running:false}}));
  await page.route('**/api/simulator/status',r=>r.fulfill({json:status}));
  await page.route('**/api/simulator/current-vla/capabilities?*',r=>r.fulfill({json:{sample_id:job.scene.sample_id,backend:'dataset_stp',path_preview_ready:true,robot_preview_ready:true,warnings:[],configuration_codes:[]}}));
  await page.route('**/api/simulator/current-preview/frames?*',r=>r.fulfill({json:gallery}));
  await page.route('**/api/simulator/current-preview/frames/**/*.png?*',r=>r.fulfill({contentType:'image/jpeg',body:jpeg}));
  await page.route('**/api/simulator/current-preview/live/**',r=>r.fulfill({contentType:'multipart/x-mixed-replace; boundary=frame',headers:{'Cache-Control':'no-store'},body:multipart}));
  const posts:string[]=[];
  page.on('request',r=>{if(r.method()==='POST'&&!r.url().endsWith('/agent/sessions'))posts.push(r.url());});
  await page.goto('/');await page.getByRole('tab',{name:'시뮬레이션',exact:true}).click();
  return {before,status,gallery,posts,job};
}

test('MJPEG live by default, capture tabs and Stop remove the owned stream',async({page,request})=>{
  const f=await setup(page,request),viewer=page.getByTestId('simulator-viewport');
  await expect(viewer.getByTestId('simulator-live-image')).toBeVisible();
  await expect.poll(()=>viewer.getByTestId('simulator-live-image').evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBe(8);
  await expect(viewer.getByTestId('simulator-live-state')).toContainText('LIVE');
  await viewer.getByRole('button',{name:'P4',exact:true}).click();
  await expect(viewer.getByTestId('simulator-live-image')).toHaveCount(0);
  await expect(viewer.locator('img')).toHaveAttribute('src',/\/P4\//);
  await expect(viewer.getByTestId('simulator-live-state')).toContainText('PAUSED');
  await viewer.getByRole('button',{name:'실시간',exact:true}).click();
  await expect(viewer.getByTestId('simulator-live-image')).toBeVisible();
  await page.screenshot({path:'test-results/simulator-live-fake.png',fullPage:true});
  await page.route('**/api/simulator/stop',r=>{f.status.current_preview.state='STOPPED';f.status.can_stop=false;return r.fulfill({json:f.status});});
  await page.getByTestId('current-preview-stop').click();
  await expect(viewer.locator('img')).toHaveCount(0);
  await expect(viewer.getByTestId('simulator-live-state')).toContainText('OFFLINE');
  expect(f.posts).toHaveLength(1);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(f.before);
});

test('stream failure uses capture without failing execution; stale request and foreign URLs stay hidden',async({page,request})=>{
  const f=await setup(page,request),viewer=page.getByTestId('simulator-viewport');
  await expect(viewer.getByTestId('simulator-live-image')).toBeVisible();
  await page.route('**/api/simulator/current-preview/live/**',r=>r.abort());
  await viewer.getByRole('button',{name:'P0',exact:true}).click();
  await viewer.getByRole('button',{name:'실시간',exact:true}).click();
  await expect(viewer.getByTestId('simulator-live-image')).toHaveCount(0);
  await expect(viewer).toContainText('Live stream 연결을 확인하세요');
  await expect(viewer.locator('img')).toBeVisible();
  expect(f.status.current_preview.state).toBe('RUNNING_PREVIEW');
  f.status.current_preview.latest.request_id=randomUUID();
  await expect(viewer.locator('img')).toHaveCount(0);
  f.status.current_preview.latest.request_id=f.gallery.request_id;
  f.gallery.live.url='https://example.invalid/private';
  await expect(viewer.getByRole('button',{name:'실시간',exact:true})).toBeDisabled();
  await expect(viewer.getByTestId('simulator-live-image')).toHaveCount(0);
  expect(f.posts).toEqual([]);
  expect(await(await request.get('/api/test/native-call-counts')).json()).toEqual(f.before);
});
