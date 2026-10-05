import {useEffect,useRef,useState} from 'react';
import {api} from '../api';
import type {PreviewFrames,SimulatorStatus,VLASummary} from '../types';

export function SimulatorViewport({jobId,vla,current,online}:{jobId?:string;vla?:VLASummary|null;current:SimulatorStatus['current_preview'];online:boolean}) {
  const [gallery,setGallery]=useState<PreviewFrames|null>(null);
  const [selected,setSelected]=useState('path_detail');
  const [failed,setFailed]=useState('');
  const [expanded,setExpanded]=useState(false);
  const [streamFailed,setStreamFailed]=useState(false);
  const [streamLoaded,setStreamLoaded]=useState(false);
  const [connectionId,setConnectionId]=useState(()=>crypto.randomUUID());
  const userSelected=useRef(false);
  const dialog=useRef<HTMLDialogElement>(null);
  const latest=current?.latest;
  const active=online&&!!jobId&&!!vla&&latest?.job_id===jobId&&latest?.artifact_id===vla.artifact_id&&
    !!latest.request_id&&!!latest.session_id&&['RUNNING_PREVIEW','READY'].includes(current?.state??'');
  useEffect(()=>{
    let alive=true;let timer:number;
    setGallery(null);setFailed('');setExpanded(false);setSelected('path_detail');
    setStreamFailed(false);setStreamLoaded(false);userSelected.current=false;
    setConnectionId(crypto.randomUUID());
    if(!active||!jobId||!vla)return;
    const poll=async()=>{
      try {
        const value=await api.previewFrames(jobId,vla.artifact_id);
        if(alive&&value.job_id===jobId&&value.artifact_id===vla.artifact_id&&value.request_id===latest?.request_id&&value.session_id===latest?.session_id){
          setGallery(value);setFailed('');
          if(value.live?.available&&!userSelected.current){setSelected('live');userSelected.current=true;}
          if(!value.live?.available)setSelected(previous=>previous==='live'?'path_detail':previous);
        }
        else if(alive)setGallery(null);
      } catch {if(alive){setGallery(null);setFailed('capture-read-failed');setExpanded(false);}}
      if(alive)timer=window.setTimeout(poll,3000);
    };
    void poll();return()=>{alive=false;window.clearTimeout(timer);};
  },[active,jobId,vla?.artifact_id,latest?.request_id,latest?.session_id]);
  const bound=active&&gallery?.job_id===jobId&&gallery.artifact_id===vla?.artifact_id&&
    gallery.request_id===latest?.request_id&&gallery.session_id===latest?.session_id?gallery:null;
  const frame=bound?.frames.find(f=>f.name===selected)??bound?.frames.at(-1);
  // Same-origin fixed API route only, even if a malformed response arrives.
  const expected=frame&&bound?`/api/simulator/current-preview/frames/${bound.session_id}/${bound.request_id}/${frame.name}/${frame.sha256}.png?job_id=${jobId}&artifact_id=${vla?.artifact_id}`:null;
  const url=frame&&frame.url===expected&&/^\/api\/simulator\/current-preview\/frames\/[0-9a-f-]+\/[0-9a-f-]+\/(P0|P4|P8|path_detail)\/[0-9a-f]{64}\.png\?job_id=[0-9a-f-]+&artifact_id=[0-9a-f-]+$/.test(frame.url)?frame.url:null;
  const visible=!!url&&failed!==url;
  const liveExpected=bound?`/api/simulator/current-preview/live/${bound.session_id}/${bound.request_id}?job_id=${jobId}&artifact_id=${vla?.artifact_id}`:null;
  const liveUrl=bound?.live?.url===liveExpected&&liveExpected&&/^\/api\/simulator\/current-preview\/live\/[0-9a-f-]+\/[0-9a-f-]+\?job_id=[0-9a-f-]+&artifact_id=[0-9a-f-]+$/.test(liveExpected)?liveExpected:null;
  const liveAvailable=!!liveUrl&&bound?.live?.available===true&&latest?.kind==='robot';
  const liveSelected=selected==='live'&&liveAvailable&&!streamFailed;
  const liveState=!active?'OFFLINE':streamFailed?'OFFLINE':liveSelected?streamLoaded?bound?.live?.state??'CONNECTING':'CONNECTING':bound?.live?.state==='LIVE'?'PAUSED':bound?.live?.state??'OFFLINE';
  useEffect(()=>{if(visible&&expanded)dialog.current?.showModal();},[visible,expanded]);
  const title=latest?.kind==='robot'?'Robot Preview':'Path Preview';
  return <section id="simulator-current-viewport" className="simulator-viewport" data-testid="simulator-viewport" aria-label="시뮬레이터 화면">
    <div className="viewport-heading"><strong>시뮬레이터 화면</strong><span>{liveSelected?'Live Simulator View':'Latest capture'}</span></div>
    {latest?.kind==='robot'&&<div data-testid="simulator-live-state" className={`viewport-live-status ${liveState==='LIVE'?'live':''}`}>{liveState==='LIVE'?'● ':''}{liveState}{liveState==='LIVE'?bound?.live?.fps?` · ${bound.live.fps} FPS`:` · 목표 ${bound?.live?.target_fps||8} FPS`:''}</div>}
    <p>{active?title:'현재 미리보기'} · {liveSelected?'Isaac viewport MJPEG · 최대 8 FPS':'최신 캡처 이미지 / 실시간 영상 아님'}</p>
    {active&&<div className="viewport-frames" aria-label="캡처 시점">
      <button aria-pressed={liveSelected} disabled={!liveAvailable} onClick={()=>{userSelected.current=true;setSelected('live');setStreamFailed(false);setStreamLoaded(false);setConnectionId(crypto.randomUUID());}}>실시간</button>
      {bound?.frames.map(f=><button key={f.name} aria-pressed={!liveSelected&&frame?.name===f.name} onClick={()=>{userSelected.current=true;setSelected(f.name);setFailed('');setExpanded(false);}}>{f.name==='path_detail'?'경로 상세':f.name}</button>)}
    </div>}
    {liveSelected?<img key={connectionId} className="viewport-live-image" data-testid="simulator-live-image" src={`${liveUrl}&connection_id=${connectionId}`} alt="Robot Preview Isaac Sim Live View"
      onLoad={()=>setStreamLoaded(true)} onError={()=>{setStreamFailed(true);setSelected('path_detail');setStreamLoaded(false);}}/>:visible?<>
      <button className="viewport-image-button" aria-label="시뮬레이터 캡처 크게 보기" onClick={()=>setExpanded(true)}>
        <img key={url} src={url!} alt={`${title} 최신 캡처 · ${frame!.name}`} onError={()=>{setFailed(url!);setExpanded(false);}} />
      </button>
      <small>{frame!.name==='path_detail'?'전체 경로 상세':`${frame!.name} 시점`} · {new Date(frame!.captured_at).toLocaleTimeString()} 캡처</small>
    </>:<div className="viewport-empty" role="status">{!active?'Path 또는 Robot Preview를 시작하면 현재 작업의 화면이 표시됩니다.':bound?.reason_code==='CURRENT_PREVIEW_FRAME_UNAVAILABLE'||failed?'캡처 화면을 읽을 수 없습니다. 재생 상태와 Console을 확인하세요.':'현재 미리보기의 캡처를 기다리고 있습니다.'}</div>}
    {streamFailed&&active&&<small role="status">Live stream 연결을 확인하세요. 정지 캡처와 Robot 재생 상태는 별도입니다.</small>}
    {liveSelected&&bound?.live?.warning&&<small role="status">일부 frame을 건너뛰고 있습니다. Robot Preview는 계속 재생합니다.</small>}
    {visible&&!liveSelected&&expanded&&<dialog ref={dialog} className="viewport-expanded" aria-label="시뮬레이터 캡처 확대" onCancel={()=>setExpanded(false)}>
      <button className="button secondary" autoFocus onClick={()=>setExpanded(false)}>캡처 닫기</button>
      <img src={url!} alt={`${title} 최신 캡처 확대`} onError={()=>{setFailed(url!);setExpanded(false);}} />
      <small>{title} · 최신 캡처 / 실시간 영상 아님</small>
    </dialog>}
  </section>;
}
