import type {AgentDecisionSummary} from '../agentDecision';
import {actionLabels,intentLabels,nextLabels,prerequisiteLabels,reasonLabels,stepLabels} from '../agentDecision';
const states={planned:'예정',running:'진행 중',completed:'완료',blocked:'준비 필요',clarification:'응답 대기'};
export function AgentDecisionCard({summary}:{summary:AgentDecisionSummary}) {
  return <section className={`agent-decision decision-${summary.status}`} data-testid="agent-decision-summary" data-status={summary.status} aria-label="AI 판단 요약" aria-live="polite">
    <header><strong>AI 판단 요약</strong><span>{states[summary.status]}</span></header>
    <p>{intentLabels[summary.intent]}</p>
    <dl><div><dt>선택 작업</dt><dd>{actionLabels[summary.selected_action]}</dd></div>
      <div><dt>현재 단계</dt><dd>{stepLabels[summary.current_step]}</dd></div>
      <div><dt>다음 단계</dt><dd>{nextLabels[summary.next_step]}</dd></div></dl>
    <details><summary>선택 이유와 준비 상태</summary><p>{reasonLabels[summary.reason_code]}</p>
      <code data-testid="decision-reason-code">{summary.reason_code}</code>
      <ul>{summary.prerequisites.map(p=><li key={p.key}>{p.ready?'✓':'○'} {prerequisiteLabels[p.key]}</li>)}</ul>
      {summary.view_count>0&&<small>{summary.view_count} views{summary.point_count>0?` · ${summary.point_count} points`:''}</small>}
    </details>
  </section>;
}
