import {useEffect,useState,useRef} from 'react';
import type {Job} from '../types';
export type OutputRow={id:string;stage:string;stage_index?:number;label:string;stale:boolean;sample_id?:string;current_overlay_allowed?:boolean;
  states:Record<string,boolean>;warnings?:string[];mask_urls?:Record<string,string>;dimensions?:number;
  segments?:{runs:number[][][]}[];runs?:number[][][];coordinate_frame?:string;units?:string;display_url?:string};
export const outputKey=(r:OutputRow)=>`${r.stage}:${r.id}${r.stage_index===undefined?'':`:${r.stage_index}`}`;
export const isXYZ=(r:OutputRow)=>r.dimensions===3||r.stage==='final';
function splitFinite(paths:number[][][],dimensions:number){
  const result:number[][][]=[];
  for(const path of paths){let run:number[][]=[];
    for(const p of path){if(Array.isArray(p)&&p.length===dimensions&&p.every(v=>typeof v==='number'&&Number.isFinite(v)))run.push(p);
      else if(run.length){result.push(run);run=[];}}
    if(run.length)result.push(run);
  }return result;
}
/** All result reads are independent from promotion. This viewer never overlays Canvas. */
export function OutputBrowser({job,jobId,xyzOnly=false,onPreferred,refreshKey}:{job?:Job;jobId?:string;xyzOnly?:boolean;onPreferred?:(row:OutputRow|null)=>void;refreshKey?:string}){
  const id=job?.id??jobId;
  const [rows,setRows]=useState<OutputRow[]>([]);const [selected,setSelected]=useState('');
  const explicitSelection=useRef('');
  const [runs,setRuns]=useState<number[][][]>([]);const [plane,setPlane]=useState<'XY'|'XZ'|'YZ'>('XY');const [error,setError]=useState('');
  useEffect(()=>{explicitSelection.current='';setRows([]);setSelected('');setRuns([]);setError('');onPreferred?.(null);},[id,onPreferred]);
  useEffect(()=>{if(!id)return;const abort=new AbortController();setError('');
    void fetch(`/api/weld/${id}/model-outputs`,{signal:abort.signal,cache:'no-store'}).then(async r=>{
      if(!r.ok)throw Error();const data=await r.json();if(data.job_id!==id)return;
      const next:OutputRow[]=data.outputs.filter((v:OutputRow)=>!xyzOnly||isXYZ(v));setRows(next);
      setSelected(previous=>explicitSelection.current===previous&&next.some(r=>outputKey(r)===previous)?previous:outputKey(
        next.find(r=>r.stage==='final'&&r.states.OUTPUT_RENDERABLE&&!r.stale)??
        next.find(r=>r.stage==='prediction'&&r.states.OUTPUT_RENDERABLE&&!r.stale)??
        [...next].reverse().find(r=>isXYZ(r)&&r.states.OUTPUT_RENDERABLE&&!r.stale)??[...next].reverse().find(r=>isXYZ(r)&&r.states.OUTPUT_RENDERABLE)??[...next].reverse().find(r=>r.states.OUTPUT_RENDERABLE&&!r.stale)??[...next].reverse().find(r=>r.states.OUTPUT_RENDERABLE)??next[0]??{stage:'',id:''} as OutputRow));
    }).catch(()=>{if(!abort.signal.aborted)setError('결과 상태를 갱신하지 못했습니다. 이미 불러온 결과는 계속 표시합니다.');});
    return()=>abort.abort();
  },[id,job,xyzOnly,refreshKey]);
  const row=rows.find(r=>outputKey(r)===selected);
  useEffect(()=>{onPreferred?.(row&&isXYZ(row)&&row.states.OUTPUT_RENDERABLE?row:null);},[row,onPreferred]);
  useEffect(()=>{setRuns([]);if(!row?.display_url||row.runs||!id)return;const abort=new AbortController();
    if(!row.display_url.startsWith(`/api/weld/${id}/final-trajectory/`))return;
    void fetch(row.display_url,{signal:abort.signal,cache:'no-store'}).then(async r=>{
      if(!r.ok)throw Error();const data=await r.json();if(data.artifact_id===row.id)setRuns(data.runs??[]);
    }).catch(()=>{});return()=>abort.abort();
  },[id,row]);
  const xyz=!!row&&isXYZ(row);const paths=splitFinite(row?.runs??(xyz?runs:row?.segments?.flatMap(s=>s.runs)??[]),xyz?3:2);
  const axes=xyz?(plane==='XY'?[0,1]:plane==='XZ'?[0,2]:[1,2]):[0,1];const points=paths.flat();
  const min=axes.map(a=>Math.min(...points.map(p=>p[a]))),max=axes.map(a=>Math.max(...points.map(p=>p[a])));
  const scale=240/Math.max(max[0]-min[0],max[1]-min[1],1e-9);const point=(p:number[])=>`${15+(p[axes[0]]-min[0])*scale},${255-(p[axes[1]]-min[1])*scale}`;
  const currentXYZ=rows.some(r=>isXYZ(r)&&r.states.OUTPUT_RENDERABLE&&!r.stale);const previous=rows.some(r=>r.states.OUTPUT_RENDERABLE&&r.stale);
  const group=(r:OutputRow)=>r.stale?'Previous':!r.states.OUTPUT_VALIDATED&&r.stage!=='mask'?'Rejected / Raw':'Current';
  return <details className="vla-summary" data-testid={xyzOnly?'simulator-output-browser':'output-browser'} open={xyzOnly||(!currentXYZ&&previous)}>
    <summary>모델 출력 보기 / 이전 결과 보기</summary>
    {(!currentXYZ&&previous||job?.latest_final_attempt?.status==='FAILED')&&<p data-testid="last-available-result">NEW GPT OUTPUT: unavailable · LAST AVAILABLE OUTPUT: 아래에서 확인할 수 있습니다.</p>}
    {error&&<p>{error}</p>}
    <label>결과 선택 <select aria-label={xyzOnly?'Simulator result source':'Model output source'} value={selected} onChange={e=>{explicitSelection.current=e.target.value;setSelected(e.target.value);}}>
      <option value="">모델 출력 선택</option>{['Current','Previous','Rejected / Raw'].map(g=><optgroup key={g} label={g}>{rows.filter(r=>group(r)===g).map(r=><option key={outputKey(r)} value={outputKey(r)}>{r.label} {r.stale?'· STALE / PREVIOUS':''}</option>)}</optgroup>)}
    </select></label>
    {row&&<><strong>{row.label} · {row.stale?'STALE / PREVIOUS':'MODEL OUTPUT'}</strong>
      {xyz&&<p data-testid="original-prediction-label">Original Prediction · source XYZ 그대로 · 아래 viewer는 Demo 변환본과 별도</p>}
      <dl>{Object.entries(row.states).filter(([k])=>k!=='physical_robot_executable').map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v?'YES':'NO'}</dd></div>)}</dl>
      <p>Artifact viewer · {row.sample_id??'sample identity unavailable'} · 현재 Canvas/scene에 자동 overlay하지 않음</p>
      {(row.warnings??[]).map(w=><small key={w}>{w}<br/></small>)}
      {Object.entries(row.mask_urls??{}).map(([v,url])=><figure key={v}><figcaption>{v} · {row.label}</figcaption><img className="reference-preview" src={url} alt={`${row.label} ${v} raw raster`}/></figure>)}
      {xyz&&<><p>{row.coordinate_frame??'unknown'} · {row.units??'unknown'} · VISUALIZATION ONLY</p>{row.coordinate_frame?.includes('relative')&&<p>RELATIVE VISUALIZATION{row.coordinate_frame==='gpt_start_relative_visualization_mm'?' · ABSOLUTE START UNAVAILABLE':''}</p>}<select aria-label="Previous XYZ projection" value={plane} onChange={e=>setPlane(e.target.value as typeof plane)}><option>XY</option><option>XZ</option><option>YZ</option></select></>}
      {points.length>0&&<svg viewBox="0 0 280 280" role="img" aria-label="Model raw geometry viewer">{paths.map((run,i)=><g key={i}><polyline points={run.map(point).join(' ')} stroke="#c52d3e" strokeWidth="2" fill="none"/>{run.length===1&&<circle cx={Number(point(run[0]).split(',')[0])} cy={Number(point(run[0]).split(',')[1])} r="3" fill="#c52d3e"/>}</g>)}</svg>}
      {!row.states.OUTPUT_RENDERABLE&&<p>렌더링 가능한 데이터 없음 · 저장된 오류/증거 상태를 확인하세요.</p>}
      <small>결과 표시로 승인·검증·로봇 재생 권한이 부여되지 않습니다.</small>
    </>}
  </details>;
}
