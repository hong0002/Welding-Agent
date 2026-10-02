import {Group,Layer,Rect,Text} from 'react-konva';
import type {YoloDetection,YoloView,YoloOverlay,ViewId} from '../types';

export function yoloLabel(d:YoloDetection){
  const name=d.class_id==null?'Object':`Class ${d.class_id}`;
  return `${name}${d.confidence==null?'':` ${d.confidence.toFixed(2)}`}`.slice(0,32);
}

export function YoloObjects({view,scale}:{view:YoloView;scale:number}){
  return <Layer name="yolo-objects" listening={false}>
    {view.detections.map(d=>{
      const b=d.bbox,text=`YOLO · ${yoloLabel(d)}`,width=Math.min(view.image_width,(text.length*6.5+12)/scale);
      return <Group key={d.detection_id} id={d.detection_id}>
        <Rect name="yolo-bbox" x={b.x_min} y={b.y_min} width={b.x_max-b.x_min} height={b.y_max-b.y_min}
          stroke="#58baff" strokeWidth={1.5/scale}/>
        <Group x={Math.max(0,Math.min(b.x_min,view.image_width-width))}
          y={Math.max(0,Math.min(b.y_max+3/scale,view.image_height-19/scale))}>
          <Rect width={width} height={19/scale} fill="#16334a" opacity={0.94} cornerRadius={3/scale}/>
          <Text name="yolo-label" text={text} x={6/scale} y={4/scale} fontSize={11/scale} fill="#b6e1ff"/>
        </Group>
      </Group>;
    })}
  </Layer>;
}

export function YoloSummary({overlay,view,warning,loading,maskSource}:{overlay:YoloOverlay|null;view:ViewId;
  warning:string;loading:boolean;maskSource:string}){
  const detections=overlay?.views[view]?.detections??[];
  return <section className="yolo-summary" data-testid="yolo-summary" aria-label="YOLO Object Detection">
    <div><strong>YOLO Object Detection</strong><span>View {view} · {detections.length}</span></div>
    <p>{loading?'YOLO 결과 확인 중…':overlay?.views[view]?`Segment2 detection · ${detections.length} objects`:'YOLO 결과 없음'}</p>
    {warning&&<p className="yolo-warning" role="status">YOLO 표시를 확인하세요 · {warning}</p>}
    {!!detections.length&&<ol>{detections.map(d=><li key={d.detection_id}>{yoloLabel(d)}</li>)}</ol>}
    {overlay&&<small>YOLO source: Segment2 detection · Mask source: {maskSource}
      {overlay.trajectory3_reuse_verified&&<span data-testid="yolo-reuse">Trajectory3 YOLO reuse: verified</span>}</small>}
  </section>;
}
