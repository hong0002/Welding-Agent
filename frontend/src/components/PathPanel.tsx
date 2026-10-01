import type { Job, MaskRegion, Trajectory } from '../types';
import { Icon } from './Icon';

type Props = {
  native?: boolean;
  instructionReady: boolean; busy: boolean; validated: boolean;
  rough: Trajectory | null; final: Trajectory | null; validation: Job['validation'];
  regions: MaskRegion[]; skipRegions: number[];
  onGenerate: () => void; onDownload: () => void; onCommand: () => void;
  job?:Job|null;onMode?:(mode:'baseline_2d'|'native_3d')=>void;onGuided?:()=>void;
};

export function PathPanel({ native = false, instructionReady, busy, validated, rough, final, validation, regions, skipRegions, onGenerate, onDownload, onCommand,job,onMode,onGuided }: Props) {
  const spatial=job?.rough_mode==='native_3d';
  const selected = regions.filter((region) => !skipRegions.includes(region.region_id));
  const failed = validation?.valid === false;
  return <section className="path-panel">
    <div className="section-heading"><div><span className="utility-label">02 / PATH PLANNING</span><h2>경로 계획</h2></div><Icon name="path" size={22} /></div>
    <p className="panel-copy">{spatial?'NativeRough3D → Guided VLA · F 이미지 guidance와 승인 binary mask를 사용합니다.':native ? 'Native Rough2D baseline · 영역마다 독립된 경로를 표시합니다.' : 'Rough → Dummy VLA · 영역마다 독립된 경로를 생성하며 영역 사이를 연결하지 않습니다.'}</p>
    {job?.scene.sample_id&&<label className="rough-mode field-label">Rough mode<select aria-label="Rough mode" value={job.rough_mode} disabled={busy} onChange={e=>onMode?.(e.target.value as 'baseline_2d'|'native_3d')}><option value="native_3d">NativeRough3D · vlm_trajectory2</option><option value="baseline_2d">NativeRough2D · baseline</option></select></label>}
    <div className="selected-regions"><span className="field-label">선택된 영역 <strong>{selected.length}</strong></span><div>{selected.length ? selected.map((region) => <span className="region-chip" key={region.region_id}>R{region.region_id}</span>) : <span className="muted">마스크 확정 후 표시됩니다.</span>}</div></div>
    <button className={`button ${validated ? 'secondary' : 'primary'} full-width generate-button`} disabled={!instructionReady || busy} onClick={onGenerate}>용접 경로 생성<Icon name="arrow" /></button>
    {!instructionReady && <button className="text-button next-action" onClick={onCommand}>Assistant에서 작업 지시를 준비하세요<Icon name="arrow" size={14} /></button>}
    <div className="result-metrics"><div><span>ROUGH POINTS</span><strong>{rough?.segments.reduce((sum, segment) => sum + segment.points.length, 0) ?? '—'}<small> pts</small></strong></div><div><span>{spatial?'VLA XYZ POINTS':'FINAL POINTS'}</span><strong>{(spatial?job?.vla_prediction?.point_count:final?.segments.reduce((sum, segment) => sum + segment.points.length, 0)) ?? '—'}<small> pts</small></strong></div></div>
    <div className={`validation-result ${validated ? 'valid' : failed ? 'invalid' : ''}`} data-testid="validation-result"><span className="validation-icon"><Icon name={validated ? 'check' : failed ? 'alert' : 'crosshair'} size={18} /></span><div><strong>{validated ? 'Preview geometry 통과' : failed ? 'Preview validation 실패' : spatial && rough ? '2D guidance 준비 완료' : native && rough ? 'Native Rough 생성 완료' : 'Preview validation 대기'}</strong><small>{validated ? '영역 대응 · 좌표 · 마스크 근접성' : failed ? validation?.errors.join(' · ') : '경로를 생성하면 이미지 좌표를 검증합니다.'}</small></div></div>
    <div className="scope-callout"><span className="utility-label">2D PREVIEW ONLY</span><p>Image coordinates · px</p><small>실제 로봇 좌표가 아닙니다. 로봇 안전성 및 충돌 검증은 포함하지 않습니다.</small></div>
    {spatial&&<div className="guided-panel">
      {job?.rough3d&&<div className="reference-summary" data-testid="rough3d-summary"><strong>2D guidance ready · {job.rough3d.image_guidance_point_count} pts</strong><p>Reference 3D · {job.rough3d.reference_sample_id} · {job.rough3d.reference_point_count} pts</p><small>Retrieved teaching reference · query에 미등록 · VLA 요청에 포함하지 않음</small>{job.rough3d.reference_preview_url&&<details><summary>Native reference 3D 보기</summary><img className="reference-preview" src={job.rough3d.reference_preview_url} alt="미정합 retrieved teaching reference, 실행 불가" loading="lazy"/></details>}<p>cot_ko.md {job.rough3d.artifacts['iteration_001/cot_ko.md']?'✓':'—'} · vla_prompt.md {job.rough3d.artifacts['iteration_001/vla_prompt.md']?'✓':'—'}</p></div>}
      <button className="button primary full-width" data-testid="run-guided-vla" disabled={busy||!instructionReady||!job?.rough3d||Boolean(job.vla_prediction)} onClick={onGuided}>Guided VLA 실행<Icon name="arrow"/></button>
      <small>현재 검증된 conditioning contract: 승인 F mask만 전송. 서버 readiness를 확인한 뒤 한 번 요청합니다.</small>
      {job?.vla_prediction&&<div className="vla-summary" data-testid="vla-summary"><strong>VLA Prediction Ready</strong><p>{job.vla_prediction.sample_id} · {job.vla_prediction.split} · {job.vla_prediction.point_count} points</p><p>{job.vla_prediction.model??'모델 이름 미제공'} · {job.vla_prediction.coordinate_frame}</p><dl><div><dt>ADE</dt><dd>{job.vla_prediction.ade_mm.toFixed(3)} mm</dd></div><div><dt>FDE</dt><dd>{job.vla_prediction.fde_mm.toFixed(3)} mm</dd></div></dl><p>Artifact <code>{job.vla_prediction.artifact_id}</code></p><small>Simulation only · physical_robot_executable=false</small></div>}
    </div>}
    {validated && <button className="button secondary full-width download-button" onClick={onDownload}><Icon name="download" size={16} />Preview JSON 저장</button>}
  </section>;
}
