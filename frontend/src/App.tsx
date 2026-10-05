import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { MaskCanvas } from './MaskCanvas';
import { SimulatorPanel } from './SimulatorPanel';
import { useSimulator } from './useSimulator';
import { createDemoScene, exportBinaryMask } from './mask';
import type { Job, ModelStatuses, Stroke, ViewId } from './types';
import { SceneViews } from './components/SceneViews';
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
import { sceneLoadIntent } from './maskIntent';
import {DecisionPreflightError} from './agentDecision';
import {useYoloOverlay} from './useYoloOverlay';
import {YoloSummary} from './components/YoloObjects';
import {ModelOutputSummary} from './components/ModelOutputSummary';
import {ModelDetails} from './components/ModelDetails';

export default function App() {
  type Draft = { strokes:Stroke[];baseMaskUrl:string|null;history:{strokes:Stroke[];baseMaskUrl:string|null}[];dirty:boolean;rawEditId?:string|null };
  const drafts = useRef<Partial<Record<ViewId,Draft>>>({});
  const [activeView,setActiveView]=useState<ViewId>('F');
  const [sampleId,setSampleId]=useState('B_PR_03_0001');
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
  const [showYolo,setShowYolo]=useState(true);
  const [showMask,setShowMask]=useState(true);
  const [showNative,setShowNative]=useState(true);
  const [showRawMask,setShowRawMask]=useState(true);
  const [forceRawMask,setForceRawMask]=useState(false);
  const [rawEditId,setRawEditId]=useState<string|null>(null);
  useEffect(()=>{setShowRawMask(true);setForceRawMask(false);},[job?.id,job?.raw_segment_output?.native_artifact_id]);
  useEffect(()=>{setShowNative(true);},[job?.native_output?.native_artifact_id]);
  const [skipRegions, setSkipRegions] = useState<number[]>([]);
  const hasViews=Boolean(job?.scene.primary_view);
  const activeImage=job?.scene.views?.[activeView];
  const canvasScene=job ? activeImage?{...job.scene,id:activeImage.image_id,width:activeImage.width,height:activeImage.height,image_url:activeImage.image_url}:job.scene:null;
  const activeMask=activeImage?activeImage.mask:job?.mask;
  const segmentOutput=job?.raw_segment_output;
  const rawMaskDisplay=segmentOutput?.model_output;
  const rawMaskUrl=rawMaskDisplay?.overlay_allowed?rawMaskDisplay.mask_urls[activeView]??null:null;
  const editRawMask=()=>{
    if(!rawMaskUrl||!segmentOutput?.native_artifact_id)return;
    setBaseMaskUrl(rawMaskUrl);setRawEditId(segmentOutput.native_artifact_id);setStrokes([]);setHistory([]);setMaskDirty(true);
  };
  const dirtyDraft=maskDirty||Object.entries(drafts.current).some(([view,draft])=>view!==activeView&&draft?.dirty);
  const assistant = useAssistant(async (message) => {
    if (sceneLoadIntent(message)) return job?.id??null;
    // Sync visual edits as an unapproved draft. SDK task selection precedes
    // backend approval gates, so edits/refinement can operate on current pixels.
    if (Object.entries(drafts.current).some(([view,draft])=>view!==activeView&&draft?.dirty))
      throw new DecisionPreflightError('MASK_DRAFT_UNSAVED','다른 view의 편집을 먼저 저장하거나 확정해주세요.');
    if (job && canvasScene && maskDirty && (strokes.length > 0 || activeMask)) {
      const blob = await exportBinaryMask(canvasScene.width, canvasScene.height, strokes, baseMaskUrl,Boolean(rawEditId));
      const synced = await api.mask(job.id, blob, activeMask?.id,activeImage?activeView:undefined,rawEditId??undefined,true);
      setJob(synced); setSkipRegions([]); setMaskDirty(false);setRawEditId(null);
      setBaseMaskUrl((activeImage?synced.scene.views?.[activeView]?.mask:synced.mask)?.image_url??null);
      setStrokes([]);setHistory([]);
    }
    return job?.id ?? null;
  }, async (id) => {
    const next = await api.getJob(id);
    if (id !== job?.id) { resetScene(next,next.scene.sample_id??'Dataset Scene');return; }
    if (next.mask && next.mask.id !== job?.mask?.id) {
      setActiveView('F');drafts.current={};setRawEditId(null);setBaseMaskUrl(next.mask.image_url); setStrokes([]); setHistory([]);
      setMaskDirty(false);
    } else if (next.scene.views?.[activeView]?.mask?.id!==job?.scene.views?.[activeView]?.mask?.id) {
      delete drafts.current[activeView];setRawEditId(null);
      setBaseMaskUrl(next.scene.views?.[activeView]?.mask?.image_url??null);
      setStrokes([]);setHistory([]);setMaskDirty(false);
    }
    setJob(next);
    if (next.mask && (!next.scene.primary_view||activeView==='F')) setMaskDirty(false);
    if (next.instruction) {
      setInstruction(next.instruction.text);
      setSkipRegions([...next.instruction.structured.skip_regions].sort((a, b) => a - b));
    }
  },job?.id);
  const busy = manualBusy || (assistant.running ? 'Assistant 작업 진행 중' : '');
  const detecting=manualBusy==='Native 마스크 검출 중'||assistant.running&&assistant.progress.some(p=>p.tool==='detect_weld_mask');
  const yolo=useYoloOverlay(job,detecting);

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
    catch (cause) { setError(cause instanceof Error ? cause.message : '요청을 처리하지 못했습니다.'); if(job)void api.getJob(job.id).then(setJob).catch(()=>{}); }
    finally { setBusy('');void api.modelStatus().then(setModels).catch(()=>{}); }
  };
  const upload = async (file: Blob, name: string) => {
    if (file.size > 20 * 1024 * 1024) throw new Error('20 MiB 이하의 이미지를 업로드하세요.');
    const next = await api.upload(file, name);
    resetScene(next,name);
  };
  const resetScene=(next:Job,name:string)=>{
    drafts.current={};setRawEditId(null);setShowNative(true);setActiveView('F');setJob(next);setSceneName(next.scene.sample_id??name);
    if(next.scene.sample_id)setSampleId(next.scene.sample_id);
    setStrokes([]);setBaseMaskUrl(null);setHistory([]);setMaskDirty(!next.mask&&!next.scene.primary_view);setSkipRegions(next.instruction?.structured.skip_regions??[]);setConnected(true);
    setInstruction(next.instruction?.text??'왼쪽에서 오른쪽으로 용접해');
  };
  const selectView=(view:ViewId)=>{
    drafts.current[activeView]={strokes,baseMaskUrl,history,dirty:maskDirty,rawEditId};
    const draft=drafts.current[view];setActiveView(view);
    setStrokes(draft?.strokes??[]);setHistory(draft?.history??[]);
    setBaseMaskUrl(draft?draft.baseMaskUrl:job?.scene.views?.[view]?.mask?.image_url??null);
    setMaskDirty(draft?.dirty??false);
    setRawEditId(draft?.rawEditId??null);
  };
  const startStroke = (stroke: Stroke) => {
    setShowRawMask(false);setForceRawMask(false);
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
  const sourceLabel = maskDirty && activeMask && activeMask.mask_source !== 'manual' ? 'Manual edited' :
    activeMask?.mask_source === 'vlm_segment' ? 'AI · VLM Segment' : activeMask?.mask_source === 'ai_refined' ? 'AI Refined from Manual' : activeMask?.mask_source === 'manual_edited' ? 'Manual edited' :
      activeMask?.mask_source === 'automatic' ? 'Dummy auto mask' : 'Manual mask';
  const canvasMaskReady=Boolean(activeMask&&activeMask.approved!==false&&!maskDirty);
  const maskReady = Boolean(job?.schema_version === 2 && job.mask && job.mask.approved !== false && !dirtyDraft);
  const editedConfirmedMask = Boolean(activeMask && maskDirty);
  const regions = maskReady ? job?.mask?.regions ?? [] : [];
  const sameSelection = JSON.stringify([...(job?.instruction?.structured.skip_regions ?? [])].sort((a, b) => a - b)) === JSON.stringify(skipRegions);
  const instructionReady = maskReady && sameSelection && job?.instruction?.text === instruction.trim();
  const previewsCurrent = maskReady && instructionReady;
  const effectiveState = !job ? 'EMPTY' : dirtyDraft ? 'SCENE_READY' : !job.mask ? 'SCENE_READY' : !instructionReady ? 'MASK_READY' : job.state;
  const final = previewsCurrent ? job?.final_trajectory ?? null : null;
  const rough = previewsCurrent ? job?.rough_trajectory ?? null : null;
  // Current-job display is independent of mask approval/instruction/acceptance.
  const nativeOutput=job?.native_output??null;
  const modelDisplay=nativeOutput?.model_output;
  const nativeWarning=!previewsCurrent||nativeOutput?.status!=='NATIVE_OUTPUT_VALIDATED';
  const nativeVisible=Boolean(showNative&&(modelDisplay?.displayable&&modelDisplay.overlay_allowed||!modelDisplay&&nativeOutput?.candidate));
  const showOriginalNative=()=>{
    const camera=modelDisplay?.primary_camera??nativeOutput?.candidate?.primary_camera;
    if(camera&&camera!==activeView)selectView(camera);
    setShowNative(true);
  };
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
        <WorkflowStepper state={effectiveState} simulatorState={simulator.online?simulator.status?.current_preview?.state??simulatorState:null} activeTab={activeTab} onNavigate={navigate} />
        <div className="model-strip" aria-label="Model status">{(['segment', 'rough', 'vla'] as const).map((stage) => {
          const status=stage==='rough'&&job?.rough_mode==='native_3d'?models?.rough3d:models?.[stage];
          return <span key={stage}>{stage === 'segment' ? 'Segment' : stage === 'rough' ? job?.rough_mode==='native_3d'?'Rough3D':'Rough2D' : status?.backend==='gpt'?'GPT Final':'VLA'} · {!status ? '확인 중' : status.backend === 'dummy' ? 'Dummy preview' : status.ready ? 'Ready' : status.configured ? '설정됨 · 미검증' : '설정 필요'}</span>;
        })}<small>{job?.rough_mode==='native_3d'?(models?.vla.backend==='gpt'?'GPT Trajectory · 승인 F conditioning':'Guided VLA · 승인 F conditioning'):'Image-pixel preview'}</small></div>
        {error && <div className="error-banner" role="alert"><Icon name="alert" /><span>{error}</span><button className="icon-button" aria-label="오류 닫기" onClick={() => setError('')}><Icon name="close" /></button></div>}
        <div className="workbench">
          <section className="workspace-panel" id="workspace" aria-label="Scene and mask workspace" tabIndex={-1}>
            <div className="panel-heading"><div><Icon name="image" size={18} /><h2>장면 · 마스크</h2><StatusBadge tone={canvasMaskReady ? 'success' : editedConfirmedMask ? 'warning' : 'neutral'} testId="mask-status">{canvasMaskReady ? '확정됨' : editedConfirmedMask ? '변경됨' : activeMask?.approved === false ? '승인 대기' : job ? '편집 중' : '장면 없음'}</StatusBadge></div><label className={`button secondary upload-button ${busy ? 'disabled' : ''}`}><Icon name="upload" size={16} />RGB 업로드<input aria-label="RGB 이미지 업로드" type="file" accept="image/png,image/jpeg,image/webp" disabled={Boolean(busy)} onChange={(event) => { const file = event.target.files?.[0]; if (file) void run('이미지 업로드 중', () => upload(file, file.name)); event.target.value = ''; }} /></label></div>
            <form className="scene-loader" onSubmit={e=>{e.preventDefault();void run('9-view 장면 불러오는 중',async()=>resetScene(await api.loadSample(sampleId.trim()),sampleId.trim()));}}>
              <label htmlFor="sample-id">Dataset sample ID</label><input id="sample-id" value={sampleId} disabled={Boolean(busy)} onChange={e=>setSampleId(e.target.value)} placeholder="B_PR_03_0001"/><button className="button secondary" disabled={Boolean(busy)||!sampleId.trim()}>9 views 불러오기</button>
            </form>
            {hasViews&&job&&<SceneViews job={job} active={activeView} disabled={Boolean(busy)} onSelect={selectView} yolo={yolo.overlay}/>}
            {(hasViews||models?.segment.backend === 'native') && <button className="button secondary native-segment-button" data-testid="native-segment" disabled={!job || Boolean(busy)} onClick={() => void run('Native 마스크 검출 중', async () => { if (!job) return; let next:Job;try{next=await api.segment(job.id,instruction);}catch(cause){setJob(await api.getJob(job.id));throw cause;} drafts.current={};setRawEditId(null);setActiveView('F');setJob(next); setBaseMaskUrl(next.mask?.image_url ?? null); setStrokes([]); setHistory([]); setMaskDirty(false); setSkipRegions([]); })}>AI 마스크 검출 {hasViews?'· F / R / S4':''}</button>}
            <WorkspaceToolbar tool={tool} brushSize={brushSize} disabled={!job || Boolean(busy)} canUndo={Boolean(history.length) && !busy} canClear={Boolean(strokes.length || baseMaskUrl) && !busy} onTool={setTool} onSize={setBrushSize} onUndo={undo} onClear={clear} />
            <div className="image-workspace">
              <div className="canvas-topline"><span><i />{job ? `${sceneName}${activeImage?' · '+activeView:''}` : 'SCENE VIEWPORT'}</span><span>{canvasScene ? `${canvasScene.width} × ${canvasScene.height} / RGB` : 'RGB + 2D MASK'}</span></div>
              {canvasScene ? <MaskCanvas key={canvasScene.id} scene={canvasScene} strokes={strokes} baseMaskUrl={baseMaskUrl} tool={tool} brushSize={brushSize} opacity={opacity} disabled={Boolean(busy)} rough={!nativeVisible&&showRough&&(!activeImage||activeView==='F') ? rough : null} final={!nativeVisible&&showFinal&&(!activeImage||activeView==='F') ? final : null} nativeCandidate={nativeVisible&&activeView===nativeOutput?.candidate?.primary_camera?nativeOutput.candidate:null} nativeWarning={nativeWarning} modelDisplay={nativeVisible&&activeView===modelDisplay?.primary_camera?modelDisplay:null} rawBase={Boolean(rawEditId)} rawMaskUnapproved={activeMask?.approved===false} rawMaskUrl={showRawMask&&!rawEditId&&(forceRawMask||!activeMask||segmentOutput?.validation.status!=='PASS')?rawMaskUrl:null} showMask={showMask} yolo={showYolo?yolo.overlay?.views[activeView]:null} regions={canvasMaskReady?activeMask?.regions??[]:[]} skippedRegions={activeView==='F'?skipRegions:[]} onStart={startStroke} onMove={moveStroke} /> :
                <div className="empty-canvas"><div className="empty-icon"><Icon name="image" size={32} /></div><span className="utility-label">START WITH A SCENE</span><h3>용접할 장면을 불러오세요</h3><p>RGB 이미지를 업로드한 뒤 브러시로<br />용접할 영역을 직접 선택하세요.</p><button className="demo-button" disabled={Boolean(busy)} onClick={() => void run('샘플 이미지 불러오는 중', async () => upload(await createDemoScene(), 'demo-plates.png'))}>샘플 이미지로 시작<Icon name="arrow" size={16} /></button><small>PNG, JPG, WEBP · 최대 20 MiB / 12 MP</small></div>}
              <div className="canvas-bottomline"><span>ORIGIN (0, 0)</span><span>{job ? '브러시로 영역 선택 · ● 시작 / ○ 끝' : '2D visual conditioning'}</span><span>IMAGE PIXELS</span></div>
            </div>
            <div className="mask-footer"><label className="range-control opacity-control">마스크 표시<input aria-label="Mask opacity" type="range" min="0.1" max="0.9" step="0.05" value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} /><output>{Math.round(opacity * 100)}%</output></label><div className="mask-confirm-action">{editedConfirmedMask && <span className="mask-dirty-note" role="status">마스크가 변경되었습니다</span>}<button data-testid="confirm-mask" className="button primary" disabled={!job || (!strokes.length && !baseMaskUrl) || Boolean(busy) || canvasMaskReady} onClick={() => void run('마스크 확정 중', async () => { if (!job||!canvasScene) return; let next:Job;if (activeMask && !maskDirty) { next=await api.approveMask(job.id, activeMask.id,activeImage?activeView:undefined); } else { const blob = await exportBinaryMask(canvasScene.width, canvasScene.height, strokes, baseMaskUrl,Boolean(rawEditId)); next=await api.mask(job.id, blob, activeMask?.id,activeImage?activeView:undefined,rawEditId??undefined); if(rawEditId){setBaseMaskUrl((activeImage?next.scene.views?.[activeView]?.mask:next.mask)?.image_url??null);setRawEditId(null);setStrokes([]);setHistory([]);} } setJob(next);delete drafts.current[activeView];setSkipRegions([]); setMaskDirty(false); })}><Icon name="check" size={16} />{canvasMaskReady ? '마스크 확정됨' : editedConfirmedMask ? '다시 확정' : '마스크 확정'}{activeImage?` · ${activeView}`:''}</button></div></div>
            <div className="layer-legend"><Icon name="layers" size={14} /><label><input aria-label="VLM Weld Mask" type="checkbox" checked={showMask} onChange={e=>setShowMask(e.target.checked)}/><i className="mask-swatch" /><span data-testid="mask-source">{sourceLabel}</span></label><label><input aria-label="YOLO Objects" type="checkbox" checked={showYolo} onChange={e=>setShowYolo(e.target.checked)}/><i className="yolo-swatch"/>YOLO Objects · <span data-testid="yolo-active-count">{yolo.overlay?.views[activeView]?.detections.length??0}</span></label><label><input type="checkbox" checked={showRough} onChange={(e) => setShowRough(e.target.checked)} /><i className="rough-swatch" />{job?.rough_mode==='native_3d'?'2D guidance':'Rough path'}</label>{(modelDisplay?.displayable&&modelDisplay.overlay_allowed||nativeOutput?.candidate)&&<label><input aria-label="Native model path" type="checkbox" checked={nativeVisible} onChange={e=>{setShowNative(e.target.checked);}}/><i className="native-swatch"/>Native model path</label>}{job?.rough_mode==='native_3d'?<span>Final XYZ · 별도 결과</span>:<label><input type="checkbox" checked={showFinal} onChange={(e) => setShowFinal(e.target.checked)} /><i className="final-swatch" />Final VLA preview</label>}{rawMaskUrl&&<label><input aria-label="Raw Segment Output" type="checkbox" checked={showRawMask} onChange={e=>{setShowRawMask(e.target.checked);setForceRawMask(e.target.checked);}}/>Raw Segment Output</label>}<span className="legend-hint">DISPLAY LAYERS</span></div>
          </section>
          <Inspector active={activeTab} onChange={setActiveTab} simulatorState={simulatorState}
            summary={<ModelDetails key={job?.id??'empty'} output={segmentOutput} approved={Boolean(job?.mask?.approved&&!dirtyDraft&&job.mask.artifact?.provenance.native_source_artifact_id===segmentOutput?.native_artifact_id)} overlay={yolo.overlay} view={activeView} loading={yolo.loading} warning={yolo.warning}>
              <ModelOutputSummary output={segmentOutput} model="SEGMENT2" approved={Boolean(job?.mask?.approved&&!dirtyDraft&&job.mask.artifact?.provenance.native_source_artifact_id===segmentOutput?.native_artifact_id)} onShow={()=>{setShowRawMask(true);setForceRawMask(true);}} onEdit={editRawMask}/>{hasViews?<YoloSummary overlay={yolo.overlay} view={activeView} warning={yolo.warning} loading={yolo.loading} maskSource={maskDirty&&activeMask?'manual_edited':activeMask?.mask_source??'—'}/>:null}
            </ModelDetails>} nextAction={
            activeTab === 'command' && manualOpen && instructionReady && !job?.trajectory_clarification ? <NextAction destination="path" onContinue={() => navigate('path')} /> :
            activeTab === 'path' && (validated || (previewsCurrent && job?.state==='VLA_READY')) ? <NextAction destination="simulator" onContinue={() => navigate('simulator')} /> : null
          } panels={{
            command: <AssistantPanel clarification={job?.trajectory_clarification} requiresMaskConfirmation={Boolean(job?.mask && (job.mask.approved === false || (dirtyDraft && (hasViews||models?.rough.backend === 'native'))))} assistant={assistant} busy={Boolean(busy)} maskDirty={Boolean(job && maskDirty && strokes.length)} onManualToggle={setManualOpen}
              manual={<CommandPanel instruction={instruction} busy={Boolean(busy)} maskReady={maskReady} instructionReady={instructionReady} job={job} regions={regions} skipRegions={skipRegions} onInstruction={setInstruction} onRegions={setSkipRegions} onParse={() => void run('명령 분석 중', async () => { if (job) setJob(await api.parse(job.id, instruction, skipRegions)); })} />} />,
            path: <PathPanel onEndpoint={(xyz,source)=>void run('끝점 적용 중',async()=>{if(job)setJob(await api.setEndpoint(job.id,xyz,source));})} finalBackend={models?.vla.backend} finalSource={models?.vla.source} finalRetrieval={models?.vla.retrieval_mode} job={job} nativeOutput={nativeOutput} onShowNative={showOriginalNative} onMode={mode=>void run('Rough mode 변경 중',async()=>{if(job)setJob(await api.roughMode(job.id,mode));})} onGuided={()=>void run('최종 3D 궤적 예측 중',async()=>{if(!job)return;try{setJob(await api.finalTrajectory(job.id));}catch(cause){try{setJob(await api.getJob(job.id));}catch{/* Keep previously loaded display evidence. */}throw cause;}})} native={models?.rough.backend === 'native'} instructionReady={instructionReady} busy={Boolean(busy)} validated={validated} rough={rough} final={final} validation={previewsCurrent ? job?.validation ?? null : null} regions={regions} skipRegions={skipRegions} onGenerate={() => void run('경로 생성 및 검증 중', async () => {
              if(!job)return;
              try {setJob(await api.plan(job.id));}
              catch(cause){
                // A failed execution may have persisted a partial native report.
                // Refresh that evidence; this never retries model generation.
                try{setJob(await api.getJob(job.id));}catch{/* Keep previously loaded display evidence. */}
                throw cause;
              }
            })} onDownload={downloadPlan} onCommand={() => navigate('command')} />,
            simulator: <fieldset className="simulator-controls"><SimulatorPanel jobId={job?.id} sampleId={job?.scene.sample_id??undefined} mutationBlocked={assistant.running} raw={previewsCurrent?job?.raw_final_prediction:null} vla={previewsCurrent?job?.vla_prediction:null} simulator={simulator} onPlan={() => navigate('path')} onConsole={() => setConsoleOpen(true)} /></fieldset>,
          }} />
        </div>
        <section className="session-strip" aria-label="Current session"><div><span className="session-dot" /><span>SESSION</span><code>{job?.id.slice(0, 8) ?? '—'}</code></div><div><span>STATE</span><code data-testid="workflow-state">{maskDirty && job ? 'MASK_EDITING' : effectiveState}</code></div><div><span>MASK</span><strong>{selectedPercent ? `${selectedPercent}%` : '—'}</strong></div><div className="session-actions">{canvasMaskReady && activeMask && <><a href={activeMask.image_url} target="_blank" rel="noreferrer">Binary mask ↗</a><a href={activeMask.overlay_url} target="_blank" rel="noreferrer">VLA overlay ↗</a></>}</div></section>
        <ConsoleDrawer logs={simulator.logs} state={simulatorState} online={simulator.online} error={simulator.error || simulator.status?.error || ''} open={consoleOpen} onToggle={() => setConsoleOpen((value) => !value)} />
      </main>
    </div>
    {busy && <div className="busy-toast" role="status"><span className="spinner" />{busy}…</div>}
  </div>;
}
