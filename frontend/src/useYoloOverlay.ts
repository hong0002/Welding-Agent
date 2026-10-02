import {useEffect,useState} from 'react';
import {api} from './api';
import {VIEW_IDS,type Job,type YoloOverlay} from './types';

const warningCodes=new Set(['YOLO_OUTPUT_NOT_AVAILABLE','YOLO_OUTPUT_STALE','YOLO_SAMPLE_MISMATCH',
  'YOLO_VIEW_MISMATCH','YOLO_COORDINATE_INVALID','YOLO_ARTIFACT_MALFORMED']);

// A display response is tied to the current scene AND original mask lineage.
// Late fetches from another job/session cannot replace the current overlay.
export function useYoloOverlay(job:Job|null,detecting:boolean){
  const artifactId=job?.mask?.artifact?.provenance.native_source_artifact_id;
  const lineage=job&&artifactId?`${job.id}:${job.scene.id}:${artifactId}`:'';
  const revision=`${lineage}:${job?.native_output?.native_artifact_id??''}`;
  const [snapshot,setSnapshot]=useState<{revision:string;data:YoloOverlay|null;warning:string}>();
  useEffect(()=>{
    let active=true;
    if(detecting){setSnapshot(undefined);return;}
    if(!job?.scene.views||!lineage)return;
    void api.yolo(job.id).then(data=>{
      if(!active)return;
      if(data.job_id!==job.id||data.scene_id!==job.scene.id||data.sample_id!==job.scene.sample_id||data.artifact_id!==artifactId)
        throw new Error('binding');
      if(data.coordinate_space!=='image_pixel'||data.frame!=='image_top_left_x_right_y_down'||
          typeof data.available!=='boolean'||!data.views||!Array.isArray(data.warnings))throw new Error('schema');
      for(const [id,view] of Object.entries(data.views)){
        const image=job.scene.views?.[id as typeof VIEW_IDS[number]];
        if(!VIEW_IDS.includes(id as typeof VIEW_IDS[number])||!image||view.image_width!==image.width||
          view.image_height!==image.height||!Array.isArray(view.detections))throw new Error('view');
        const ids=new Set<string>();
        for(const d of view.detections){
          const b=d.bbox;
          if(typeof d.detection_id!=='string'||ids.has(d.detection_id)||!b||
            ![b.x_min,b.y_min,b.x_max,b.y_max].every(Number.isFinite)||
            b.x_min<0||b.x_min>b.x_max||b.x_max>image.width||b.y_min<0||b.y_min>b.y_max||b.y_max>image.height||
            (d.class_id!=null&&(!Number.isInteger(d.class_id)||d.class_id<0))||
            (d.confidence!=null&&(!Number.isFinite(d.confidence)||d.confidence<0||d.confidence>1)))throw new Error('box');
          ids.add(d.detection_id);
        }
      }
      setSnapshot({revision,data,warning:data.warnings.find(code=>warningCodes.has(code)&&code!=='YOLO_OUTPUT_NOT_AVAILABLE')??''});
    }).catch(()=>{if(active)setSnapshot({revision,data:null,warning:'YOLO_ARTIFACT_MALFORMED'});});
    return()=>{active=false;};
  },[revision,detecting]);
  if(detecting)return {overlay:null,warning:'',loading:true};
  if(!lineage)return {overlay:null,warning:'',loading:false};
  if(snapshot?.revision!==revision)return {overlay:null,warning:'',loading:true};
  return {overlay:snapshot.data?.available?snapshot.data:null,warning:snapshot.warning,loading:false};
}
