// One request/timer at a time; caller stops it on selection/session/state change.
export function pollViewportFrames(url:string,onFrame:(blob:Blob)=>void,onUnavailable:()=>void,onError:()=>void) {
  let alive=true;let timer:number|undefined;
  const controller=new AbortController();
  const poll=async()=>{
    try {
      const response=await fetch(`${url}&version=${Date.now()}`,{cache:'no-store',signal:controller.signal});
      if(!alive)return;
      if(response.status===204){/* Still starting or between atomic JPEG writes. */}
      else if(response.status===409){onUnavailable();return;}
      else if(!response.ok||!response.headers.get('content-type')?.startsWith('image/jpeg')){onError();return;}
      else {const blob=await response.blob();if(alive)onFrame(blob);}
    } catch {if(alive)onError();return;}
    if(alive)timer=window.setTimeout(poll,250);
  };
  void poll();
  return()=>{alive=false;controller.abort();window.clearTimeout(timer);};
}
