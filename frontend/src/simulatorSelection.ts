import type {OutputRow} from './components/OutputBrowser';

/** Split invalid points without connecting independent source runs. */
export function finiteRuns(paths:number[][][],dimensions=3):number[][][]{
  const result:number[][][]=[];
  for(const path of paths){let run:number[][]=[];
    for(const p of path){if(Array.isArray(p)&&p.length===dimensions&&p.every(v=>typeof v==='number'&&Number.isFinite(v)))run.push(p);
      else if(run.length){result.push(run);run=[];}}
    if(run.length)result.push(run);
  }return result;
}
export const sourcePointCount=(row?:OutputRow|null)=>finiteRuns(row?.runs??[]).reduce((n,r)=>n+r.length,0);
export function currentModelOutput(row:OutputRow|undefined|null,jobId?:string,sampleId?:string):boolean{
  return !!jobId&&!!row&&!row.stale&&row.job_id===jobId&&(!sampleId||row.sample_id===sampleId)&&
    !['playback','simulator_source'].includes(row.stage)&&(row.dimensions===3||row.stage==='final')&&row.states.OUTPUT_RENDERABLE===true;
}
function priority(row:OutputRow):number{
  if(row.source==='vlm_final_gpt2')return row.stage==='final'||/\bfinal\b/i.test(row.label)?-2:-1;
  if(row.stage==='prediction')return 4;
  if(row.stage==='final'||/\bfinal\b/i.test(row.label))return 0;
  if(/corner/i.test(row.label))return 1;
  if(/derived/i.test(row.label))return 2;
  return 3;
}
/** Promotion, approval and cached preview readiness do not select visualization sources. */
export function preferredCurrentOutput(rows:OutputRow[],jobId?:string,sampleId?:string):OutputRow|undefined{
  return rows.map((row,index)=>({row,index})).filter(({row})=>currentModelOutput(row,jobId,sampleId)&&sourcePointCount(row)>=2)
    .sort((a,b)=>priority(a.row)-priority(b.row)||b.index-a.index)[0]?.row;
}
