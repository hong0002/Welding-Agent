import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { AssistantController } from '../useAssistant';
import type { Job } from '../types';
import { Icon } from './Icon';

export function AssistantPanel({ assistant, busy, maskDirty, requiresMaskConfirmation = false, manual, onManualToggle, clarification }: {
  assistant: AssistantController; busy: boolean; maskDirty: boolean; manual: ReactNode;
  requiresMaskConfirmation?: boolean;
  clarification?:Job['trajectory_clarification'];
  onManualToggle: (open: boolean) => void;
}) {
  const [draft, setDraft] = useState('');
  const transcript = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = transcript.current; if (node) node.scrollTop = node.scrollHeight;
  }, [assistant.messages, assistant.progress]);
  const submit = () => {
    if (busy || !assistant.canSend || !draft.trim()) return;
    const message = draft; setDraft(''); void assistant.send(message);
  };
  return <section className="assistant-panel" aria-label="Welding Assistant">
    <div className="assistant-heading"><div><span className="utility-label">WELDING ASSISTANT</span><h2>작업을 지시하세요</h2></div>
      <button className="text-button" disabled={busy} onClick={() => void assistant.reset()}>새 대화</button></div>
    <div className="agent-connection"><span className={`agent-light agent-${assistant.displayState.toLowerCase().replace(' ', '-')}`} />
      <span>GPT Agent</span><strong data-testid="agent-state">{assistant.displayState}</strong></div>
    {!assistant.canSend && <p className="agent-config-note">Agent 설정 후 채팅을 사용할 수 있습니다. 아래 수동 지시와 Path 기능은 바로 사용할 수 있습니다.</p>}
    <div className="agent-transcript" ref={transcript} role="log" aria-label="Assistant 대화" aria-live="polite">
      {!assistant.messages.length && <div className="assistant-welcome"><Icon name="command" size={23} /><strong>그린 영역에 지시를 더하세요.</strong>
        <p>“표시한 부분을 왼쪽에서 오른쪽으로 용접해”</p><span>영역 선택 · 방향 변경 · 경로 생성</span></div>}
      {assistant.messages.map((message, index) => <article key={index} className={`agent-message ${message.role}`}>
        <span className="utility-label">{message.role === 'user' ? 'YOU' : 'ASSISTANT'}</span><p>{message.text}</p></article>)}
      {assistant.progress.length > 0 && <ul className="agent-progress" aria-label="Agent 작업 진행">
        {assistant.progress.map((item) => <li key={item.call_id} data-testid="agent-tool-progress" className={item.success === false ? 'failed' : ''}>
          {item.success === undefined ? <span className="spinner" /> : <Icon name={item.success ? 'check' : 'alert'} size={13} />}<span>{item.label}</span></li>)}
      </ul>}
    </div>
    {clarification&&<div className="clarification-card" data-testid="trajectory-clarification" data-clarification-id={clarification.id} role="status">
      <span className="utility-label">CLARIFICATION · 사용자 응답 대기</span>
      <p>{clarification.question}</p>
      <div className="clarification-choices">{clarification.choices.map(answer=><button key={answer} className="button secondary"
        disabled={busy||!assistant.canSend||requiresMaskConfirmation}
        onClick={()=>void assistant.send(answer,clarification.id)}>{({'위에서 아래로':'위 → 아래','아래에서 위로':'아래 → 위','왼쪽에서 오른쪽으로':'왼쪽 → 오른쪽','오른쪽에서 왼쪽으로':'오른쪽 → 왼쪽'} as Record<string,string>)[answer]??answer}</button>)}</div>
      <small>채팅으로도 답할 수 있습니다. 현재 승인된 F 마스크로 Trajectory3만 실행합니다.</small>
    </div>}
    {assistant.warning && <p className="agent-warning" role="status">{assistant.warning}</p>}
    {assistant.error && <p className="agent-error" role="alert">{assistant.errorCode&&<><code data-testid="agent-reason-code">{assistant.errorCode}</code> · </>}{assistant.error}</p>}
    <form className="agent-composer" onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <label className="sr-only" htmlFor="agent-message">Assistant 메시지</label>
      <textarea id="agent-message" value={draft} maxLength={2000} rows={3} disabled={busy || !assistant.canSend}
        placeholder="용접 방향이나 제외할 영역을 알려주세요" onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); submit(); } }} />
      <div><span>{assistant.running ? '작업 진행 중…' : requiresMaskConfirmation ? 'Canvas에서 마스크 확정 후 전송' : maskDirty ? '전송 시 마스크 자동 확정' : 'Enter 전송 · Shift+Enter 줄바꿈'}</span>
        <button className="button primary" type="submit" aria-label="메시지 전송" disabled={busy || !assistant.canSend || !draft.trim()}><Icon name="arrow" size={16} /></button></div>
    </form>
    <details className="manual-fallback" onToggle={(event) => onManualToggle(event.currentTarget.open)}>
      <summary>수동 지시 / 디버그<Icon name="chevron" size={14} /></summary>{manual}
    </details>
  </section>;
}
