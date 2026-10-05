import sys as _release_sys
from pathlib import Path as _ReleasePath
_release_sys.path.insert(0, str(_ReleasePath(__file__).resolve().parents[1]))
from backend.services.project_paths import native_parent
"""Operator-only isolated USD composition check. No app/GUI or live rerun."""
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    project=Path(__file__).resolve().parents[1]
    output=Path(sys.argv[1]).resolve()
    if not output.is_relative_to(project/'.cache/current-vla-preview-smoke') or output.exists():
        raise ValueError('Fresh owned offline report required')
    isaac=Path('D:/isaacsim')
    libs=isaac/'extscache/omni.usd.libs-1.0.3+00c488ae.wx64.r.cp312'
    handles=[os.add_dll_directory(str(p)) for p in (libs/'bin',isaac/'kit/kernel/plugins',isaac/'kit')]
    sys.path.insert(0,str(libs))
    from pxr import Gf, Usd, UsdGeom
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    audit=read(project/'.cache/bpr-geometry-audit/0efd49b0-a360-466e-b7f1-2fe5cdee0d2e/diagnostics.json')
    summary=read(project/'.cache/bpr-tool-clearance/a74cb77c-7d4e-4617-b20d-57a43fcb89cf/summary.json')
    fixed=audit['candidates'][0]['fixed_tool_diagnostic']
    flange=[r+[t] for r,t in zip(fixed['initial_flange_rotation'],fixed['initial_flange_xyz_m'])]+[[0,0,0,1]]
    cad=summary['tool_geometry']['mounted_cad_transform']
    def mult(a,b):return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    combined=mult(flange,cad)
    stage=Usd.Stage.CreateInMemory()
    tool=UsdGeom.Xform.Define(stage,'/Tool')
    tool.AddTransformOp().Set(Gf.Matrix4d([list(row) for row in zip(*combined)]))
    geometry=UsdGeom.Xform.Define(stage,'/Tool/Geometry')
    asset=native_parent(project)/'simulator/ATU01035_welding_tool.usd'
    before=hashlib.sha256(asset.read_bytes()).hexdigest()
    geometry.GetPrim().GetReferences().AddReference(str(asset))
    geometry.AddScaleOp().Set(Gf.Vec3f(.001,.001,.001))
    cache=UsdGeom.XformCache(Usd.TimeCode.Default())
    tip=summary['tool_geometry']['cad_tip_mm']
    actual=list(cache.GetLocalToWorldTransform(geometry.GetPrim()).Transform(Gf.Vec3d(*tip)))
    expected=[sum(combined[i][k]*(tip[k]*.001) for k in range(3))+combined[i][3] for i in range(3)]
    error=max(abs(a-b) for a,b in zip(actual,expected))
    # Float32 USD scale is recorded; this tolerance only checks composition, not clearance.
    assert error<1e-7
    mesh=UsdGeom.Mesh.Define(stage,'/SyntheticAPIProbe')
    mesh.CreatePointsAttr([Gf.Vec3f(0,0,0),Gf.Vec3f(1,0,0),Gf.Vec3f(0,1,0)])
    mesh.CreateFaceVertexCountsAttr([3]);mesh.CreateFaceVertexIndicesAttr([0,1,2]);mesh.CreateDoubleSidedAttr(True)
    forbidden=[m for m in sys.modules if m=='isaacsim' or m.startswith('omni') or 'simulation_app' in m.lower()]
    assert not forbidden and hashlib.sha256(asset.read_bytes()).hexdigest()==before
    output.write_text(json.dumps(dict(verdict='USD_COMPOSITION_OFFLINE_PASS',SimulationApp=0,GUI=0,physics=0,
        source_unchanged=True,forbidden_modules=forbidden,tip_composition_error_m=error),indent=2),encoding='utf-8')
    print(json.dumps({'verdict':'USD_COMPOSITION_OFFLINE_PASS','error_m':error}))


if __name__=='__main__':main()
