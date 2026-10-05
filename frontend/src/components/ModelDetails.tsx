import type {ReactNode} from 'react';
import type {NativeOutput,ViewId,YoloOverlay} from '../types';

export function ModelDetails({output,approved,overlay,view,loading,warning,children}:{
  output:NativeOutput|null|undefined;approved:boolean;overlay:YoloOverlay|null;view:ViewId;
  loading:boolean;warning:string;children:ReactNode;
}) {
  const validation=output?.validation.status;
  const raw=output?.model_output?.status==='OUTPUT_RAW_DISPLAYABLE';
  const warned=validation==='WARN'||raw||!!output?.model_output?.warnings.length;
  const segment=validation==='FAIL'?'⚠ VALIDATION FAILED':warned?'⚠ WARNING · RAW / UNVALIDATED':
    validation==='PASS'?'✓ PASS':'출력 없음';
  const detections=overlay?.views[view]?.detections;
  return <details className="inspector-model-details" data-testid="model-details">
    <summary aria-label="모델 상태 상세 접기/펼치기">
      <strong>모델 상태</strong>
      <span data-testid="model-status-summary" className={validation==='FAIL'||warned?'model-warning':''}>
        Segment2 {segment}{output?approved?' · APPROVED':' · Approval required':''}
      </span>
      <span data-testid="yolo-status-summary" className={warning||!detections?'model-warning':''}>
        YOLO {loading?'확인 중…':warning?'⚠ WARNING':detections?`✓ ${view} · ${detections.length} objects`:'⚠ unavailable'}
      </span>
    </summary>
    <div className="model-details-content">{children}</div>
  </details>;
}
