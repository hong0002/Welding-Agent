import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Circle, Group, Image as KonvaImage, Layer, Line, Rect, Stage, Text } from 'react-konva';
import type Konva from 'konva';
import type { Job, MaskRegion, Stroke, Trajectory,NativeCandidate,YoloView,ModelOutputDisplay } from './types';
import { loadMaskLayer } from './mask';
import {YoloObjects} from './components/YoloObjects';

type Props = {
  scene: Job['scene']; strokes: Stroke[]; tool: Stroke['tool']; brushSize: number; opacity: number;
  baseMaskUrl?: string | null;
  disabled: boolean; rough: Trajectory | null; final: Trajectory | null;
  regions: MaskRegion[]; skippedRegions: number[];
  nativeCandidate?:NativeCandidate|null;nativeWarning?:boolean;
  modelDisplay?:ModelOutputDisplay|null;rawMaskUrl?:string|null;rawBase?:boolean;rawMaskUnapproved?:boolean;
  yolo?:YoloView|null;showMask?:boolean;
  onStart: (stroke: Stroke) => void; onMove: (point: number[]) => void;
};

export function MaskCanvas({ scene, strokes, tool, brushSize, opacity, baseMaskUrl, disabled, rough, final, nativeCandidate,nativeWarning,modelDisplay,rawMaskUrl,rawBase=false,rawMaskUnapproved=false,yolo,showMask=true,regions, skippedRegions, onStart, onMove }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const stage = useRef<Konva.Stage>(null);
  const maskLayer = useRef<Konva.Layer>(null);
  const drawing = useRef(false);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [imageError, setImageError] = useState(false);
  const [baseMask, setBaseMask] = useState<HTMLCanvasElement | null>(null);
  const [maskError, setMaskError] = useState('');
  const [rawMask,setRawMask]=useState<HTMLCanvasElement|null>(null);
  useEffect(()=>{let active=true;setRawMask(null);if(rawMaskUrl)void loadMaskLayer(rawMaskUrl,scene.width,scene.height,true)
    .then(c=>{if(active)setRawMask(c);}).catch(()=>{if(active)setMaskError('모델 출력 표시를 불러오지 못했습니다.');});return()=>{active=false;};},[rawMaskUrl,scene.width,scene.height]);
  useEffect(() => {
    let active = true; setBaseMask(null); setMaskError('');
    if (baseMaskUrl) void loadMaskLayer(baseMaskUrl, scene.width, scene.height,rawBase)
      .then((canvas) => { if (active) setBaseMask(canvas); })
      .catch((cause) => { if (active) setMaskError(cause instanceof Error ? cause.message : '마스크 로드 실패'); });
    return () => { active = false; };
  }, [baseMaskUrl, scene.width, scene.height,rawBase]);
  const maskLoading = Boolean(baseMaskUrl && !baseMask);
  const [viewport, setViewport] = useState({ width: 800, height: 450 });
  const [cursor, setCursor] = useState<number[] | null>(null);
  // Only the displayed stage is fitted. Strokes and exported masks remain source pixels.
  const scale = Math.min(viewport.width / scene.width, viewport.height / scene.height);

  useLayoutEffect(() => {
    // Konva node opacity is inherited by every stroke, including destination-out.
    // Composite brush/eraser at alpha=1, then fade only the completed DOM canvas.
    const canvas = maskLayer.current?.getNativeCanvasElement();
    if (canvas) canvas.style.opacity = String(opacity);
  }, [opacity, image]);

  useEffect(() => {
    setImage(null); setImageError(false);
    const next = new Image(); next.crossOrigin = 'anonymous';
    next.onload = () => setImage(next); next.onerror = () => setImageError(true); next.src = scene.image_url;
    return () => { next.onload = null; next.onerror = null; };
  }, [scene.image_url]);
  useEffect(() => {
    const resize = new ResizeObserver(([entry]) => setViewport({
      width: Math.max(1, entry.contentRect.width), height: Math.max(1, entry.contentRect.height),
    }));
    if (host.current) resize.observe(host.current);
    return () => resize.disconnect();
  }, []);
  useEffect(() => {
    const stop = () => { drawing.current = false; };
    window.addEventListener('pointerup', stop); window.addEventListener('blur', stop);
    return () => { window.removeEventListener('pointerup', stop); window.removeEventListener('blur', stop); };
  }, []);

  const position = () => {
    const pos = stage.current?.getPointerPosition();
    return pos ? [Math.max(0, Math.min(scene.width - 1, pos.x / scale)), Math.max(0, Math.min(scene.height - 1, pos.y / scale))] : null;
  };
  // One Konva Line per segment. Flattening the full trajectory would bridge regions.
  const path = (trajectory: Trajectory, color: string, dashed = false) => (trajectory.segments ?? []).map((segment) => <Group key={segment.segment_id}>
    <Line points={segment.points.flatMap((p) => [p.x, p.y])} stroke={color} strokeWidth={(dashed ? 6 : 2.5) / scale} dash={dashed ? [7 / scale, 5 / scale] : undefined} lineCap="round" lineJoin="round" />
    {segment.points[0] && <Circle x={segment.points[0].x} y={segment.points[0].y} radius={(dashed ? 6 : 4) / scale} fill={color} stroke="#142323" strokeWidth={1.5 / scale} />}
    {segment.points.length > 1 && <Circle x={segment.points.at(-1)!.x} y={segment.points.at(-1)!.y} radius={4 / scale} stroke={color} strokeWidth={2 / scale} />}
  </Group>);

  return <div ref={host} className={`canvas-host ${tool}`} data-testid="canvas-host">
    {(modelDisplay||nativeCandidate)&&<span className={`native-canvas-label ${nativeWarning?'warning':''}`} data-testid="native-path-label">{nativeWarning?'⚠ 모델 생성 경로 · 검증 미통과':'원본 모델 경로 · 검증 통과'}{modelDisplay?.partial?' · PARTIAL':''}</span>}
    {(rawMaskUrl||rawBase||rawMaskUnapproved)&&<span className="raw-mask-label" data-testid="raw-mask-label">RAW MODEL MASK · 승인과 별도</span>}
    {maskError && <p role="alert">{maskError}</p>}
    {imageError ? <p role="alert">이미지를 불러오지 못했습니다. Backend 연결을 확인하고 다시 업로드하세요.</p> : !image ? <p className="canvas-loading">이미지 불러오는 중…</p> :
    <div className="stage-wrap" data-testid="drawing-surface">
      <Stage ref={stage} width={scene.width * scale} height={scene.height * scale} scaleX={scale} scaleY={scale}
        onPointerDown={(event) => {
          if (disabled || maskLoading || event.evt.button > 0) return;
          const point = position(); if (!point) return;
          drawing.current = true; onStart({ tool, size: brushSize, points: point });
        }}
        onPointerMove={() => { const point = position(); setCursor(point); if (point && drawing.current && !disabled) onMove(point); }}
        onPointerUp={() => {
          const point = position();
          if (point && drawing.current && !disabled) onMove(point);
          drawing.current = false;
        }}
        onPointerCancel={() => { drawing.current = false; setCursor(null); }}
        onPointerLeave={() => { drawing.current = false; setCursor(null); }}>
        <Layer listening={false}><KonvaImage image={image} width={scene.width} height={scene.height} /></Layer>
        <Layer ref={maskLayer} listening={false} visible={showMask}>
          {baseMask && <KonvaImage image={baseMask} width={scene.width} height={scene.height} />}
          {strokes.map((stroke, index) => stroke.points.length === 2
            ? <Circle key={index} x={stroke.points[0]} y={stroke.points[1]} radius={stroke.size / 2} fill="#ff4b60" globalCompositeOperation={stroke.tool === 'eraser' ? 'destination-out' : 'source-over'} />
            : <Line key={index} points={stroke.points} stroke="#ff4b60" strokeWidth={stroke.size} lineCap="round" lineJoin="round" globalCompositeOperation={stroke.tool === 'eraser' ? 'destination-out' : 'source-over'} />)}
        </Layer>
        {yolo&&<YoloObjects view={yolo} scale={scale}/>}
        {rawMask&&<Layer listening={false} opacity={0.28} visible={showMask}><KonvaImage image={rawMask}/><Rect width={scene.width} height={scene.height} stroke="#ffc866" strokeWidth={2/scale} dash={[8/scale,6/scale]}/></Layer>}
        <Layer listening={false}>
          {rough && path(rough, '#ffc866', true)}
          {final && path(final, '#62eed2')}
          {modelDisplay?.segments.map(segment=><Group key={segment.segment_index} name="native-model-segment">
            {segment.runs.map((run,index)=><Group key={index}>
              {run.length>1&&<Line name="native-model-path" points={run.flat()} stroke={nativeWarning?'#ff9c61':'#62eed2'} strokeWidth={3.5/scale}
                dash={modelDisplay.partial?[2/scale,5/scale]:nativeWarning?[10/scale,6/scale]:undefined} lineCap="round" lineJoin="round"/>}
              <Circle name="native-model-point" x={run[0][0]} y={run[0][1]} radius={4/scale} fill={nativeWarning?'#ff9c61':'#62eed2'}/>
            </Group>)}
          </Group>)}
          {!modelDisplay&&nativeCandidate?.segments.map(segment=><Group key={segment.segment_id} name="native-model-segment">
            <Line name="native-model-path" points={segment.points_pixel.flat()} stroke={nativeWarning?'#ff9c61':'#62eed2'}
              strokeWidth={3.5/scale} dash={nativeWarning?[10/scale,6/scale]:undefined} lineCap="round" lineJoin="round" />
            <Circle x={segment.points_pixel[0][0]} y={segment.points_pixel[0][1]} radius={5/scale} fill={nativeWarning?'#ff9c61':'#62eed2'} stroke="#142323" strokeWidth={1.5/scale}/>
          </Group>)}
          {regions.map((region) => {
            const skipped = skippedRegions.includes(region.region_id);
            const text = `Region ${region.region_id}${skipped ? ' · skip' : ''}`;
            const labelWidth = (text.length * 6.5 + 12) / scale;
            const x = Math.max(0, Math.min(region.bounding_box.x_min, scene.width - labelWidth));
            const y = Math.max(0, region.bounding_box.y_min - 24 / scale);
            return <Group key={region.region_id} x={x} y={y}>
              <Rect width={labelWidth} height={19 / scale} fill="#183430" opacity={0.88} cornerRadius={3 / scale} />
              <Text text={text} x={6 / scale} y={4 / scale} fontSize={11 / scale} fill={skipped ? '#b9c3bc' : '#d8f2ba'} />
            </Group>;
          })}
          {cursor && !disabled && <Circle x={cursor[0]} y={cursor[1]} radius={brushSize / 2} stroke="#fff" strokeWidth={1 / scale} dash={tool === 'eraser' ? [4 / scale, 3 / scale] : undefined} />}
        </Layer>
      </Stage>
    </div>}
  </div>;
}
