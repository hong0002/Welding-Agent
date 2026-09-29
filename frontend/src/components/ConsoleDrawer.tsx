import type { SimulatorLogs, SimulatorState } from '../types';
import { Icon } from './Icon';

export function ConsoleDrawer({ logs, state, online, error, open, onToggle }: {
  logs: SimulatorLogs['entries']; state: SimulatorState | null; online: boolean; error: string;
  open: boolean; onToggle: () => void;
}) {
  const failed = state === 'FAILED' || Boolean(error);
  return <section id="console" className={`console-drawer ${open ? 'is-open' : ''} ${failed ? 'has-error' : ''}`} aria-label="Runtime console">
    <button className="console-toggle" aria-expanded={open} aria-controls="console-content" onClick={onToggle} aria-label={open ? 'Console 닫기' : 'Console 열기'}>
      <Icon name="command" size={17} /><strong>Console</strong><span className="console-count">{logs.length}</span>
      <span className="console-description">Simulator logs · latest 200</span>
      {failed && <span className="console-alert"><Icon name="alert" size={14} />실행 오류 · 로그 확인</span>}
      <span className={`drawer-chevron ${open ? 'expanded' : ''}`}><Icon name="chevron" size={16} /></span>
    </button>
    <div id="console-content" hidden={!open} className="console-content">
      <div className="console-caption"><span>{online ? 'Captured stdout / stderr' : 'Backend 연결 확인 필요'}</span><span>LOCAL RUNTIME</span></div>
      <pre aria-label="Simulator logs">{logs.length ? logs.map((entry) => `[${entry.source}] ${entry.text}`).join('\n') : '실행 후 로그가 표시됩니다.'}</pre>
    </div>
  </section>;
}
