import type { Job, MaskRegion, Trajectory, GPTRetrievalMode } from '../types';
import { Icon } from './Icon';
import {ModelOutputSummary} from './ModelOutputSummary';
import {FinalPredictionView} from './FinalPredictionView';
import {OutputBrowser} from './OutputBrowser';
import {EndpointControl} from './EndpointControl';

type Props = {
  native?: boolean;
  instructionReady: boolean; busy: boolean; validated: boolean;
  rough: Trajectory | null; final: Trajectory | null; validation: Job['validation'];
  regions: MaskRegion[]; skipRegions: number[];
  onGenerate: () => void; onDownload: () => void; onCommand: () => void;
  job?:Job|null;onMode?:(mode:'baseline_2d'|'native_3d')=>void;onGuided?:()=>void;
  nativeOutput?:Job['native_output'];onShowNative?:()=>void;
  finalBackend?:string;
  finalSource?:string;
  finalRetrieval?:GPTRetrievalMode;
  onEndpoint?:(xyz:[number,number,number],source:'user_selected_3d'|'dataset_gt_endpoint')=>void;
};

export function PathPanel({ native = false, instructionReady, busy, validated, rough, final, validation, regions, skipRegions, onGenerate, onDownload, onCommand,job,onMode,onGuided,nativeOutput,onShowNative,finalBackend,finalSource,finalRetrieval,onEndpoint }: Props) {
  const spatial=job?.rough_mode==='native_3d';
  const gpt=finalBackend!==undefined?['gpt','gpt2'].includes(finalBackend):job?.vla_prediction?.provider==='gpt';
  const native2=finalSource==='vlm_final_gpt2';
  const predictor=gpt?'GPT Trajectory':'Guided VLA';
  const resultPredictor=job?.vla_prediction?.provider==='gpt'?'GPT Trajectory':'Guided VLA';
  const selected = regions.filter((region) => !skipRegions.includes(region.region_id));
  const failed = validation?.valid === false;
  const accepted=instructionReady&&nativeOutput?.status==='NATIVE_OUTPUT_VALIDATED'&&nativeOutput.validation.status==='PASS';
  const generated=nativeOutput?.native_output_generated;
  const hard=nativeOutput?.validation.issues.some(i=>i.classification==='HARD_INVALID');
  const modelPoints=nativeOutput?.model_output?.point_count??nativeOutput?.candidate?.segments.reduce((sum,s)=>sum+s.points_pixel.length,0);
  return <section className="path-panel">
    <div className="section-heading"><div><span className="utility-label">02 / PATH PLANNING</span><h2>경로 계획</h2></div><Icon name="path" size={22} /></div>
    {job&&<OutputBrowser job={job}/>}
    <p className="panel-copy">{spatial?`Trajectory3 → ${predictor} · 현재 승인 F mask와 작업 계보를 검증합니다.`:native ? 'Native Rough2D baseline · 영역마다 독립된 경로를 표시합니다.' : 'Rough → Dummy VLA · 영역마다 독립된 경로를 생성하며 영역 사이를 연결하지 않습니다.'}</p>
    {job?.scene.sample_id&&<label className="rough-mode field-label">Rough mode<select aria-label="Rough mode" value={job.rough_mode} disabled={busy} onChange={e=>onMode?.(e.target.value as 'baseline_2d'|'native_3d')}><option value="native_3d">NativeRough3D · vlm_trajectory2</option><option value="baseline_2d">NativeRough2D · baseline</option></select></label>}
    <div className="selected-regions"><span className="field-label">선택된 영역 <strong>{selected.length}</strong></span><div>{selected.length ? selected.map((region) => <span className="region-chip" key={region.region_id}>R{region.region_id}</span>) : <span className="muted">마스크 확정 후 표시됩니다.</span>}</div></div>
    <button className={`button ${validated ? 'secondary' : 'primary'} full-width generate-button`} disabled={!instructionReady || busy || Boolean(job?.trajectory_clarification)} onClick={onGenerate}>용접 경로 생성<Icon name="arrow" /></button>
    {nativeOutput&&<div className={`native-output-panel ${accepted?'accepted':'warning'}`} data-testid="native-output-panel">
      <span className="utility-label">MODEL OUTPUT</span>
      <strong>{generated?'✓ 경로 생성 완료':nativeOutput.status==='PARTIAL_NATIVE_OUTPUT'?'부분 결과 · 최종 경로 없음':'경로 결과 없음'}{modelPoints?` · ${modelPoints} points`:''}</strong>
      <code className="native-output-status" data-testid="native-output-status">{nativeOutput.status}</code>
      {job?.trajectory_clarification&&<div className="clarification-card" data-testid="path-clarification"><span className="utility-label">CLARIFICATION</span><strong>● 사용자 응답 대기</strong><p>{job.trajectory_clarification.question}</p><button className="text-button" onClick={onCommand}>Assistant에서 답하기<Icon name="arrow" size={14}/></button></div>}
      <span className="utility-label">VALIDATION</span>
      <strong>{accepted?'✓ 검증 통과':hard?'필수 계약 검사 실패 · downstream 차단':generated?'⚠ 모델 생성 경로 · 검증 미통과':'최종 경로 검증 대기'}</strong>
      <ModelOutputSummary output={nativeOutput} model="TRAJECTORY3" downstreamAllowed={accepted}/>
      {nativeOutput.validation.issues.length>0&&<ul>{nativeOutput.validation.issues.map(i=><li key={i.code}>{i.message}</li>)}</ul>}
      <span className="utility-label">{predictor} · Final 3D Trajectory</span>
      <p data-testid="native-vla-policy">{accepted?'검증 통과 · 명시적 실행 가능':'Blocked by validation · 검증 전에는 실행하지 않음'}</p>
      {(nativeOutput.model_output?.displayable&&nativeOutput.model_output.overlay_allowed||nativeOutput.candidate)&&<button className="button secondary full-width" data-testid="show-native-output" onClick={onShowNative}>원본 모델 경로 보기<Icon name="path" size={16}/></button>}
      {Object.keys(nativeOutput.artifacts).length>0&&<details><summary>Native artifact summary</summary><ul className="native-artifact-list">{Object.entries(nativeOutput.artifacts).filter(([,ready])=>ready).map(([name])=><li key={name}>{name}</li>)}</ul></details>}
      {Object.entries(nativeOutput.preview_urls).map(([kind,url])=><details key={kind}><summary>Native {kind} 시각화 보기</summary><a href={url} target="_blank" rel="noreferrer"><img className="reference-preview" src={url} alt={`Native ${kind} 원본 artifact · 실행 불가`} loading="lazy"/></a></details>)}
      <small>원본 points·순서를 보존합니다. 검증 우회는 비활성화되어 있습니다.</small>
    </div>}
    {!instructionReady && <button className="text-button next-action" onClick={onCommand}>Assistant에서 작업 지시를 준비하세요<Icon name="arrow" size={14} /></button>}
    <div className="result-metrics"><div><span>{nativeOutput?'MODEL POINTS':'ROUGH POINTS'}</span><strong>{modelPoints??rough?.segments.reduce((sum, segment) => sum + segment.points.length, 0) ?? '—'}<small> pts</small></strong></div><div><span>{spatial?'FINAL XYZ POINTS':'FINAL POINTS'}</span><strong>{(spatial?job?.vla_prediction?.point_count:final?.segments.reduce((sum, segment) => sum + segment.points.length, 0)) ?? '—'}<small> pts</small></strong></div></div>
    {!nativeOutput&&<div className={`validation-result ${validated ? 'valid' : failed ? 'invalid' : ''}`} data-testid="validation-result"><span className="validation-icon"><Icon name={validated ? 'check' : failed ? 'alert' : 'crosshair'} size={18} /></span><div><strong>{validated ? 'Preview geometry 통과' : failed ? 'Preview validation 실패' : spatial && rough ? '2D guidance 준비 완료' : native && rough ? 'Native Rough 생성 완료' : 'Preview validation 대기'}</strong><small>{validated ? '영역 대응 · 좌표 · 마스크 근접성' : failed ? validation?.errors.join(' · ') : '경로를 생성하면 이미지 좌표를 검증합니다.'}</small></div></div>}
    <div className="scope-callout"><span className="utility-label">2D PREVIEW ONLY</span><p>Image coordinates · px</p><small>실제 로봇 좌표가 아닙니다. 로봇 안전성 및 충돌 검증은 포함하지 않습니다.</small></div>
    {(spatial||gpt||job?.raw_final_prediction)&&<div className="guided-panel">
      {job?.rough3d&&<div className="reference-summary" data-testid="rough3d-summary"><strong>2D guidance ready · {job.rough3d.image_guidance_point_count} pts</strong><p>Reference 3D · {job.rough3d.reference_sample_id} · {job.rough3d.reference_point_count} pts</p><small>Retrieved teaching reference · query에 미등록 · VLA 요청에 포함하지 않음</small>{job.rough3d.reference_preview_url&&<details><summary>Native reference 3D 보기</summary><img className="reference-preview" src={job.rough3d.reference_preview_url} alt="미정합 retrieved teaching reference, 실행 불가" loading="lazy"/></details>}<p>cot_ko.md {job.rough3d.artifacts['iteration_001/cot_ko.md']?'✓':'—'} · vla_prompt.md {job.rough3d.artifacts['iteration_001/vla_prompt.md']?'✓':'—'}</p></div>}
      <p data-testid="final-predictor-source">Predictor: {gpt?finalSource??'vlm_final_gpt':'Guided VLA'}</p>
      {native2&&job?.scene.sample_id==='B_PR_03_0001'&&onEndpoint&&<EndpointControl job={job} busy={busy} onApply={onEndpoint}/>}
      {gpt&&finalRetrieval&&<p data-testid="final-retrieval-mode">Retrieval: {finalRetrieval==='native'?'GPT2 Native':finalRetrieval==='none'?'None':finalRetrieval==='local'?'Local':'Segment2 Adapter'}{finalRetrieval==='none'?' · reference 없이 예측하여 정확도가 낮아질 수 있습니다.':''}</p>}
      <button className="button primary full-width" data-testid="run-guided-vla" disabled={busy||(gpt?!job?.scene.views||!(job.mask||job.raw_segment_output):!instructionReady||!job?.rough3d||Boolean(job.vla_prediction)||(Boolean(nativeOutput)&&!accepted))} onClick={onGuided}>{gpt?'GPT 최종 3D 궤적 예측':'Guided VLA 실행'}<Icon name="arrow"/></button>
      <small>{native2?'9-view RGB + native source label seam masks + 현재 지시 + H5 첫 XYZ start. Native retrieval → Rough → Corners → native prediction-only Final export. 웹 edited mask와 Trajectory3 XYZ는 전송하지 않습니다.':gpt?'9-view RGB + 사용 가능한 F/R/S4 마스크 (승인 여부와 별도) + 현재 지시 + 알려진 시작 XYZ. 선택된 retrieval 설정으로 GPT가 두 단계에서 예측합니다.':'현재 검증된 conditioning contract: 승인 F mask만 전송. 서버 readiness를 확인한 뒤 한 번 요청합니다.'}</small>
      {job?.vla_prediction&&<div className="vla-summary" data-testid="vla-summary"><strong>{resultPredictor} · Final 3D Trajectory</strong><p>Source: {job.vla_prediction.source??'guided_vla'}</p><p>{job.vla_prediction.sample_id} · {job.vla_prediction.split} · {job.vla_prediction.point_count} points</p><p>{job.vla_prediction.model??'모델 이름 미제공'} · {job.vla_prediction.coordinate_frame}</p>{job.vla_prediction.ade_mm!=null&&job.vla_prediction.fde_mm!=null?<dl><div><dt>ADE</dt><dd>{job.vla_prediction.ade_mm.toFixed(3)} mm</dd></div><div><dt>FDE</dt><dd>{job.vla_prediction.fde_mm.toFixed(3)} mm</dd></div></dl>:<p data-testid="prediction-only-evaluation">Prediction only · GT 평가 미실행</p>}<p>Artifact <code>{job.vla_prediction.artifact_id}</code></p><small>Simulation only · physical_robot_executable=false</small></div>}
      {job&&<FinalPredictionView job={job}/>}
    </div>}
    {validated && <button className="button secondary full-width download-button" onClick={onDownload}><Icon name="download" size={16} />Preview JSON 저장</button>}
  </section>;
}
