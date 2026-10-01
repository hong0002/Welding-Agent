import {VIEW_IDS,type Job,type ViewId} from '../types';

export function SceneViews({job,active,disabled,onSelect}:{job:Job;active:ViewId;disabled:boolean;onSelect:(view:ViewId)=>void}){
  return <div className="scene-views" role="tablist" aria-label="Scene views">
    {VIEW_IDS.map(id=>{
      const view=job.scene.views?.[id];
      return <button key={id} role="tab" aria-label={`View ${id}`} aria-selected={active===id}
        disabled={disabled||!view} className={`view-thumb ${active===id?'active':''}`} onClick={()=>onSelect(id)} data-testid={`view-${id}`}>
        {view&&<img src={view.image_url} alt={`${id} view`} loading="lazy"/>}
        <span className="view-name">{id}{active===id&&<small>ACTIVE</small>}</span>
        <span className="view-badges">{view&&<small>IMAGE</small>}{view?.mask&&<small>MASK</small>}{view?.mask?.approved&&<small className="approved">APPROVED</small>}</span>
      </button>;
    })}
  </div>;
}
