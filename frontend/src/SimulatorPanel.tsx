import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { SimulatorLogs, SimulatorState, SimulatorStatus } from './types';

export function SimulatorPanel({ onState }: { onState: (state: SimulatorState | null) => void }) {
  const [status, setStatus] = useState<SimulatorStatus | null>(null);
  const [logs, setLogs] = useState<SimulatorLogs['entries']>([]);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const revision = useRef(0);
  const pending = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    let active = true;
    let timer: number;
    const poll = async () => {
      const current = revision.current;
      if (!pending.current) {
        try {
          const [next, output] = await Promise.all([api.simulatorStatus(), api.simulatorLogs()]);
          if (active && current === revision.current) {
            setStatus(next); setLogs(output.entries); setOnline(true); onState(next.state);
          }
        } catch {
          if (active && current === revision.current) { setOnline(false); onState(null); }
        }
      }
      if (active) timer = window.setTimeout(poll, 1500);
    };
    void poll();
    return () => { active = false; alive.current = false; window.clearTimeout(timer); };
  }, [onState]);

  const act = async (action: () => Promise<SimulatorStatus>) => {
    if (pending.current) return;
    pending.current = true; revision.current += 1; setBusy(true); setError('');
    try {
      const next = await action();
      if (alive.current) { setStatus(next); setOnline(true); onState(next.state); }
    } catch (cause) {
      if (alive.current) setError(cause instanceof Error ? cause.message : 'Simulator 요청 실패');
    } finally {
      revision.current += 1; pending.current = false;
      if (alive.current) setBusy(false);
    }
  };

  return <section className="card simulator-card" aria-labelledby="simulator-heading">
    <div className="card-heading"><span className="section-index">04</span><h2 id="simulator-heading">Simulator</h2><span className={`status-pill ${online && status?.state === 'READY' ? 'success' : ''}`} data-testid="simulator-state">{online ? status?.state : 'OFFLINE'}</span></div>
    <p className="card-copy"><strong>Existing simulator sample</strong><br />기존 VLA prediction을 재생합니다. 현재 웹 preview trajectory와 아직 연결되지 않았습니다.</p>
    <p className="simulator-profile">샘플 <code>{status?.sample_id ?? '미설정'}</code>{status?.simulator_pid && <small> · PID {status.simulator_pid}</small>}</p>
    {status?.configuration_diagnostics && <details className="simulator-config"><summary>Isaac 환경 진단 · {status.configuration_diagnostics.isaac_import_check.status}</summary><p>Launcher: {status.configuration_diagnostics.isaac_launcher ?? '미설정'}</p><p>Prediction: {status.configuration_diagnostics.prediction_format}</p><p>{status.configuration_diagnostics.isaac_import_check.message}</p><p>Import 검사는 GUI 재생 성공을 보장하지 않습니다.</p></details>}
    {!online && <p className="simulator-message">Simulator 상태를 확인할 수 없습니다. Backend 연결을 확인하세요.</p>}
    {status && [...status.configuration_errors, ...status.sample_configuration_errors].length > 0 && <details className="simulator-config"><summary>실행 환경 설정 필요</summary><ul>{[...status.configuration_errors, ...status.sample_configuration_errors].map((message) => <li key={message}>{message}</li>)}</ul><p>프로젝트 .env 설정 후 backend를 재시작하세요. README의 Simulator 실행 절차를 참고하세요.</p></details>}
    <div className="simulator-buttons">
      <button className="button secondary" disabled={!online || busy || !status?.can_start} onClick={() => void act(api.startSimulator)}>Start Simulator</button>
      <button className="button secondary" disabled={!online || busy || !status?.can_stop} onClick={() => void act(api.stopSimulator)}>Stop Simulator</button>
      <button className="button generate-button full-width" disabled={!online || busy || !status?.can_run_sample} onClick={() => void act(api.runSimulatorSample)}>Run Existing Welding Sample</button>
    </div>
    {status?.state === 'STARTING' && <p className="simulator-message">시뮬레이터의 준비 신호를 기다리는 중입니다.</p>}
    {(error || status?.error) && <p className="simulator-error" role="alert">{error || status?.error}</p>}
    <div className="simulator-latest" data-testid="simulator-latest"><span>LATEST SAMPLE</span><strong>{status?.latest_sample?.status ?? '실행 기록 없음'}</strong>{status?.latest_sample?.request_id && <code>{status.latest_sample.request_id}</code>}{status?.latest_sample?.error && <p>{status.latest_sample.error}</p>}</div>
    <details className="simulator-output" open><summary>Simulator logs · 최근 200줄</summary><pre aria-label="Simulator logs">{logs.length ? logs.map((entry) => `[${entry.source}] ${entry.text}`).join('\n') : '실행 후 로그가 표시됩니다.'}</pre></details>
  </section>;
}
