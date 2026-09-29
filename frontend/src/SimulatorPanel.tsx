import { api } from './api';
import { Icon } from './components/Icon';
import { StatusBadge, statusTone } from './components/StatusBadge';
import type { SimulatorController } from './useSimulator';

export function SimulatorPanel({ simulator, onConsole }: { simulator: SimulatorController; onConsole: () => void }) {
  const { status, online, busy, error, act } = simulator;
  const state = online ? status?.state ?? 'STOPPED' : 'OFFLINE';
  const check = status?.configuration_diagnostics?.isaac_import_check;
  return <section className="simulator-panel" aria-labelledby="simulator-heading">
    <div className="section-heading"><div><span className="utility-label">03 / SIMULATION</span><h2 id="simulator-heading">시뮬레이션 <span className="heading-detail">Isaac Sim</span></h2></div><Icon name="robot" size={25} /></div>
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
    <div className="scope-callout simulator-scope"><span className="utility-label">EXISTING VLA SAMPLE</span><p>Preview path not connected</p><small>현재 웹 preview trajectory와 아직 연결되지 않았습니다.</small></div>
    {status?.configuration_diagnostics && <details className="diagnostic-details"><summary>환경 상세 · Isaac 진단<Icon name="chevron" size={14} /></summary><p>Isaac import: <StatusBadge tone={statusTone(check?.status)}>{check?.status ?? 'not_run'}</StatusBadge></p><p>Launcher: <code>{status.configuration_diagnostics.isaac_launcher ?? '미설정'}</code></p><p>Prediction: {status.configuration_diagnostics.prediction_format}</p><p>{check?.message}</p><p>Import 검사는 GUI 재생 성공을 보장하지 않습니다.</p></details>}
    {status && [...status.configuration_errors, ...status.sample_configuration_errors].length > 0 && <details className="diagnostic-details configuration-warning"><summary><Icon name="alert" size={15} />실행 환경 설정 필요<Icon name="chevron" size={14} /></summary><ul>{[...status.configuration_errors, ...status.sample_configuration_errors].map((message) => <li key={message}>{message}</li>)}</ul><p>프로젝트 .env 설정 후 backend를 재시작하세요. README의 Simulator 실행 절차를 참고하세요.</p></details>}
  </section>;
}
