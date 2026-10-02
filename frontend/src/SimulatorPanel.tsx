import { useEffect, useState } from 'react';
import { api, safePreviewReason } from './api';
import { Icon } from './components/Icon';
import { StatusBadge, statusTone } from './components/StatusBadge';
import { SimulatorViewport } from './components/SimulatorViewport';
import type { SimulatorController } from './useSimulator';
import type { VLASummary, PreviewCapabilities } from './types';

const reasons:Record<string,string>={
  CURRENT_PREVIEW_LAUNCHER_NOT_CONFIGURED:'Isaac launcher 설정이 필요합니다. Backend 설정 후 재시작하세요.',
  CURRENT_PREVIEW_LAUNCHER_INVALID:'Isaac launcher 설정을 확인하세요.',
  CURRENT_PREVIEW_CONFIGURATION_INVALID:'현재 미리보기 설정을 확인하세요.',
  CURRENT_PREVIEW_ASSET_MISSING:'현재 샘플의 시뮬레이터 source/assets가 준비되지 않았습니다.',
  CURRENT_PREVIEW_ARTIFACT_INVALID:'현재 VLA artifact 또는 승인 증거가 변경됐습니다.',
  SIMULATOR_STP_ROBOT_PREFLIGHT_REQUIRED:'로봇 준비 확인을 먼저 눌러주세요. 모델이나 Isaac은 실행하지 않습니다.',
  SIMULATOR2_ROBOT_PREFLIGHT_REQUIRED:'로봇 준비 확인을 먼저 눌러주세요. 모델이나 Isaac은 실행하지 않습니다.',
  SIMULATOR_STP_H5_MISSING:'현재 샘플의 H5를 찾을 수 없습니다.',SIMULATOR_STP_OBJ_MISSING:'현재 샘플의 OBJ를 찾을 수 없습니다.',
  SIMULATOR_STP_IK_FAIL:'로봇 자세 확인에 실패했습니다. Path Preview는 별도로 확인하세요.',
  SIMULATOR_STP_SAMPLE_UNSUPPORTED:'현재 샘플의 native preview 지원을 확인할 수 없습니다.',
  SIMULATOR_STP_FRAME_MISMATCH:'현재 예측과 H5 좌표계가 일치하지 않습니다.',
};
const friendly=(code:string)=>reasons[code]??(code.endsWith('_UNVALIDATED_SCENE')?'시뮬레이션 배치이며 실제 작업셀 검증 결과가 아닙니다.':code.endsWith('_CAPTURE_WARNING')?'캡처 경고입니다. 재생 결과는 별도로 확인하세요.':'준비 또는 실행 증거를 확인하세요.');
const runtimeLabels:Record<string,string>={STOPPED:'미리보기 대기',STARTING:'시뮬레이터 창을 준비하고 있습니다',RUNNING_PREVIEW:'현재 경로를 표시하고 있습니다',READY:'화면 확인 가능',FAILED:'미리보기 실패',OFFLINE:'Backend 연결 확인 필요',RUNNING_SAMPLE:'이전 샘플 재생 중'};

