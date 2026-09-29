import { useEffect, useState } from 'react';
import { api } from './api';
import { MaskCanvas } from './MaskCanvas';
import { RegionSelector } from './RegionSelector';
import { SimulatorPanel } from './SimulatorPanel';
import { createDemoScene, exportBinaryMask } from './mask';
import type { Job, SimulatorState, State, Stroke } from './types';

const steps: { state: State; label: string }[] = [
  { state: 'SCENE_READY', label: 'RGB scene' }, { state: 'MASK_READY', label: '2D mask' },
  { state: 'INSTRUCTION_READY', label: 'Instruction' }, { state: 'ROUGH_PATH_READY', label: 'Rough path' },
  { state: 'VLA_REFINED', label: 'VLA refine' }, { state: 'VALIDATED', label: 'Validation' },
];

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, React.ReactNode> = {
    brush: <><path d="m14 4 6 6-8 8-6-6 8-8Z" /><path d="M6 12c-4 2-1 5-4 8 5 0 7-1 8-4" /></>,
    eraser: <><path d="m13 3 8 8-9 10H7l-5-5L13 3Z" /><path d="m7 11 8 8M12 21h10" /></>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6" /></>,
    undo: <><path d="M4 10h10a6 6 0 0 1 0 12M4 10l5-5M4 10l5 5" /></>,
    clear: <><path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7" /></>,
    arrow: <><path d="M4 12h16m-6-6 6 6-6 6" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    layers: <><path d="m12 3 10 6-10 6L2 9l10-6ZM2 13l10 6 10-6M2 17l10 6 10-6" /></>,
    image: <><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8" cy="8" r="1" /><path d="m3 17 6-6 4 4 3-3 5 5" /></>,
    download: <><path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4" /></>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name] ?? paths.layers}</svg>;
}

