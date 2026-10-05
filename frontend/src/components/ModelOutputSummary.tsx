import type {NativeOutput} from '../types';

export function ModelOutputSummary({output,model,onShow,onEdit,approved=false,downstreamAllowed=true}:{output:NativeOutput|null|undefined;model:string;onShow?:()=>void;onEdit?:()=>void;approved?:boolean;downstreamAllowed?:boolean}){
  if(!output)return null;
  const d=output.model_output;
  const passed=output.validation.status==='PASS';
  return <section className="model-output-summary" data-testid={`${model.toLowerCase()}-output-summary`}>
    <span className="utility-label">{model} · MODEL OUTPUT</span>
    <dl><div><dt>Model output</dt><dd>{d?.available?'GENERATED':'NOT GENERATED'}{d?.point_count?` · ${d.point_count} points`:''}</dd></div>
      <div><dt>Validation</dt><dd>{output.validation.status}</dd></div>
      <div><dt>Display</dt><dd>{d?.displayable?d.overlay_allowed?'VISIBLE':'DIAGNOSTIC ONLY':'UNAVAILABLE'}</dd></div>
      <div><dt>Downstream</dt><dd>{model==='SEGMENT2'?passed&&approved?'APPROVED MASK':'BLOCKED · F 승인 필요':passed&&d?.guided_vla_allowed&&downstreamAllowed?'VALIDATED':'BLOCKED'}</dd></div></dl>
    <code>{d?.status??'OUTPUT_MISSING'}</code>
    {model==='SEGMENT2'&&<p>Approval: {approved?'APPROVED':'NOT APPROVED'} · 표시와 승인은 별도입니다.</p>}
    {d?.omitted_point_count? <p>{d.point_count} / {d.point_count+d.omitted_point_count} finite points displayed · {d.omitted_point_count} invalid points omitted</p>:null}
    {!passed&&d?.available&&<p>모델 출력은 생성되었습니다. 검증을 통과하지 않아 downstream에는 적용되지 않았습니다.</p>}
    {output.validation.issues.map(i=><p key={i.code}><code>{i.code.toUpperCase()}</code> · {i.message}</p>)}
    {d?.warnings.map(code=><p key={code}><code>{code}</code></p>)}
    {d?.displayable&&onShow&&<button className="button secondary" onClick={onShow}>모델 출력 보기</button>}
    {d?.displayable&&d.overlay_allowed&&onEdit&&<button className="button secondary" data-testid="edit-raw-mask" onClick={onEdit}>Raw 마스크 검토·수정</button>}
    {d?.displayable&&!d.overlay_allowed&&<details open data-testid="foreign-model-output"><summary>foreign/stale model output · 현재 Canvas에 겹치지 않음</summary>
      {d.width&&d.height&&<svg className="diagnostic-path" viewBox={`0 0 ${d.width} ${d.height}`} aria-label="Foreign model path diagnostic">
        {d.segments.flatMap(s=>s.runs.map((run,i)=><g key={`${s.segment_index}:${i}`}><polyline points={run.map(p=>p.join(',')).join(' ')} fill="none" stroke="#ff9c61" strokeWidth="2" strokeDasharray="3 4"/>{run.map((p,j)=><circle key={j} cx={p[0]} cy={p[1]} r="1" fill="#ff9c61"/>)}</g>))}</svg>}
      {Object.entries(d.mask_urls).map(([view,url])=><img key={view} src={url} alt={`Foreign raw ${view} mask · display only`}/>)}
    </details>}
  </section>;
}
