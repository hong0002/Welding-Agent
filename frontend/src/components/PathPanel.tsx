import type { Job, MaskRegion, Trajectory } from '../types';
import { Icon } from './Icon';

type Props = {
  instructionReady: boolean; busy: boolean; validated: boolean;
  rough: Trajectory | null; final: Trajectory | null; validation: Job['validation'];
  regions: MaskRegion[]; skipRegions: number[];
  onGenerate: () => void; onDownload: () => void; onCommand: () => void;
};

export function PathPanel({ instructionReady, busy, validated, rough, final, validation, regions, skipRegions, onGenerate, onDownload, onCommand }: Props) {
  const selected = regions.filter((region) => !skipRegions.includes(region.region_id));
  const failed = validation?.valid === false;
  return <section className="path-panel">
    <div className="section-heading"><div><span className="utility-label">02 / PATH PLANNING</span><h2>경로 계획</h2></div><Icon name="path" size={22} /></div>
    <p className="panel-copy">Rough → Dummy VLA · 영역마다 독립된 경로를 생성하며 영역 사이를 연결하지 않습니다.</p>
    <div className="selected-regions"><span className="field-label">선택된 영역 <strong>{selected.length}</strong></span><div>{selected.length ? selected.map((region) => <span className="region-chip" key={region.region_id}>R{region.region_id}</span>) : <span className="muted">마스크 확정 후 표시됩니다.</span>}</div></div>
    <button className={`button ${validated ? 'secondary' : 'primary'} full-width generate-button`} disabled={!instructionReady || busy} onClick={onGenerate}>용접 경로 생성<Icon name="arrow" /></button>
    {!instructionReady && <button className="text-button next-action" onClick={onCommand}>Assistant에서 작업 지시를 준비하세요<Icon name="arrow" size={14} /></button>}
    <div className="result-metrics"><div><span>ROUGH POINTS</span><strong>{rough?.segments.reduce((sum, segment) => sum + segment.points.length, 0) ?? '—'}<small> pts</small></strong></div><div><span>FINAL POINTS</span><strong>{final?.segments.reduce((sum, segment) => sum + segment.points.length, 0) ?? '—'}<small> pts</small></strong></div></div>
    <div className={`validation-result ${validated ? 'valid' : failed ? 'invalid' : ''}`} data-testid="validation-result"><span className="validation-icon"><Icon name={validated ? 'check' : failed ? 'alert' : 'crosshair'} size={18} /></span><div><strong>{validated ? 'Preview geometry 통과' : failed ? 'Preview validation 실패' : 'Preview validation 대기'}</strong><small>{validated ? '영역 대응 · 좌표 · 마스크 근접성' : failed ? validation?.errors.join(' · ') : '경로를 생성하면 이미지 좌표를 검증합니다.'}</small></div></div>
    <div className="scope-callout"><span className="utility-label">2D PREVIEW ONLY</span><p>Image coordinates · px</p><small>실제 로봇 좌표가 아닙니다. 로봇 안전성 및 충돌 검증은 포함하지 않습니다.</small></div>
    {validated && <button className="button secondary full-width download-button" onClick={onDownload}><Icon name="download" size={16} />Preview JSON 저장</button>}
  </section>;
}