export function SimulatorPanel({simulator,onConsole,onPlan,vla,jobId}:{simulator:SimulatorController;onConsole:()=>void;onPlan:()=>void;vla?:VLASummary|null;jobId?:string}) {
  const {status,online,busy,error,act}=simulator;
  const current=status?.current_preview;
  const replayState=online?status?.state??'STOPPED':'OFFLINE';
  const state=online?current?.state??replayState:'OFFLINE';
  const [capabilities,setCapabilities]=useState<{jobId:string;artifactId:string;value:PreviewCapabilities}|null>(null);
  useEffect(()=>{
    let active=true;setCapabilities(null);
    if(jobId&&vla)void api.previewCapabilities(jobId).then(value=>{if(active)setCapabilities({jobId,artifactId:vla.artifact_id,value});}).catch(()=>{});
    return()=>{active=false;};
  },[jobId,vla?.artifact_id]);
  const support=capabilities&&capabilities.jobId===jobId&&capabilities.artifactId===vla?.artifact_id&&capabilities.value.sample_id===vla?.sample_id?capabilities.value:null;
  const backend=support?.backend??current?.backend??status?.backend??'legacy';
  const canPreview=online&&!busy&&current?.configured===true&&!!jobId&&!!vla&&['STOPPED','FAILED','READY'].includes(current.state)&&['STOPPED','FAILED'].includes(replayState);
  const canPath=canPreview&&support?.path_preview_ready===true;
  const canRobot=canPreview&&support?.robot_preview_ready===true&&(current?.robot_configuration?.configured??current?.configured)===true;
  const canPreflight=online&&!busy&&!!jobId&&!!vla&&support?.robot_preflight_available===true&&['STOPPED','FAILED'].includes(replayState)&&['STOPPED','FAILED','READY'].includes(current?.state??'STOPPED');
  const latest=current?.latest;
  const boundLatest=latest&&latest.job_id===jobId&&latest.artifact_id===vla?.artifact_id?latest:null;
  const pathSeen=boundLatest?.kind==='path'&&boundLatest.status==='SUCCEEDED';
  const robotSeen=boundLatest?.kind==='robot'&&boundLatest.status==='SUCCEEDED';
  const running=['STARTING','RUNNING_PREVIEW'].includes(state);
  const recommended=running||robotSeen?'stop':pathSeen?'robot':'path';
  const canStop=online&&!busy&&status?.can_stop===true;
  const commonReason=!online?'Backend 연결을 확인하세요.':!vla?'Guided VLA 3D prediction이 준비되면 시작할 수 있습니다.':busy||running?'현재 요청이 끝날 때까지 기다려 주세요.':!['STOPPED','FAILED'].includes(replayState)?'이전 재생 창을 중지한 뒤 현재 미리보기를 시작하세요.':current?.configured!==true?'Current Preview 설정이 필요합니다. 아래 설정 상태를 확인하세요.':!support?'현재 샘플의 지원 상태를 확인하고 있습니다.':'';
  const supportCodes=[...new Set([...(support?.warnings??[]),...(support?.configuration_codes??[]),...(support?.robot_reason_code?[support.robot_reason_code]:[])])].map(safePreviewReason).filter(Boolean);
  const replayErrors=status?.existing_replay?.errors??[...(status?.configuration_errors??[]),...(status?.sample_configuration_errors??[])];
  return <section className="simulator-panel" aria-labelledby="simulator-heading">
    <div className="section-heading"><div><span className="utility-label">03 / CURRENT VLA PREVIEW</span><h2 id="simulator-heading">시뮬레이션 <span className="heading-detail">Isaac Sim</span></h2></div><Icon name="robot" size={25}/></div>
    <div className="current-vla-gate" data-testid="current-vla-gate">
      <strong>{vla?'VLA Prediction Ready':'Guided VLA 3D prediction 필요'}</strong>
      <p>{vla?`${vla.sample_id} · 현재 작업의 3D prediction`:'Dataset 선택 → Segment 마스크 검토·승인 → Trajectory3 2D guidance → Guided VLA 순서로 준비하세요.'}</p>
      {!vla&&<button className="button secondary full-width" onClick={onPlan}>경로 계획으로 이동<Icon name="arrow" size={16}/></button>}
      <p data-testid="simulator-backend">Simulator: {backend==='dataset_stp'?'Dataset Simulator STP':backend==='dataset_v2'?'Dataset Simulator v2':'Legacy Simulator'}</p>
      {backend==='dataset_stp'&&<p data-testid="simulator-cad-source">Layout: STP Reference Environment<br/>Workpiece CAD: Exact Sample OBJ</p>}
      {vla&&<p data-testid="source-playback-count">VLA source trajectory: {support?.source_point_count??vla.point_count??9} points<br/>Simulator playback trajectory: {support?.playback_point_count??'준비 확인 대기'}{support?.playback_point_count!=null?' points · Simulator playback interpolation':''}</p>}
      <p className="simulator-order" data-testid="simulator-order">권장 순서: 1. 경로 보기 → 2. 로봇 준비 확인 및 미리보기 → 3. 필요 시 중지</p>
      {boundLatest&&['RUNNING_PREVIEW','READY'].includes(state)&&<button className="button secondary full-width" onClick={()=>document.getElementById('simulator-current-viewport')?.scrollIntoView({block:'center'})}>시뮬레이터 화면으로 이동<Icon name="arrow" size={16}/></button>}
      <ol className="preview-actions">
        <li className={recommended==='path'?'recommended':''}><strong>Step 1. 예측 경로 확인</strong><p>현재 VLA 원본 XYZ 경로를 3D scene에서 확인합니다. 로봇은 움직이지 않습니다.</p>
          <button className={`button ${recommended==='path'?'primary':'secondary'} full-width`} data-testid="current-vla-path-preview" disabled={!canPath} onClick={()=>void act(()=>api.previewCurrentVLA(jobId!,'path'))}>현재 VLA 경로 보기 · Path Preview<Icon name="path" size={16}/></button>
          {!canPath&&<small>{commonReason||'현재 샘플의 경로/자산 확인이 필요합니다.'}</small>}
        </li>
        <li className={recommended==='robot'?'recommended':''}><strong>Step 2. 로봇 자세와 재생 확인</strong><p>시뮬레이터 정책의 자세와 derived playback을 사용합니다. VLA는 방향을 예측하지 않습니다.</p>
          {['dataset_v2','dataset_stp'].includes(backend)&&support&&!support.robot_preview_ready&&<>
            <button className={`button ${recommended==='robot'?'primary':'secondary'} full-width`} data-testid="simulator2-preflight" disabled={!canPreflight} onClick={()=>void act(async()=>{const value=await api.simulator2Preflight(jobId!);setCapabilities({jobId:jobId!,artifactId:vla!.artifact_id,value});return api.simulatorStatus();})}>로봇 준비 확인 · Offline<Icon name="check" size={16}/></button>
            <small>필요할 때 한 번 확인합니다. 모델·Isaac 실행 없음.</small>
          </>}
          <button className={`button ${recommended==='robot'&&canRobot?'primary':'secondary'} full-width`} data-testid="current-vla-preview" disabled={!canRobot} onClick={()=>void act(()=>api.previewCurrentVLA(jobId!))}>VLA 로봇 미리보기 · Robot Preview<Icon name="play" size={16}/></button>
          {!canRobot&&<small>{commonReason||(!support?.robot_preview_ready?'로봇 준비 확인이 필요합니다. 현재 샘플의 IK/FK 통과 후 사용할 수 있습니다.':'로봇용 launcher/assets 설정을 확인하세요.')}</small>}
        </li>
        <li className={recommended==='stop'?'recommended':''}><strong>Step 3. 필요 시 중지</strong><p>확인이 끝나면 이 작업에서 연 시뮬레이터 창을 닫습니다.</p>
          <button className={`button ${recommended==='stop'?'primary':'secondary'} full-width danger-hover`} data-testid="current-preview-stop" disabled={!canStop} onClick={()=>void act(api.stopSimulator)}>시뮬레이터 중지<Icon name="stop" size={15}/></button>
        </li>
      </ol>
      <div className={`runtime-status tone-${statusTone(state)}`}><div><span className="field-label">{runtimeLabels[state]??'상태 확인 중'}</span><StatusBadge tone={statusTone(state)} testId="simulator-state">{state}</StatusBadge></div></div>
      <p data-testid="current-preview-support">{support?.path_preview_ready?'Path Preview Ready':'Path Preview Pending'} · {support?.robot_preview_ready?'Robot Preview Ready':'Robot Preview Pending'}</p>
      <p data-testid="current-preview-configuration">Current Preview 설정: {current?.configured?'준비됨':'설정 필요'}</p>
      {current&&current.configured===undefined&&<p className="error-text">Backend를 재시작한 후 Current Preview 설정을 확인하세요.</p>}
      {(current?.configuration_codes??[]).map(code=><p className="error-text" key={code}>{friendly(code)} <small>{safePreviewReason(code)}</small></p>)}
      {current?.robot_configuration?.configured===false&&(current.robot_configuration.configuration_codes??[]).map(code=><p className="error-text" key={code}>{friendly(code)} <small>{safePreviewReason(code)}</small></p>)}
      {vla&&current&&<p data-testid="current-preview-status">Current preview: {current.state} {boundLatest?.status}<br/>{boundLatest?`${boundLatest.kind==='path'?'Path Preview':'Robot Preview'} · ${boundLatest.sample_id}`:current.can_stop?'다른 작업의 창이 열려 있습니다.':''}</p>}
      {boundLatest?.playback_status&&<p data-testid="current-preview-diagnostics">Playback: {boundLatest.playback_status}<br/>Capture: {boundLatest.capture_status}{(boundLatest.capture_warning_codes??[]).map(safePreviewReason).filter(Boolean).map(code=><span key={code}><br/>{code}</span>)}{['PARTIAL_FAILED','FAILED'].includes(boundLatest.capture_status??'')&&<span><br/>캡처 경고 · 재생 결과는 별도로 확인하세요.</span>}</p>}
      {supportCodes.map(code=><p data-testid="current-preview-reason" className="simulator-message" key={code}>{friendly(code)} <small>{code}</small></p>)}
      <SimulatorViewport jobId={jobId} vla={vla} current={current} online={online}/>
      <div className="scope-callout"><strong>Preview / Simulation only</strong><p>Simulator Fixture Pending · 실제 로봇 실행 비활성</p><small>원본 9 XYZ 보존 · orientation_source={support?.orientation_source??'simulator policy'} · vla_orientation=false<br/>fixture_ready=false · validated_simulation=false · physical_robot_executable=false</small></div>
      <button className="button secondary full-width" data-testid="current-vla-sim" disabled>실제 로봇 실행 · 비활성</button>
      <details className="preview-glossary"><summary>단계별 결과 구분</summary><dl><dt>YOLO</dt><dd>객체 검출 · Canvas 보조 표시</dd><dt>Segment</dt><dd>2D 마스크 검출 · 사람이 F mask 승인</dd><dt>Trajectory3 / Rough</dt><dd>2D guidance · 작업 지시의 경로 계획</dd><dt>Guided VLA</dt><dd>원본 9 XYZ · 3D prediction</dd><dt>Simulator</dt><dd>Path / Robot Preview · 시뮬레이션 정책의 자세</dd></dl></details>
    </div>
    {!online&&<p className="simulator-message">Backend 연결을 확인하세요.</p>}
    {(error||current?.error)&&<div className="inline-error" role="alert"><Icon name="alert" size={17}/><p>{error||current?.error}</p></div>}
    <button className="text-button console-link" onClick={onConsole}><Icon name="command" size={16}/>Console에서 로그 확인<Icon name="arrow" size={14}/></button>
    {backend==='legacy'&&<details className="legacy-replay" data-testid="legacy-replay"><summary>이전 샘플 재생 · 고급</summary>
      <p>현재 작업의 VLA preview와 독립된 이전 기능입니다.</p><p>샘플: {status?.sample_id??'미설정'}</p>
      <button className="button secondary full-width" disabled={!online||busy||!status?.can_start} onClick={()=>void act(api.startSimulator)}>시뮬레이터 시작</button>
      <button className="button secondary full-width" disabled={!online||busy||!status?.can_run_sample} onClick={()=>void act(api.runSimulatorSample)}>기존 용접 샘플 실행</button>
      <p data-testid="simulator-latest">{status?.latest_sample?.status??'이전 재생 기록 없음'}</p>
      {status?.error&&<p role="alert">{status.error}</p>}
      {replayErrors.length>0&&<details><summary>실행 환경 설정 필요</summary><ul>{replayErrors.map(message=><li key={message}>{message}</li>)}</ul></details>}
      {status?.configuration_diagnostics&&<details><summary>이전 재생 환경 진단</summary><p>{status.configuration_diagnostics.isaac_import_check?.message}</p></details>}
    </details>}
  </section>;
}
