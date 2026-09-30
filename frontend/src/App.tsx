import { useEffect, useState } from 'react';
import { api } from './api';
import { MaskCanvas } from './MaskCanvas';
import { SimulatorPanel } from './SimulatorPanel';
import { useSimulator } from './useSimulator';
import { createDemoScene, exportBinaryMask } from './mask';
import type { Job, ModelStatuses, Stroke } from './types';
import { Icon } from './components/Icon';
import { StatusBadge } from './components/StatusBadge';
import { WorkflowStepper } from './components/WorkflowStepper';
import { WorkspaceToolbar } from './components/WorkspaceToolbar';
import { Inspector, type InspectorTab } from './components/Inspector';
import { CommandPanel } from './components/CommandPanel';
import { PathPanel } from './components/PathPanel';
import { NextAction } from './components/NextAction';
import { ConsoleDrawer } from './components/ConsoleDrawer';
import { AssistantPanel } from './components/AssistantPanel';
import { useAssistant } from './useAssistant';

export default function App() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const simulator = useSimulator();
  const simulatorState = simulator.online ? simulator.status?.state ?? null : null;
  const [activeTab, setActiveTab] = useState<InspectorTab>('command');
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [sceneName, setSceneName] = useState('');
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [baseMaskUrl, setBaseMaskUrl] = useState<string | null>(null);
  const [history, setHistory] = useState<{ strokes: Stroke[]; baseMaskUrl: string | null }[]>([]);
  const [models, setModels] = useState<ModelStatuses | null>(null);
  const [tool, setTool] = useState<Stroke['tool']>('brush');
  const [brushSize, setBrushSize] = useState(28);
  const [opacity, setOpacity] = useState(0.45);
  const [maskDirty, setMaskDirty] = useState(true);
  const [instruction, setInstruction] = useState('왼쪽에서 오른쪽으로 용접해');
  const [manualBusy, setBusy] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [error, setError] = useState('');
  const [showRough, setShowRough] = useState(true);
  const [showFinal, setShowFinal] = useState(true);
  const [skipRegions, setSkipRegions] = useState<number[]>([]);
  const assistant = useAssistant(async () => {
    if (job?.mask && (job.mask.approved === false || (maskDirty && models?.rough.backend === 'native'))) {
      throw new Error('Canvas에서 현재 마스크를 검토하고 마스크 확정을 눌러주세요.');
    }
    if (job && maskDirty && (strokes.length > 0 || job.mask)) {
      const blob = await exportBinaryMask(job.scene.width, job.scene.height, strokes, baseMaskUrl);
      const synced = await api.mask(job.id, blob, job.mask?.id);
      setJob(synced); setSkipRegions([]); setMaskDirty(false);
    }
    return job?.id ?? null;
  }, async (id) => {
    if (id !== job?.id) return;
    const next = await api.getJob(id);
    if (next.mask && next.mask.id !== job?.mask?.id && ['automatic', 'vlm_segment'].includes(next.mask.mask_source)) {
      setBaseMaskUrl(next.mask.image_url); setStrokes([]); setHistory([]);
    }
    setJob(next);
    if (next.mask) setMaskDirty(false);
    if (next.instruction) {
      setInstruction(next.instruction.text);
      setSkipRegions([...next.instruction.structured.skip_regions].sort((a, b) => a - b));
    }
  });
  const busy = manualBusy || (assistant.running ? 'Assistant 작업 진행 중' : '');

  useEffect(() => {
    let active = true;
    const check = async () => {
      try { await api.health(); if (active) setConnected(true); }
      catch { if (active) setConnected(false); }
      try { const status = await api.modelStatus(); if (active) setModels(status); }
      catch { if (active) setModels(null); }
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
    setJob(next); setSceneName(name); setStrokes([]); setBaseMaskUrl(null); setHistory([]); setMaskDirty(true); setSkipRegions([]); setConnected(true);
  };
  const startStroke = (stroke: Stroke) => {
    setHistory((previous) => [...previous, { strokes, baseMaskUrl }]); setStrokes((previous) => [...previous, stroke]); setMaskDirty(true);
  };
  const moveStroke = (point: number[]) => setStrokes((previous) => {
    const last = previous.at(-1); if (!last || (last.points.at(-2) === point[0] && last.points.at(-1) === point[1])) return previous;
    return [...previous.slice(0, -1), { ...last, points: [...last.points, ...point] }];
  });
  const undo = () => {
    const previous = history.at(-1); if (!previous) return;
    setStrokes(previous.strokes); setBaseMaskUrl(previous.baseMaskUrl); setHistory((values) => values.slice(0, -1)); setMaskDirty(true);
  };
  const clear = () => { setHistory((previous) => [...previous, { strokes, baseMaskUrl }]); setStrokes([]); setBaseMaskUrl(null); setMaskDirty(true); };
  const sourceLabel = maskDirty && job?.mask && job.mask.mask_source !== 'manual' ? 'Manual edited' :
    job?.mask?.mask_source === 'vlm_segment' ? 'AI · VLM Segment' : job?.mask?.mask_source === 'manual_edited' ? 'Manual edited' :
      job?.mask?.mask_source === 'automatic' ? 'Dummy auto mask' : 'Manual mask';
  const maskReady = Boolean(job?.schema_version === 2 && job.mask && job.mask.approved !== false && !maskDirty);
  const editedConfirmedMask = Boolean(job?.mask && maskDirty);
  const regions = maskReady ? job?.mask?.regions ?? [] : [];
  const sameSelection = JSON.stringify([...(job?.instruction?.structured.skip_regions ?? [])].sort((a, b) => a - b)) === JSON.stringify(skipRegions);
  const instructionReady = maskReady && sameSelection && job?.instruction?.text === instruction.trim();
  const previewsCurrent = maskReady && instructionReady;
  const effectiveState = !job ? 'EMPTY' : maskDirty ? 'SCENE_READY' : !instructionReady ? 'MASK_READY' : job.state;
  const final = previewsCurrent ? job?.final_trajectory ?? null : null;
  const rough = previewsCurrent ? job?.rough_trajectory ?? null : null;
  const validated = Boolean(previewsCurrent && job?.state === 'VALIDATED' && job.validation?.valid);
  const selectedPercent = maskReady && job?.mask ? (100 * job.mask.selected_pixels / (job.scene.width * job.scene.height)).toFixed(2) : null;

  const navigate = (target: InspectorTab | 'workspace') => {
    if (target !== 'workspace') setActiveTab(target);
    window.requestAnimationFrame(() => {
      const destination = document.getElementById(target === 'workspace' ? 'workspace' : `tab-${target}`);
      destination?.focus({ preventScroll: true });
      if (target !== 'workspace') document.getElementById(`panel-${target}`)?.scrollTo(0, 0);
      if (window.matchMedia('(max-width: 1000px)').matches) {
        document.getElementById(target === 'workspace' ? 'workspace' : 'inspector')?.scrollIntoView({ block: 'start' });
      }
    });
  };

  const downloadPlan = () => {
    if (!job || !validated) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(job, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `preview-${job.id}.json`; anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return <div className="app-shell">
    <a className="skip-link" href="#workspace">작업 영역으로 이동</a>
    <aside className="rail" aria-label="Workspace identity">
      <div className="brand-symbol" aria-label="Welding Agent"><Icon name="crosshair" size={24} /></div>
      <a className="rail-item active" href="#workspace" aria-label="Preview workspace" title="Preview workspace"><Icon name="layers" size={21} /></a>
      <span className="rail-caption">STUDIO</span>
      <div className="rail-bottom"><span className="vertical-label">HUMAN IN THE LOOP</span><span className="version">MVP</span></div>
    </aside>
    <div className="app-main">
      <header className="topbar">
        <div className="wordmark">WELDING<span>AGENT</span><span className="topbar-divider" /><span className="workspace-name">Operator workspace</span></div>
        <div className="topbar-right"><span className="mode-tag">LOCAL</span><span className={`connection ${connected ? 'online' : connected === false ? 'offline' : ''}`} role="status"><i />{connected === null ? '연결 확인 중' : connected ? 'Backend connected' : 'Backend offline'}</span></div>
      </header>
      <main>
        <section className="page-heading"><div><h1>Welding Preview Studio</h1><p>영역을 선택하고, 지시하고, 경로를 검토하세요.</p></div><span className="preview-badge"><Icon name="crosshair" size={16} />2D PREVIEW<span>Image pixels</span></span></section>
        <WorkflowStepper state={effectiveState} simulatorState={simulatorState} activeTab={activeTab} onNavigate={navigate} />
        <div className="model-strip" aria-label="Model status">{(['segment', 'rough', 'vla'] as const).map((stage) => <span key={stage}>
          {stage === 'segment' ? 'Segment' : stage === 'rough' ? 'Rough' : 'VLA'} · {stage === 'vla' && models?.rough.backend === 'native' ? '연결 보류' : models?.[stage].backend === 'dummy' ? 'Dummy preview' : !models ? '확인 중' : models[stage].ready ? 'Ready' : models[stage].configured ? models[stage].state === 'FAILED' ? '실행 오류' : '설정됨 · 미검증' : '설정 필요'}
        </span>)}<small>실제 VLA 연결 보류</small></div>
        {error && <div className="error-banner" role="alert"><Icon name="alert" /><span>{error}</span><button className="icon-button" aria-label="오류 닫기" onClick={() => setError('')}><Icon name="close" /></button></div>}
        <div className="workbench">
          <section className="workspace-panel" id="workspace" aria-label="Scene and mask workspace" tabIndex={-1}>
            <div className="panel-heading"><div><Icon name="image" size={18} /><h2>장면 · 마스크</h2><StatusBadge tone={maskReady ? 'success' : editedConfirmedMask ? 'warning' : 'neutral'} testId="mask-status">{maskReady ? '확정됨' : editedConfirmedMask ? '변경됨' : job?.mask?.approved === false ? '승인 대기' : job ? '편집 중' : '장면 없음'}</StatusBadge></div><label className={`button secondary upload-button ${busy ? 'disabled' : ''}`}><Icon name="upload" size={16} />RGB 업로드<input aria-label="RGB 이미지 업로드" type="file" accept="image/png,image/jpeg,image/webp" disabled={Boolean(busy)} onChange={(event) => { const file = event.target.files?.[0]; if (file) void run('이미지 업로드 중', () => upload(file, file.name)); event.target.value = ''; }} /></label></div>
            {models?.segment.backend === 'native' && <button className="button secondary" data-testid="native-segment" disabled={!job || Boolean(busy)} onClick={() => void run('Native 마스크 검출 중', async () => { if (!job) return; const next = await api.segment(job.id, instruction); setJob(next); setBaseMaskUrl(next.mask?.image_url ?? null); setStrokes([]); setHistory([]); setMaskDirty(false); setSkipRegions([]); })}>AI 마스크 검출</button>}
            <WorkspaceToolbar tool={tool} brushSize={brushSize} disabled={!job || Boolean(busy)} canUndo={Boolean(history.length) && !busy} canClear={Boolean(strokes.length || baseMaskUrl) && !busy} onTool={setTool} onSize={setBrushSize} onUndo={undo} onClear={clear} />
            <div className="image-workspace">
              <div className="canvas-topline"><span><i />{job ? sceneName : 'SCENE VIEWPORT'}</span><span>{job ? `${job.scene.width} × ${job.scene.height} / RGB` : 'RGB + 2D MASK'}</span></div>
              {job ? <MaskCanvas key={job.scene.id} scene={job.scene} strokes={strokes} baseMaskUrl={baseMaskUrl} tool={tool} brushSize={brushSize} opacity={opacity} disabled={Boolean(busy)} rough={showRough ? rough : null} final={showFinal ? final : null} regions={regions} skippedRegions={skipRegions} onStart={startStroke} onMove={moveStroke} /> :
                <div className="empty-canvas"><div className="empty-icon"><Icon name="image" size={32} /></div><span className="utility-label">START WITH A SCENE</span><h3>용접할 장면을 불러오세요</h3><p>RGB 이미지를 업로드한 뒤 브러시로<br />용접할 영역을 직접 선택하세요.</p><button className="demo-button" disabled={Boolean(busy)} onClick={() => void run('샘플 이미지 불러오는 중', async () => upload(await createDemoScene(), 'demo-plates.png'))}>샘플 이미지로 시작<Icon name="arrow" size={16} /></button><small>PNG, JPG, WEBP · 최대 20 MiB / 12 MP</small></div>}
              <div className="canvas-bottomline"><span>ORIGIN (0, 0)</span><span>{job ? '브러시로 영역 선택 · ● 시작 / ○ 끝' : '2D visual conditioning'}</span><span>IMAGE PIXELS</span></div>
            </div>
            <div className="mask-footer"><label className="range-control opacity-control">마스크 표시<input aria-label="Mask opacity" type="range" min="0.1" max="0.9" step="0.05" value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} /><output>{Math.round(opacity * 100)}%</output></label><div className="mask-confirm-action">{editedConfirmedMask && <span className="mask-dirty-note" role="status">마스크가 변경되었습니다</span>}<button data-testid="confirm-mask" className="button primary" disabled={!job || (!strokes.length && !baseMaskUrl) || Boolean(busy) || maskReady} onClick={() => void run('마스크 확정 중', async () => { if (!job) return; if (job.mask && !maskDirty) { setJob(await api.approveMask(job.id, job.mask.id)); } else { const blob = await exportBinaryMask(job.scene.width, job.scene.height, strokes, baseMaskUrl); setJob(await api.mask(job.id, blob, job.mask?.id)); } setSkipRegions([]); setMaskDirty(false); })}><Icon name="check" size={16} />{maskReady ? '마스크 확정됨' : editedConfirmedMask ? '다시 확정' : '마스크 확정'}</button></div></div>
            <div className="layer-legend"><Icon name="layers" size={14} /><span><i className="mask-swatch" /><span data-testid="mask-source">{sourceLabel}</span></span><label><input type="checkbox" checked={showRough} onChange={(e) => setShowRough(e.target.checked)} /><i className="rough-swatch" />Rough path</label><label><input type="checkbox" checked={showFinal} onChange={(e) => setShowFinal(e.target.checked)} /><i className="final-swatch" />Final VLA preview</label><span className="legend-hint">DISPLAY LAYERS</span></div>
          </section>
          <Inspector active={activeTab} onChange={setActiveTab} simulatorState={simulatorState} nextAction={
            activeTab === 'command' && manualOpen && instructionReady ? <NextAction destination="path" onContinue={() => navigate('path')} /> :
            activeTab === 'path' && validated ? <NextAction destination="simulator" onContinue={() => navigate('simulator')} /> : null
          } panels={{
            command: <AssistantPanel requiresMaskConfirmation={Boolean(job?.mask && (job.mask.approved === false || (maskDirty && models?.rough.backend === 'native')))} assistant={assistant} busy={Boolean(busy)} maskDirty={Boolean(job && maskDirty && strokes.length)} onManualToggle={setManualOpen}
              manual={<CommandPanel instruction={instruction} busy={Boolean(busy)} maskReady={maskReady} instructionReady={instructionReady} job={job} regions={regions} skipRegions={skipRegions} onInstruction={setInstruction} onRegions={setSkipRegions} onParse={() => void run('명령 분석 중', async () => { if (job) setJob(await api.parse(job.id, instruction, skipRegions)); })} />} />,
            path: <PathPanel native={models?.rough.backend === 'native'} instructionReady={instructionReady} busy={Boolean(busy)} validated={validated} rough={rough} final={final} validation={previewsCurrent ? job?.validation ?? null : null} regions={regions} skipRegions={skipRegions} onGenerate={() => void run('경로 생성 및 검증 중', async () => { if (job) setJob(await api.plan(job.id)); })} onDownload={downloadPlan} onCommand={() => navigate('command')} />,
            simulator: <fieldset className="simulator-controls" disabled={assistant.running}><SimulatorPanel simulator={simulator} onConsole={() => setConsoleOpen(true)} /></fieldset>,
          }} />
        </div>
        <section className="session-strip" aria-label="Current session"><div><span className="session-dot" /><span>SESSION</span><code>{job?.id.slice(0, 8) ?? '—'}</code></div><div><span>STATE</span><code data-testid="workflow-state">{maskDirty && job ? 'MASK_EDITING' : effectiveState}</code></div><div><span>MASK</span><strong>{selectedPercent ? `${selectedPercent}%` : '—'}</strong></div><div className="session-actions">{maskReady && job?.mask && <><a href={job.mask.image_url} target="_blank" rel="noreferrer">Binary mask ↗</a><a href={job.mask.overlay_url} target="_blank" rel="noreferrer">VLA overlay ↗</a></>}</div></section>
        <ConsoleDrawer logs={simulator.logs} state={simulatorState} online={simulator.online} error={simulator.error || simulator.status?.error || ''} open={consoleOpen} onToggle={() => setConsoleOpen((value) => !value)} />
      </main>
    </div>
    {busy && <div className="busy-toast" role="status"><span className="spinner" />{busy}…</div>}
  </div>;
}
