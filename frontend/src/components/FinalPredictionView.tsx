import {useEffect,useState} from 'react';
import type {Job} from '../types';

type Display={artifact_id:string;coordinate_frame:string;units:string;runs:number[][][]};
/** Display-only projections retain independent finite runs; never transmit edited XYZ. */
export function FinalPredictionView({job}:{job:Job}) {
  const raw=job.raw_final_prediction;
  const [value,setValue]=useState<{id:string;data:Display}|null>(null);
  const [plane,setPlane]=useState<'XY'|'XZ'|'YZ'>('XY');
  useEffect(()=>{
    setValue(null);
    if(!raw?.displayable||raw.display_url!==`/api/weld/${job.id}/final-trajectory/${raw.artifact_id}/display`)return;
    const abort=new AbortController();
    void fetch(raw.display_url,{signal:abort.signal,cache:'no-store'}).then(async r=>{
      if(!r.ok)throw new Error('Unavailable');
      const data=await r.json() as Display;
      if(data.artifact_id!==raw.artifact_id||!Array.isArray(data.runs)||!data.runs.every(run=>run.every(p=>p.length===3&&p.every(Number.isFinite))))return;
      setValue({id:raw.artifact_id,data});
    }).catch(()=>{});
    return()=>abort.abort();
  },[job.id,raw?.artifact_id,raw?.display_url,raw?.displayable]);
  if(!raw)return null;
  const axes=plane==='XY'?[0,1]:plane==='XZ'?[0,2]:[1,2];
  const data=value?.id===raw.artifact_id?value.data:null;
  const points=data?.runs.flat()??[];
  const min=axes.map(axis=>Math.min(...points.map(p=>p[axis])));
  const max=axes.map(axis=>Math.max(...points.map(p=>p[axis])));
  const scale=230/Math.max(max[0]-min[0],max[1]-min[1],1e-9);
  const project=(p:number[])=>`${20+(p[axes[0]]-min[0])*scale},${255-(p[axes[1]]-min[1])*scale}`;
  return <div className="vla-summary" data-testid="final-raw-output">
    <strong>GPT Trajectory · Raw model output</strong>
    <p>Source: vlm_final_gpt · {raw.point_count} points · {raw.validation_status}</p>
    <p>{raw.coordinate_frame} · {raw.units}</p>
    <p>{raw.simulator_eligible?'최종 예측 검증 통과':'표시 전용 · Simulator 차단'}{raw.omitted_point_count>0?` · 비유한 점 ${raw.omitted_point_count}개 생략`:''}</p>
    <label>좌표 투영 <select aria-label="Final XYZ projection" value={plane} onChange={e=>setPlane(e.target.value as typeof plane)}><option>XY</option><option>XZ</option><option>YZ</option></select></label>
    {data&&points.length>0?<svg viewBox="0 0 280 280" role="img" aria-label={`Raw GPT XYZ ${plane} projection`}>
      {data.runs.map((run,i)=><g key={i}><polyline points={run.map(project).join(' ')} fill="none" stroke="#c52d3e" strokeWidth="2"/>{run.length===1&&<circle cx={Number(project(run[0]).split(',')[0])} cy={Number(project(run[0]).split(',')[1])} r="3" fill="#c52d3e"/>}</g>)}
    </svg>:<small>{raw.displayable?'현재 작업의 raw 표시 결과를 불러올 수 없습니다.':'렌더링 가능한 XYZ 결과 없음'}</small>}
    <small>원본 수치·순서 보존 · 화면 투영만 사용 · 실행 불가</small>
  </div>;
}
