"""Bounded presentation extraction. No geometry repair or execution authority."""
import json
import math
import re


def finite_runs(points, dimensions=3, connections=None, limit=4096):
    if not isinstance(points, list): return [], 0
    modes = connections
    if modes == ['within_segment']: modes = modes * max(0, len(points)-1)
    if not isinstance(modes, list) or len(modes) != len(points)-1:
        modes = ['within_segment'] * max(0, len(points)-1)
    runs, run, omitted = [], [], 0
    for i, point in enumerate(points[:limit]):
        if i and modes[i-1] != 'within_segment' and run:
            runs.append(run); run = []
        if isinstance(point, dict): point = [point.get(k) for k in ('x','y','z')[:dimensions]]
        try:
            valid = isinstance(point,(list,tuple)) and len(point)==dimensions and all(
                type(v) in (int,float) and math.isfinite(v) for v in point)
        except (ValueError,OverflowError): valid=False
        if valid: run.append(list(point))
        else:
            omitted += 1
            if run: runs.append(run); run=[]
    if run: runs.append(run)
    return runs, omitted


def output_geometry(text):
    """Only points in visible structured output; never SDK errors/reasoning.

    Malformed JSON can retain explicit XYZ objects or triples in the points
    array. Null/invalid rows remain breaks. No free-text coordinate guessing.
    """
    if not isinstance(text,str) or len(text)>1_000_000: return []
    try:
        value=json.loads(text)
        points=value.get('proposal',value).get('points',[]) if isinstance(value,dict) else []
        return points[:4096] if isinstance(points,list) else []
    except (ValueError,TypeError,AttributeError): pass
    marker=re.search(r'"points"\s*:\s*\[',text)
    if not marker: return []
    # Walk rows with JSON decoder; a malformed row introduces a break.
    tail=text[marker.end():]; decoder=json.JSONDecoder(); points=[]; pos=0
    while pos<len(tail) and len(points)<4096:
        while pos<len(tail) and tail[pos] in ' \r\n\t,':pos+=1
        if pos==len(tail) or tail[pos]==']':break
        try:
            row,end=decoder.raw_decode(tail,pos)
            points.append(row if isinstance(row,(dict,list)) else None);pos=end
        except ValueError:
            points.append(None)
            end=tail.find(',',pos)
            if end<0:break
            pos=end+1
    return points


def presentation(*, exists, renderable, validated=False, approved=False, simulation=False, robot=False, stale=False):
    return dict(OUTPUT_EXISTS=bool(exists),OUTPUT_RENDERABLE=bool(renderable),
        OUTPUT_VALIDATED=bool(validated),OUTPUT_APPROVED=bool(approved),
        SIMULATION_DISPLAYABLE=bool(simulation and renderable),ROBOT_PLAYBACK_READY=bool(robot),
        CURRENT_RESULT=bool(exists and not stale),STALE_RESULT=bool(stale),
        SIMULATION_VISUALIZABLE=bool(simulation and renderable),PHYSICAL_EXECUTION_READY=False,
        physical_robot_executable=False)