export default function App() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [simulatorState, setSimulatorState] = useState<SimulatorState | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [sceneName, setSceneName] = useState('');
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [history, setHistory] = useState<Stroke[][]>([]);
  const [tool, setTool] = useState<Stroke['tool']>('brush');
  const [brushSize, setBrushSize] = useState(28);
  const [opacity, setOpacity] = useState(0.45);
  const [maskDirty, setMaskDirty] = useState(true);
  const [instruction, setInstruction] = useState('왼쪽에서 오른쪽으로 용접해');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [showRough, setShowRough] = useState(true);
  const [showFinal, setShowFinal] = useState(true);
  const [skipRegions, setSkipRegions] = useState<number[]>([]);

  useEffect(() => {
    let active = true;
    const check = async () => {
      try { await api.health(); if (active) setConnected(true); }
      catch { if (active) setConnected(false); }
    };
    void check(); const timer = window.setInterval(check, 10_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const run = async (label: string, action: () => Promise<void>) => {
    setBusy(label); setError('');
    try { await action(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '요청을 처리하지 못했습니다.'); }
    finally { setBusy(''); }
  };
  const upload = async (file: Blob, name: string) => {
    if (file.size > 20 * 1024 * 1024) throw new Error('20 MiB 이하의 이미지를 업로드하세요.');
    const next = await api.upload(file, name);
    setJob(next); setSceneName(name); setStrokes([]); setHistory([]); setMaskDirty(true); setSkipRegions([]); setConnected(true);
  };
  const startStroke = (stroke: Stroke) => {
    setHistory((previous) => [...previous, strokes]); setStrokes((previous) => [...previous, stroke]); setMaskDirty(true);
  };
  const moveStroke = (point: number[]) => setStrokes((previous) => {
    const last = previous.at(-1); if (!last) return previous;
    return [...previous.slice(0, -1), { ...last, points: [...last.points, ...point] }];
  });
  const undo = () => {
    const previous = history.at(-1); if (!previous) return;
    setStrokes(previous); setHistory((values) => values.slice(0, -1)); setMaskDirty(true);
  };
  const clear = () => { setHistory((previous) => [...previous, strokes]); setStrokes([]); setMaskDirty(true); };
  const maskReady = Boolean(job?.schema_version === 2 && job.mask && !maskDirty);
  const regions = maskReady ? job?.mask?.regions ?? [] : [];
  const sameSelection = JSON.stringify([...(job?.instruction?.structured.skip_regions ?? [])].sort((a, b) => a - b)) === JSON.stringify(skipRegions);
  const instructionReady = maskReady && sameSelection && job?.instruction?.text === instruction.trim();
  const previewsCurrent = maskReady && instructionReady;
  const effectiveState = !job ? 'EMPTY' : maskDirty ? 'SCENE_READY' : !instructionReady ? 'MASK_READY' : job.state;
  const currentStep = steps.findIndex((step) => step.state === effectiveState);
  const final = previewsCurrent ? job?.final_trajectory ?? null : null;
  const rough = previewsCurrent ? job?.rough_trajectory ?? null : null;
  const validated = previewsCurrent && job?.state === 'VALIDATED' && job.validation?.valid;
  const selectedPercent = maskReady && job?.mask ? (100 * job.mask.selected_pixels / (job.scene.width * job.scene.height)).toFixed(2) : null;

  const downloadPlan = () => {
    if (!job || !validated) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(job, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `preview-${job.id}.json`; anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return <div className="app-shell">
    <aside className="rail" aria-label="Workspace identity">
      <div className="brand-symbol"><span /> <span /> <span /></div>
      <div className="rail-item active" title="Preview workspace"><Icon name="layers" size={22} /><span>STUDIO</span></div>
      <div className="rail-bottom"><span className="vertical-label">HUMAN IN THE LOOP</span><span className="version">MVP<br />0.1</span></div>
    </aside>
    <div className="app-main">
      <header className="topbar">
        <div className="wordmark">WELDING<span>AGENT</span><span className="topbar-divider" /><span className="workspace-name">Preview Studio</span></div>
        <div className="topbar-right"><span className="mode-tag">LOCAL WORKSPACE</span><span className={`connection ${connected ? 'online' : connected === false ? 'offline' : ''}`} role="status"><i />{connected === null ? '연결 확인 중' : connected ? 'Backend connected' : 'Backend offline'}</span></div>
      </header>
      <main>
        <section className="page-heading">
          <div><div className="eyebrow"><span className="small-line" /> HUMAN-IN-THE-LOOP WELDING</div><h1>용접 경로를 함께 설계하세요<span>.</span></h1><p>이미지에서 영역을 선택하고, 자연어 명령으로 경로를 미리 확인합니다.</p></div>
          <div className="preview-badge"><span className="badge-orbit" />2D PREVIEW ONLY<small>Image coordinates · px</small></div>
        </section>

        <ol className="pipeline" aria-label="Workflow progress">
          {steps.map((step, index) => <li key={step.state} className={`${index <= currentStep ? 'complete' : ''} ${index === currentStep ? 'current' : ''}`}><span className="step-number">{index <= currentStep ? <Icon name="check" size={14} /> : String(index + 1).padStart(2, '0')}</span><span>{step.label}</span><span className="step-line" /></li>)}
          <li className={simulatorState === 'READY' || simulatorState === 'RUNNING_SAMPLE' ? 'complete' : ''} title={`Independent runtime: ${simulatorState ?? 'OFFLINE'}`}><span className="step-number">07</span><span>Simulator<small className="pipeline-runtime">독립 실행</small></span></li>
        </ol>
        {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label="오류 닫기" onClick={() => setError('')}>×</button></div>}

        <div className="workbench">
          <section className="workspace-panel">
            <div className="panel-heading"><div><span className="section-index">01</span><h2>Scene & mask</h2><span className={`status-pill ${maskReady ? 'success' : ''}`}>{maskReady ? 'MASK CONFIRMED' : job ? 'EDITING' : 'NO SCENE'}</span></div><label className={`button upload-button ${busy ? 'disabled' : ''}`}><Icon name="upload" />RGB 업로드<input aria-label="RGB 이미지 업로드" type="file" accept="image/png,image/jpeg,image/webp" disabled={Boolean(busy)} onChange={(event) => { const file = event.target.files?.[0]; if (file) void run('이미지 업로드 중', () => upload(file, file.name)); event.target.value = ''; }} /></label></div>
            <div className="tools-bar">
              <div className="tool-group"><button className={tool === 'brush' ? 'selected' : ''} aria-pressed={tool === 'brush'} onClick={() => setTool('brush')} disabled={!job || Boolean(busy)}><Icon name="brush" />Brush</button><button className={tool === 'eraser' ? 'selected' : ''} aria-pressed={tool === 'eraser'} onClick={() => setTool('eraser')} disabled={!job || Boolean(busy)}><Icon name="eraser" />Eraser</button></div>
              <span className="tool-divider" /><label className="range-control">크기<input aria-label="Brush size" type="range" min="2" max="120" value={brushSize} disabled={!job || Boolean(busy)} onChange={(e) => setBrushSize(Number(e.target.value))} /><output>{brushSize}<small> px</small></output></label>
              <span className="tool-spacer" /><button className="icon-button" aria-label="Undo" title="Undo" disabled={!history.length || Boolean(busy)} onClick={undo}><Icon name="undo" /></button><button className="icon-button" aria-label="Clear" title="Clear" disabled={!strokes.length || Boolean(busy)} onClick={clear}><Icon name="clear" /></button>
            </div>
            <div className="image-workspace">
              <div className="canvas-topline"><span><i />{job ? sceneName : 'SCENE VIEWPORT'}</span><span>{job ? `${job.scene.width} × ${job.scene.height}  /  RGB` : 'RGB + 2D MASK'}</span></div>
              {job ? <MaskCanvas key={job.scene.id} scene={job.scene} strokes={strokes} tool={tool} brushSize={brushSize} opacity={opacity} disabled={Boolean(busy)} rough={showRough ? rough : null} final={showFinal ? final : null} regions={regions} skippedRegions={skipRegions} onStart={startStroke} onMove={moveStroke} /> :
                <div className="empty-canvas"><div className="empty-icon"><Icon name="image" size={34} /></div><h3>용접할 장면을 불러오세요</h3><p>RGB 이미지를 업로드한 뒤 브러시로<br />용접할 영역을 직접 선택하세요.</p><button className="demo-button" disabled={Boolean(busy)} onClick={() => void run('샘플 이미지 불러오는 중', async () => upload(await createDemoScene(), 'demo-plates.png'))}>샘플 이미지로 시작<Icon name="arrow" size={16} /></button><small>PNG, JPG, WEBP · 최대 20 MiB / 12 MP</small></div>}
              <div className="canvas-bottomline"><span>ORIGIN (0, 0) ↘</span><span>{job ? '브러시로 영역을 그리세요 · 채워진 점 = 경로 시작' : '마스크는 2D visual conditioning 정보입니다'}</span><span>IMAGE PIXELS</span></div>
            </div>
            <div className="mask-footer"><label className="range-control opacity-control">Mask opacity<input aria-label="Mask opacity" type="range" min="0.1" max="0.9" step="0.05" value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} /><output>{Math.round(opacity * 100)}%</output></label><button className="button primary" disabled={!job || !strokes.length || Boolean(busy) || maskReady} onClick={() => void run('마스크 확정 중', async () => { if (!job) return; const blob = await exportBinaryMask(job.scene.width, job.scene.height, strokes); setJob(await api.mask(job.id, blob)); setSkipRegions([]); setMaskDirty(false); })}><Icon name="check" />{maskReady ? '마스크 확정됨' : '마스크 확정'}</button></div>
            <div className="layer-legend"><span><i className="mask-swatch" />Manual mask</span><label><input type="checkbox" checked={showRough} onChange={(e) => setShowRough(e.target.checked)} /><i className="rough-swatch" />Rough path</label><label><input type="checkbox" checked={showFinal} onChange={(e) => setShowFinal(e.target.checked)} /><i className="final-swatch" />Final VLA preview</label><span className="legend-hint">표시 레이어</span></div>
          </section>

          <aside className="control-column">
            <section className="card instruction-card"><div className="card-heading"><span className="section-index">02</span><h2>작업 지시</h2><span className="subtle-tag">DUMMY PARSER</span></div><label htmlFor="instruction" className="field-label">어느 방향으로 용접할까요?</label><textarea id="instruction" value={instruction} maxLength={2000} disabled={Boolean(busy)} onChange={(e) => setInstruction(e.target.value)} placeholder="왼쪽에서 오른쪽으로 용접해" /><div className="quick-directions"><button disabled={Boolean(busy)} onClick={() => setInstruction('왼쪽에서 오른쪽으로 용접해')}>왼쪽 → 오른쪽</button><button disabled={Boolean(busy)} onClick={() => setInstruction('오른쪽에서 왼쪽으로 용접해')}>오른쪽 → 왼쪽</button></div>{maskReady && <RegionSelector regions={regions} skipped={skipRegions} discarded={job?.mask?.discarded_component_count ?? 0} disabled={Boolean(busy) || !maskReady} onChange={setSkipRegions} />}<button className="button secondary full-width" disabled={!maskReady || !instruction.trim() || Boolean(busy) || skipRegions.length === regions.length} onClick={() => void run('명령 분석 중', async () => { if (job) setJob(await api.parse(job.id, instruction, skipRegions)); })}>Parse Instruction<Icon name="arrow" size={16} /></button><div className="parsed-output"><div className="output-label"><span>STRUCTURED INSTRUCTION</span><span className={instructionReady ? 'tiny-success' : ''}>{instructionReady ? '● READY' : '○ WAITING'}</span></div>{instructionReady && job?.instruction ? <pre data-testid="parsed-instruction">{JSON.stringify(job.instruction.structured, null, 2)}</pre> : <p>{maskReady ? '명령을 분석하면 구조화된 결과가 표시됩니다.' : '마스크를 확정한 후 명령을 분석하세요.'}</p>}</div></section>

            <section className="card plan-card"><div className="card-heading"><span className="section-index">03</span><h2>경로 미리보기</h2></div><p className="card-copy">각 영역의 Rough 경로를 만들고, Dummy VLA가 개별 경로를 다듬습니다. 영역 사이 연결선은 생성하지 않습니다.</p><button className="button generate-button full-width" disabled={!instructionReady || Boolean(busy)} onClick={() => void run('경로 생성 및 검증 중', async () => { if (job) setJob(await api.plan(job.id)); })}>Generate Weld Plan<Icon name="arrow" /></button><div className="result-metrics"><div><span>ROUGH POINTS</span><strong>{rough?.segments?.reduce((sum, segment) => sum + segment.points.length, 0) ?? '—'}<small> pts</small></strong></div><div><span>FINAL POINTS</span><strong>{final?.segments?.reduce((sum, segment) => sum + segment.points.length, 0) ?? '—'}<small> pts</small></strong></div></div><div className={`validation-result ${validated ? 'valid' : ''}`} data-testid="validation-result"><span className="validation-icon">{validated ? <Icon name="check" /> : <span>○</span>}</span><div><strong>{validated ? 'Preview geometry 통과' : 'Preview validation 대기'}</strong><small>{validated ? '영역 대응 · 좌표 · 마스크 근접성' : '경로를 생성하면 이미지 좌표를 검증합니다.'}</small></div></div><p className="scope-note">Preview trajectory · 실제 로봇 좌표가 아닙니다.<br />로봇 안전성 및 충돌 검증은 포함하지 않습니다.</p>{validated && <button className="button secondary full-width download-button" onClick={downloadPlan}><Icon name="download" />Preview JSON 저장</button>}</section>
            <SimulatorPanel onState={setSimulatorState} />
          </aside>
        </div>

        <section className="session-strip"><div><span className="session-dot" /><span>SESSION</span><code>{job?.id.slice(0, 8) ?? '—'}</code></div><div><span>STATE</span><code data-testid="workflow-state">{maskDirty && job ? 'MASK_EDITING' : effectiveState}</code></div><div><span>MASK COVERAGE</span><strong>{selectedPercent ? `${selectedPercent}%` : '—'}</strong></div><div className="session-actions">{maskReady && job?.mask && <><a href={job.mask.image_url} target="_blank" rel="noreferrer">Binary mask ↗</a><a href={job.mask.overlay_url} target="_blank" rel="noreferrer">VLA overlay ↗</a></>}</div></section>
        <footer className="page-footer"><span>2026 GYEONGNAM AI·SW COMPETITION</span><span>Human decides where. Models propose the path.</span></footer>
      </main>
    </div>
    {busy && <div className="busy-toast" role="status"><span className="spinner" />{busy}…</div>}
  </div>;
}
