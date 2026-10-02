import { useEffect, useState } from 'react';
import { api, safePreviewReason } from './api';
import { Icon } from './components/Icon';
import { StatusBadge, statusTone } from './components/StatusBadge';
import type { SimulatorController } from './useSimulator';
import type { VLASummary, PreviewCapabilities } from './types';

export function SimulatorPanel({ simulator, onConsole,vla,jobId }: { simulator: SimulatorController; onConsole: () => void;vla?:VLASummary|null;jobId?:string }) {
  const { status, online, busy, error, act } = simulator;
  const state = online ? status?.state ?? 'STOPPED' : 'OFFLINE';
  const check = status?.configuration_diagnostics?.isaac_import_check;
  const current=status?.current_preview;
  const [capabilities,setCapabilities]=useState<{jobId:string;artifactId:string;value:PreviewCapabilities}|null>(null);
  useEffect(()=>{
    let active=true;setCapabilities(null);
    if(jobId&&vla)void api.previewCapabilities(jobId).then(value=>{
      if(active)setCapabilities({jobId,artifactId:vla.artifact_id,value});
    }).catch(()=>{});
    return()=>{active=false;};
  },[jobId,vla?.artifact_id]);
  const support=capabilities&&capabilities.jobId===jobId&&capabilities.artifactId===vla?.artifact_id&&capabilities.value.sample_id===vla?.sample_id?capabilities.value:null;
  const canPreview=online&&!busy&&current?.configured===true&&!!jobId&&!!vla&&['STOPPED','FAILED','READY'].includes(current.state)&&['STOPPED','FAILED'].includes(state);
  const canPath=canPreview&&support?.path_preview_ready===true;
  const canRobot=canPreview&&support?.robot_preview_ready===true&&(current?.robot_configuration?.configured??current?.configured)===true;
  const supportCodes=[...new Set([...(support?.warnings??[]),...(support?.configuration_codes??[]),...(support?.robot_reason_code?[support.robot_reason_code]:[])])];
  const replayErrors=status?.existing_replay?.errors??[...(status?.configuration_errors??[]),...(status?.sample_configuration_errors??[])];
  return <section className="simulator-panel" aria-labelledby="simulator-heading">
    <div className="section-heading"><div><span className="utility-label">03 / SIMULATION</span><h2 id="simulator-heading">시뮬레이션 <span className="heading-detail">Isaac Sim</span></h2></div><Icon name="robot" size={25} /></div>
    {vla&&<div className="current-vla-gate" data-testid="current-vla-gate"><strong>VLA Prediction Ready</strong><p>{vla.sample_id} · {support?.family??'Policy 확인 중'}</p>
      <p data-testid="simulator-backend">Simulator: {(support?.backend??current?.backend)==='dataset_v2'?'Dataset Simulator v2':'Legacy Simulator'}</p>
      <p data-testid="source-playback-count">VLA source trajectory: {support?.source_point_count??vla.point_count??9} points<br/>
        Simulator playback trajectory: {support?.playback_point_count??'확인 대기'}{support?.playback_point_count!=null?' points · Simulator playback interpolation':''}</p>
      <p data-testid="current-preview-support">{support?.path_preview_ready?'Path Preview Ready':'Path Preview Pending'}<br/>{support?.robot_preview_ready?'Robot Preview Ready':'Robot Preview Pending'}</p>
      <p>Simulator Fixture Pending</p><small>fixture_ready=false · physical_robot_executable=false</small>
      {supportCodes.map(code=><p data-testid="current-preview-reason" key={code}>{safePreviewReason(code)||(code==='B_PR_TOOL_CLEARANCE_FAIL'?code:'')}</p>)}
      {support?.robot_preview_ready&&current?.robot_configuration?.configured===false&&current.robot_configuration.configuration_codes.map(code=><p className="error-text" key={code}>{safePreviewReason(code)}</p>)}
      <button className="button primary full-width" data-testid="current-vla-path-preview" disabled={!canPath} onClick={()=>void act(()=>api.previewCurrentVLA(jobId!,'path'))}>현재 VLA 경로 보기 · Path Preview</button>
      <button className="button secondary full-width" data-testid="current-vla-preview" disabled={!canRobot} onClick={()=>void act(()=>api.previewCurrentVLA(jobId!))}><Icon name="play" size={16}/>VLA 로봇 미리보기</button>
      {support?.backend==='dataset_v2'&&!support.robot_preview_ready&&<button className="button secondary full-width" data-testid="simulator2-preflight"
        disabled={!online||busy||!jobId||!vla||!support.robot_preflight_available||!['STOPPED','FAILED'].includes(state)||!['STOPPED','FAILED','READY'].includes(current?.state??'STOPPED')}
        onClick={()=>void act(async()=>{const value=await api.simulator2Preflight(jobId!);setCapabilities({jobId:jobId!,artifactId:vla!.artifact_id,value});return api.simulatorStatus();})}>Robot offline 확인 · Isaac 실행 없음</button>}
      <button className="button secondary full-width" data-testid="current-vla-sim" disabled>검증된 로봇 실행 · blocked</button>
      <p>UNVALIDATED FIXTURE · SIMULATION PREVIEW ONLY<br/>PHYSICAL EXECUTION DISABLED</p>
      {current&&<p data-testid="current-preview-status">Current preview: {current.state} {current.latest?.status}<br/>{current.latest?.sample_id} · {current.latest?.point_count??9} points<br/>{current.latest?.artifact_id}</p>}
      {current?.backend==='dataset_v2'&&current.latest?.playback_status&&<p data-testid="current-preview-diagnostics">
        Playback: {current.latest.playback_status}<br/>Capture: {current.latest.capture_status}
        {(current.latest.capture_warning_codes??[]).map(code=>safePreviewReason(code)).filter(Boolean).map(code=><span key={code}><br/>{code}</span>)}
        {['PARTIAL_FAILED','FAILED'].includes(current.latest.capture_status??'')&&<span><br/>스크린샷 진단 경고 · 재생 결과는 별도로 확인하세요.</span>}
      </p>}
      {current&&<p data-testid="current-preview-configuration">Current Preview 설정: {current.configured?'준비됨':'설정 필요'}</p>}
      {(current?.configuration_errors??[]).map((message,index)=><p className="error-text" key={index}>{current?.configuration_codes?.[index]} · {message}</p>)}
      {current&&current.configured===undefined&&<p className="error-text">Backend를 재시작한 후 Current Preview 설정을 확인하세요.</p>}
      {current?.error&&<p className="error-text" role="alert">{current.error}</p>}
      {current?.latest?.reason_code&&<p className={current.latest.reason_code==='SIMULATOR2_CAPTURE_WARNING'?'simulator-message':'error-text'}>{safePreviewReason(current.latest.reason_code)}</p>}
    </div>}
    <div className={`runtime-status tone-${statusTone(state)}`}>
      <span className="runtime-orbit" aria-hidden="true"><Icon name={state === 'FAILED' ? 'alert' : state === 'READY' ? 'check' : 'robot'} size={22} /></span>
      <div><span className="field-label">Simulator runtime</span><StatusBadge tone={statusTone(state)} testId="simulator-state">{state}</StatusBadge></div>
    </div>
    <dl className="runtime-profile"><div><dt>입력</dt><dd>Existing VLA prediction</dd></div><div><dt>샘플</dt><dd><code>{status?.sample_id ?? '미설정'}</code></dd></div>{status?.simulator_pid && <div><dt>Process</dt><dd><code>PID {status.simulator_pid}</code></dd></div>}</dl>
    <div className="simulator-buttons">
      <button className={`button full-width ${status?.can_start ? 'primary' : 'secondary'}`} disabled={!online || busy || !status?.can_start} onClick={() => void act(api.startSimulator)}><Icon name="play" size={16} />시뮬레이터 시작</button>
      <button className="button primary full-width" disabled={!online || busy || !status?.can_run_sample} onClick={() => void act(api.runSimulatorSample)}><Icon name="play" size={16} />기존 용접 샘플 실행</button>
      <button className="button secondary full-width danger-hover" disabled={!online || busy || !status?.can_stop} onClick={() => void act(api.stopSimulator)}><Icon name="stop" size={15} />시뮬레이터 중지</button>
    </div>
    {status?.state === 'STARTING' && <p className="simulator-message"><span className="spinner" />시뮬레이터의 준비 신호를 기다리는 중입니다.</p>}
    {!online && <p className="simulator-message">Simulator 상태를 확인할 수 없습니다. Backend 연결을 확인하세요.</p>}
    {(error || status?.error) && <div className="inline-error" role="alert"><Icon name="alert" size={17} /><p>{error || status?.error}</p></div>}
    <div className="simulator-latest" data-testid="simulator-latest"><span className="utility-label">최근 실행</span><StatusBadge tone={statusTone(status?.latest_sample?.status)}>{status?.latest_sample?.status ?? '실행 기록 없음'}</StatusBadge>{status?.latest_sample?.request_id && <code>{status.latest_sample.request_id}</code>}{status?.latest_sample?.error && <p className="error-text">{status.latest_sample.error}</p>}</div>
    <button className="text-button console-link" onClick={onConsole}><Icon name="command" size={16} />Console에서 로그 확인<Icon name="arrow" size={14} /></button>
    <div className="scope-callout simulator-scope"><span className="utility-label">EXISTING VLA SAMPLE</span><p>기존 샘플 재생은 별도 기능입니다.</p><small>현재 VLA preview는 현재 job의 9-point XYZ artifact를 사용합니다. 2D Canvas 경로는 로봇 입력이 아닙니다.</small></div>
    {status?.configuration_diagnostics && <details className="diagnostic-details"><summary>환경 상세 · Isaac 진단<Icon name="chevron" size={14} /></summary><p>Isaac import: <StatusBadge tone={statusTone(check?.status)}>{check?.status ?? 'not_run'}</StatusBadge></p><p>Launcher: <code>{status.configuration_diagnostics.isaac_launcher ?? '미설정'}</code></p><p>Prediction: {status.configuration_diagnostics.prediction_format}</p><p>{check?.message}</p><p>Import 검사는 GUI 재생 성공을 보장하지 않습니다.</p></details>}
    {replayErrors.length > 0 && <details className="diagnostic-details configuration-warning"><summary><Icon name="alert" size={15} />기존 샘플 재생 · 실행 환경 설정 필요<Icon name="chevron" size={14} /></summary><ul>{replayErrors.map((message) => <li key={message}>{message}</li>)}</ul><p>기존 샘플 재생용 설정입니다. Current Preview는 별도 설정을 검사합니다. 프로젝트 .env 설정 후 backend를 재시작하세요.</p></details>}
  </section>;
}
