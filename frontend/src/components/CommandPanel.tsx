import { RegionSelector } from '../RegionSelector';
import type { Job, MaskRegion } from '../types';
import { Icon } from './Icon';
import { StatusBadge } from './StatusBadge';

type Props = {
  instruction: string; busy: boolean; maskReady: boolean; instructionReady: boolean;
  job: Job | null; regions: MaskRegion[]; skipRegions: number[];
  onInstruction: (value: string) => void; onRegions: (ids: number[]) => void;
  onParse: () => void;
};

export function CommandPanel({ instruction, busy, maskReady, instructionReady, job, regions, skipRegions, onInstruction, onRegions, onParse }: Props) {
  return <section className="command-panel">
    <div className="section-heading"><div><span className="utility-label">01 / COMMAND</span><h2>작업 지시</h2></div><span className="quiet-tag">Dummy parser</span></div>
    <label htmlFor="instruction" className="field-label">용접 방향을 입력하세요</label>
    <textarea id="instruction" value={instruction} maxLength={2000} disabled={busy} onChange={(event) => onInstruction(event.target.value)} placeholder="왼쪽에서 오른쪽으로 용접해" />
    <div className="quick-directions" aria-label="Direction presets">
      <button disabled={busy} onClick={() => onInstruction('왼쪽에서 오른쪽으로 용접해')}>왼쪽 → 오른쪽</button>
      <button disabled={busy} onClick={() => onInstruction('오른쪽에서 왼쪽으로 용접해')}>오른쪽 → 왼쪽</button>
    </div>
    {maskReady ? <RegionSelector regions={regions} skipped={skipRegions} discarded={job?.mask?.discarded_component_count ?? 0} disabled={busy} onChange={onRegions} /> :
      <div className="panel-empty"><Icon name="layers" /><div><strong>영역 선택 대기</strong><p>캔버스에서 영역을 그리고 마스크를 확정하세요.</p></div></div>}
    <button className={`button ${instructionReady ? 'secondary' : 'primary'} full-width`} disabled={!maskReady || !instruction.trim() || busy || skipRegions.length === regions.length} onClick={onParse}>지시 분석<Icon name="arrow" size={16} /></button>
    <details className="structured-output">
      <summary><span>Structured output</span><StatusBadge tone={instructionReady ? 'success' : 'neutral'}>{instructionReady ? 'READY' : 'WAITING'}</StatusBadge><Icon name="chevron" size={14} /></summary>
      {instructionReady && job?.instruction ? <pre data-testid="parsed-instruction">{JSON.stringify(job.instruction.structured, null, 2)}</pre> : <p>{maskReady ? '명령을 분석하면 구조화된 결과가 표시됩니다.' : '마스크를 확정한 후 명령을 분석하세요.'}</p>}
    </details>
  </section>;
}
