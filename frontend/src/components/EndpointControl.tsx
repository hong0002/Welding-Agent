import {useEffect,useState} from 'react';
import {api} from '../api';
import type {Job} from '../types';

export function EndpointControl({job,busy,onApply}:{job:Job;busy:boolean;onApply:(xyz:[number,number,number],source:'user_selected_3d'|'dataset_gt_endpoint')=>void}) {
  const [fields,setFields]=useState(['','','']);
  const [source,setSource]=useState<'user_selected_3d'|'dataset_gt_endpoint'>('user_selected_3d');
  const [start,setStart]=useState<number[]|null>(null);
  const [error,setError]=useState(false);
  useEffect(()=>{
    let alive=true;
    setFields(job.user_endpoint?.end_xyz_mm.map(String)??['','','']);
    setSource(job.user_endpoint?.source??'user_selected_3d');setStart(null);setError(false);
    void api.endpointContext(job.id).then(value=>{if(alive)setStart(value.start_xyz_mm);}).catch(()=>{if(alive)setError(true);});
    return()=>{alive=false;};
  },[job.id,job.instruction?.text,job.user_endpoint?.revision]);
  const xyz=fields.map(Number);
  const valid=fields.every(s=>s.trim()!=='')&&xyz.every(Number.isFinite);
  const result=job.vla_prediction?.endpoint_diagnostics;
  return <div className="endpoint-control" data-testid="endpoint-control">
    <strong>3D 끝점 conditioning · {job.user_endpoint?'ON':'OFF'}</strong>
    <p>Start XYZ: {start?start.map(v=>v.toFixed(3)).join(', '):error?'시작점 확인 필요':'확인 중'} mm</p>
    <p>End XYZ: {job.user_endpoint?job.user_endpoint.end_xyz_mm.join(', '):'미지정'}</p>
    <small>Frame: source_robot_frame_unaligned_with_isaac · mm</small>
    <div className="endpoint-inputs">{['X','Y','Z'].map((axis,i)=><label key={axis}>End {axis} [mm]<input type="number" step="any" aria-label={`End ${axis} mm`} value={fields[i]} disabled={busy} onChange={event=>setFields(previous=>previous.map((v,n)=>n===i?event.target.value:v))}/></label>)}</div>
    <label className="field-label">끝점 출처<select aria-label="끝점 출처" value={source} disabled={busy} onChange={e=>setSource(e.target.value as typeof source)}><option value="user_selected_3d">사용자 지정 3D</option><option value="dataset_gt_endpoint">Dataset GT 끝점 · 시연용</option></select></label>
    {(source==='dataset_gt_endpoint'||job.user_endpoint?.source==='dataset_gt_endpoint')&&<small>GT 끝점 conditioning 시연 · blind prediction 성능평가 결과가 아닙니다.</small>}
    <button className="button secondary full-width" disabled={busy||!valid||!job.instruction} onClick={()=>onApply(xyz as [number,number,number],source)}>끝점 적용</button>
    <small>적용 시 기존 Final만 무효화합니다. 새 예측 후 검토하세요. 자동 GT 조회·사후 XYZ 보정 없음.</small>
    {result&&<p data-testid="endpoint-errors">Start error: {result.start_error_mm.toFixed(3)} mm · End error: {result.end_error_mm.toFixed(3)} mm<br/>End source: {result.end_source}</p>}
  </div>;
}
